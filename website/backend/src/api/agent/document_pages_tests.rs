//! Route tests of the document page reads on a fixture of 1,200 page ids. The local
//! corpus holds no document with more than 1,000 pages, so an in-memory [`TextPages`]
//! stands in for `text_content` and the Manticore shard, and counts every read.

use std::cell::Cell;

use super::*;

const FIXTURE_PAGES: u32 = 1_200;

/// Page ids 1 to 1,200, with every seventh id absent, as the text writer drops a page
/// with less than 2 characters. Every third page holds 2 hits of the word `needle`.
struct FixturePages {
    text_reads: Cell<usize>,
    hit_reads: Cell<usize>,
}

impl FixturePages {
    fn new() -> Self {
        Self { text_reads: Cell::new(0), hit_reads: Cell::new(0) }
    }

    fn stored(page_id: u32) -> bool {
        (1..=FIXTURE_PAGES).contains(&page_id) && page_id % 7 != 0
    }

    fn hits_on(page_id: u32) -> u64 {
        if Self::stored(page_id) && page_id % 3 == 0 { 2 } else { 0 }
    }

    fn counts() -> Vec<(u32, u64)> {
        (1..=FIXTURE_PAGES).filter(|page| Self::hits_on(*page) > 0).map(|page| (page, Self::hits_on(page))).collect()
    }
}

fn span(text: &str, is_highlighted: bool) -> HighlightTextSpan {
    HighlightTextSpan { text: text.to_string(), is_highlighted, index: 0 }
}

impl TextPages for FixturePages {
    async fn extent(&self, _extracted_by: &str) -> Result<(u64, u32), AgentError> {
        let stored: Vec<u32> = (1..=FIXTURE_PAGES).filter(|page| Self::stored(*page)).collect();
        Ok((stored.len() as u64, stored.last().copied().unwrap_or(0)))
    }

    async fn page_text(&self, _extracted_by: &str, page_id: u32) -> Result<Option<String>, AgentError> {
        self.text_reads.set(self.text_reads.get() + 1);
        Ok(Self::stored(page_id).then(|| format!("page {page_id} text")))
    }

    async fn page_after(&self, _extracted_by: &str, page_id: u32) -> Result<Option<u32>, AgentError> {
        Ok((page_id + 1..=FIXTURE_PAGES).find(|page| Self::stored(*page)))
    }

    async fn page_hits(&self, _extracted_by: &str, page_id: u32, _query: &str) -> Result<Vec<HighlightTextSpan>, AgentError> {
        self.hit_reads.set(self.hit_reads.get() + 1);
        if Self::hits_on(page_id) == 0 {
            return Ok(Vec::new());
        }
        Ok(vec![span("a ", false), span("needle", true), span(" and ", false), span("needle", true), span(" end", false)])
    }
}

#[tokio::test]
async fn each_read_documents_call_reads_one_page_of_a_long_document() {
    let pages = FixturePages::new();
    let mut page_id = 1;
    let mut calls = 0;
    loop {
        let before = pages.text_reads.get();
        let (text, next) = read_text_page(&pages, "pdftotext", page_id).await.ok().expect("a stored page reads");
        assert_eq!(pages.text_reads.get() - before, 1, "one call reads one page");
        assert_eq!(text, format!("page {page_id} text"));
        calls += 1;
        match next {
            Some(next) => {
                assert!(FixturePages::stored(next) && next > page_id);
                page_id = next;
            }
            None => break,
        }
    }
    let stored = (1..=FIXTURE_PAGES).filter(|page| FixturePages::stored(*page)).count();
    assert!(stored > 1_000);
    assert_eq!(calls, stored, "the next positions skip the gaps and reach the last page");
    assert_eq!(pages.extent("pdftotext").await.ok(), Some((stored as u64, page_id)));
}

#[tokio::test]
async fn a_page_id_in_a_gap_is_not_found() {
    let error = read_text_page(&FixturePages::new(), "pdftotext", 700).await.err().expect("page 700 is absent");
    assert_eq!(error.status, StatusCode::NOT_FOUND);
    assert_eq!(error.error, "not_found");
}

#[test]
fn the_most_hits_page_takes_the_lowest_page_on_a_tie() {
    assert_eq!(most_hits_page(&[(4, 1), (9, 5), (12, 5), (30, 2)]), Some(9));
    assert_eq!(most_hits_page(&[]), None);
}

#[tokio::test]
async fn search_text_pages_every_hit_and_reads_only_the_pages_it_returns() {
    let pages = FixturePages::new();
    let counts = FixturePages::counts();
    let expected: u64 = counts.iter().map(|(_, count)| count).sum();
    let mut after = None;
    let mut seen = Vec::new();
    loop {
        let before = pages.hit_reads.get();
        let (hits, next) = text_hits_page(&pages, "pdftotext", "needle", &counts, after, TEXT_HITS_PAGE_SIZE)
            .await
            .ok()
            .expect("hits read");
        let mut returned_pages: Vec<u32> = hits.iter().map(|hit| hit.page).collect();
        returned_pages.dedup();
        assert_eq!(pages.hit_reads.get() - before, returned_pages.len(), "a call reads only the pages of its hits");
        assert!(hits.len() <= TEXT_HITS_PAGE_SIZE);
        seen.extend(hits.iter().map(|hit| (hit.page, hit.ordinal)));
        match next {
            Some(AgentPosition::HitKey { page_id, ordinal }) => after = Some((page_id, ordinal)),
            Some(other) => panic!("unexpected position {other:?}"),
            None => break,
        }
    }
    let mut unique = seen.clone();
    unique.sort_unstable();
    unique.dedup();
    assert_eq!(seen.len() as u64, expected);
    assert_eq!(unique.len(), seen.len());
    assert_eq!(unique, seen, "hits come in page order");
}

#[test]
fn a_hit_carries_its_offsets_and_a_snippet() {
    let hits = hits_from_spans(3, &[span("a ", false), span("needle", true), span(" end", false)]);
    assert_eq!(hits, vec![AgentTextHit { page: 3, ordinal: 0, start: 2, end: 8, snippet: "a needle end".into() }]);
}

#[test]
fn a_long_metadata_value_is_cut_with_the_marker() {
    let long = "é".repeat(MAX_METADATA_VALUE_CHARS + 5);
    let mut value = serde_json::json!({ "short": "x", "a/b": long });
    cut_long_strings(&mut value, "/tika_metadata/0");
    assert_eq!(value["short"], "x");
    let cut = &value["a/b"];
    assert_eq!(cut["text"].as_str().map(|text| text.chars().count()), Some(MAX_METADATA_VALUE_CHARS));
    assert_eq!(cut["cut"]["field"], "/tika_metadata/0/a~1b");
    assert_eq!(cut["cut"]["returned_bytes"], (MAX_METADATA_VALUE_CHARS * 2) as u64);
    assert_eq!(cut["cut"]["total_bytes"], ((MAX_METADATA_VALUE_CHARS + 5) * 2) as u64);
}

fn pdf_results(pages: &[(i32, i32)]) -> PdfSearchResults {
    let results: Vec<serde_json::Value> = pages
        .iter()
        .map(|(page, index)| {
            serde_json::json!({
                "pageIndex": page, "charIndex": index, "charCount": 3, "rects": [],
                "context": {"before": "", "match": "the", "after": "", "truncatedLeft": false, "truncatedRight": false}
            })
        })
        .collect();
    serde_json::from_value(serde_json::json!({ "results": results, "total": pages.len() })).expect("fixture parses")
}

#[test]
fn pdf_hits_filter_by_page_range_and_continue_by_hit_key() {
    let results = pdf_results(&[(0, 1), (1, 1), (1, 9), (2, 4), (2, 8), (5, 0)]);
    let (hits, total, next) = pdf_hits_page(&results, Some(1), Some(2), None, 3);
    assert_eq!(total, 4);
    assert_eq!(hits.iter().map(|hit| (hit.page, hit.start)).collect::<Vec<_>>(), vec![(1, 1), (1, 9), (2, 4)]);
    assert_eq!(next, Some(AgentPosition::HitKey { page_id: 2, ordinal: 0 }));
    let (hits, _, next) = pdf_hits_page(&results, Some(1), Some(2), Some((2, 0)), 3);
    assert_eq!(hits.iter().map(|hit| (hit.page, hit.start)).collect::<Vec<_>>(), vec![(2, 8)]);
    assert_eq!(next, None);
}

#[test]
fn the_pdf_cache_keeps_sixteen_recent_results_for_ten_minutes() {
    let start = std::time::Instant::now();
    let key = |n: usize| (String::from("c_d"), format!("hash{n}"), String::new(), String::from("q"));
    let mut cache = PdfSearchCache::default();
    for n in 0..PDF_CACHE_ENTRIES {
        cache.put(key(n), std::sync::Arc::new(pdf_results(&[])), start);
    }
    assert!(cache.get(&key(0), start).is_some(), "a read makes the entry the most recent");
    cache.put(key(99), std::sync::Arc::new(pdf_results(&[])), start);
    assert!(cache.get(&key(0), start).is_some());
    assert!(cache.get(&key(1), start).is_none(), "the least recent entry goes first");
    assert!(cache.get(&key(0), start + PDF_CACHE_TTL).is_none(), "an entry expires after the TTL");
}

#[test]
fn a_source_count_names_its_state() {
    assert_eq!(source_count_state(SourceCount::Counted { hits: 3, stopped_at_limit: false }), (Some(3), "counted"));
    assert_eq!(
        source_count_state(SourceCount::Counted { hits: 900, stopped_at_limit: true }),
        (Some(900), "partial"),
        "a text read that returned its 1,000-row limit is partial"
    );
    assert_eq!(source_count_state(SourceCount::TimedOut), (None, "timed_out"));
    assert_eq!(source_count_state(SourceCount::Failed), (None, "failed"), "a failed count is not a count of 0");
}
