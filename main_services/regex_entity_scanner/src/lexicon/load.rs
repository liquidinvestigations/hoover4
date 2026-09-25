//! Reading the lexicon directory, and every check that refuses a malformed one at startup.
//!
//! A term file that is wrong in a way the matcher cannot notice (a duplicate that makes one match
//! count twice, a `*` in the middle of a phrase that silently never matches, a category that exists
//! in one language and not another) is refused here, with the file and line, instead of loading as a
//! lexicon that quietly answers less than it claims to.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use sha2::{Digest, Sha256};

use super::fold::fold_term;
use super::{Boundary, CategoryDoc, Review, Speaker, Term, Tier};

/// The header every term file starts with, in this order.
const TERM_HEADER: &str = "term\ttier\tspeaker\tconcept\tsource\treview\tnote";
const CATEGORY_HEADER: &str = "id\ttitle\tcatches\tdoes_not_prove";

/// A prefix shorter than this matches too many unrelated words to be a signal of anything.
const MIN_STEM_CHARS: usize = 3;

/// A double quote inside a cell is legal to this loader but not to the CSV-style readers that
/// treat `"` as a field quote, GitHub's file view among them, which then refuse the whole file.
/// The lists are meant to be read and searched there, so a quote is refused at load time.
fn refuse_quotes(line: &str, at: impl Fn() -> String) -> Result<()> {
    if line.contains('"') {
        bail!(
            "{}: a double quote makes the file unreadable to CSV-style TSV readers; rephrase \
             without it",
            at()
        );
    }
    Ok(())
}

pub struct Loaded {
    pub categories: Vec<CategoryDoc>,
    pub languages: Vec<String>,
    pub terms: Vec<Term>,
    pub version: String,
}

pub fn load(root: &Path) -> Result<Loaded> {
    let mut hasher = Sha256::new();

    let categories_path = root.join("categories.tsv");
    let raw = std::fs::read_to_string(&categories_path).with_context(|| {
        format!(
            "reading the lexicon categories at {}",
            categories_path.display()
        )
    })?;
    hasher.update(raw.as_bytes());
    let categories = parse_categories(&raw, &categories_path)?;
    let category_index: HashMap<&str, usize> = categories
        .iter()
        .enumerate()
        .map(|(index, doc)| (doc.id.as_str(), index))
        .collect();

    let mut languages: Vec<String> = std::fs::read_dir(root)
        .with_context(|| format!("listing the lexicon at {}", root.display()))?
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.path().is_dir())
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter(|name| name != "licenses")
        .collect();
    languages.sort();
    if languages.is_empty() {
        bail!(
            "the lexicon at {} holds no language directory",
            root.display()
        );
    }

    let mut terms = Vec::new();
    for lang in &languages {
        let dir = root.join(lang);
        let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
            .with_context(|| format!("listing {}", dir.display()))?
            .filter_map(|entry| entry.ok().map(|entry| entry.path()))
            .filter(|path| path.extension().is_some_and(|ext| ext == "tsv"))
            .collect();
        files.sort();
        for doc in &categories {
            if !files.iter().any(|path| file_stem(path) == doc.id) {
                bail!(
                    "{} has no file for the category {}; every language holds every category",
                    dir.display(),
                    doc.id
                );
            }
        }
        // Where each folded term was first seen in this language, so a duplicate names both lines.
        let mut seen: HashMap<(String, Boundary), String> = HashMap::new();
        for path in &files {
            let stem = file_stem(path);
            let Some(&category) = category_index.get(stem.as_str()) else {
                bail!(
                    "{} is not a category listed in {}",
                    path.display(),
                    categories_path.display()
                );
            };
            let raw = std::fs::read_to_string(path)
                .with_context(|| format!("reading {}", path.display()))?;
            hasher.update(lang.as_bytes());
            hasher.update(stem.as_bytes());
            hasher.update(raw.as_bytes());
            for term in parse_terms(&raw, path, lang, category)? {
                let key = (term.folded.clone(), term.boundary);
                let here = format!("{}:{}", path.display(), term.line);
                if let Some(first) = seen.insert(key, here.clone()) {
                    bail!(
                        "{here} repeats a term already at {first}: {:?}; a term belongs to one \
                         category per language",
                        term.term
                    );
                }
                terms.push(term);
            }
        }
    }

    let digest = hasher.finalize();
    let version = digest[..6]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok(Loaded {
        categories,
        languages,
        terms,
        version,
    })
}

fn file_stem(path: &Path) -> String {
    path.file_stem()
        .and_then(|stem| stem.to_str())
        .unwrap_or_default()
        .to_string()
}

fn parse_categories(raw: &str, path: &Path) -> Result<Vec<CategoryDoc>> {
    let mut lines = raw.lines();
    if lines.next() != Some(CATEGORY_HEADER) {
        bail!(
            "{} must start with the header {CATEGORY_HEADER:?}",
            path.display()
        );
    }
    let mut out = Vec::new();
    for (index, line) in lines.enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        refuse_quotes(line, || format!("{}:{}", path.display(), index + 2))?;
        let cells: Vec<&str> = line.split('\t').collect();
        let [id, title, catches, does_not_prove] = cells[..] else {
            bail!(
                "{}:{} has {} columns; expected 4",
                path.display(),
                index + 2,
                cells.len()
            );
        };
        if id.is_empty() || !id.bytes().all(|b| b.is_ascii_lowercase() || b == b'_') {
            bail!(
                "{}:{}: category id {id:?} must be lowercase letters and underscores",
                path.display(),
                index + 2
            );
        }
        out.push(CategoryDoc {
            id: id.to_string(),
            title: title.to_string(),
            catches: catches.to_string(),
            does_not_prove: does_not_prove.to_string(),
        });
    }
    if out.is_empty() {
        bail!("{} lists no category", path.display());
    }
    Ok(out)
}

fn parse_terms(raw: &str, path: &Path, lang: &str, category: usize) -> Result<Vec<Term>> {
    let mut lines = raw.lines();
    if lines.next() != Some(TERM_HEADER) {
        bail!(
            "{} must start with the header {TERM_HEADER:?}",
            path.display()
        );
    }
    let mut out = Vec::new();
    for (index, line) in lines.enumerate() {
        let line_no = index + 2;
        if line.trim().is_empty() {
            continue;
        }
        let at = || format!("{}:{line_no}", path.display());
        refuse_quotes(line, at)?;
        let cells: Vec<&str> = line.split('\t').collect();
        let [term, tier, speaker, concept, source, review, note] = cells[..] else {
            bail!("{} has {} columns; expected 7", at(), cells.len());
        };
        let (body, boundary) = match term.strip_suffix('*') {
            Some(body) => (body, Boundary::Prefix),
            None => (term, Boundary::Word),
        };
        if body.contains('*') {
            bail!(
                "{}: {term:?} has a `*` inside it; only a trailing `*` means anything, and one \
                 anywhere else would never match",
                at()
            );
        }
        let folded = fold_term(body);
        if folded.is_empty() {
            bail!("{}: {term:?} is empty once folded", at());
        }
        if boundary == Boundary::Prefix && folded.chars().count() < MIN_STEM_CHARS {
            bail!(
                "{}: the stem {term:?} is shorter than {MIN_STEM_CHARS} characters",
                at()
            );
        }
        let tier = match tier {
            "H" => Tier::H,
            "M" => Tier::M,
            "L" => Tier::L,
            other => bail!("{}: tier {other:?} is not H, M or L", at()),
        };
        let speaker = match speaker {
            "actor" => Speaker::Actor,
            "insider" => Speaker::Insider,
            "accuser" => Speaker::Accuser,
            "neutral" => Speaker::Neutral,
            other => bail!(
                "{}: speaker {other:?} is not actor, insider, accuser or neutral",
                at()
            ),
        };
        let review = match review {
            "original" => Review::Original,
            "mt-edited" => Review::MtEdited,
            "native" => Review::Native,
            other => bail!(
                "{}: review {other:?} is not original, mt-edited or native",
                at()
            ),
        };
        if concept.trim().is_empty() || source.trim().is_empty() {
            bail!("{}: concept and source must not be empty", at());
        }
        out.push(Term {
            term: term.to_string(),
            folded,
            boundary,
            category,
            lang: lang.to_string(),
            tier,
            speaker,
            concept: concept.to_string(),
            source: source.to_string(),
            review,
            note: note.to_string(),
            line: line_no,
        });
    }
    Ok(out)
}

/// Term counts per category and language, for `/signals`.
pub fn counts(terms: &[Term], categories: usize) -> Vec<BTreeMap<String, usize>> {
    let mut out = vec![BTreeMap::new(); categories];
    for term in terms {
        *out[term.category].entry(term.lang.clone()).or_insert(0) += 1;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::{parse_terms, TERM_HEADER};
    use std::path::Path;

    #[test]
    fn a_double_quote_in_a_row_is_refused() {
        let raw = format!(
            "{TERM_HEADER}\ntold me to\tM\tinsider\ttold me to\tcurated\toriginal\ta \"quoted\" note\n"
        );
        let err =
            parse_terms(&raw, Path::new("en/x.tsv"), "en", 0).expect_err("the row is refused");
        assert!(err.to_string().contains("en/x.tsv:2"), "{err}");
    }
}
