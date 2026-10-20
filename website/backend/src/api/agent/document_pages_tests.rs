//! Route tests of the document page reads on a fixture of 1,200 page ids. An in-memory
//! [`TextPages`] stands in for `text_content` and the Manticore shard, and counts every
//! read. The live `p63pages` fixture collection checks the same reads in
//! `tests/stack_integration.rs`.

use std::cell::Cell;

use super::*;

const FIXTURE_PAGES: u32 = 1_200;

/// Page ids 1 to 1,200, with every seventh id absent, as the text writer drops a page
/// with less than 2 characters. Every third page holds 2 hits of the word `needle`.
struct FixturePages {
    text_reads: Cell<usize>,
    hit_reads: Cell<usize>,
    batch_reads: Cell<usize>,
}

impl FixturePages {
    fn new() -> Self {
        Self { text_reads: Cell::new(0), hit_reads: Cell::new(0), batch_reads: Cell::new(0) }
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
    async fn revision(&self, _extracted_by: &str) -> Result<SourceRevision, AgentError> {
        let stored: Vec<u32> = (1..=FIXTURE_PAGES).filter(|page| Self::stored(*page)).collect();
        let last = stored.last().copied().unwrap_or(0);
        Ok(SourceRevision { stored_count: stored.len() as u64, revision: format!("{}:1-{last}:5", stored.len()) })
    }

    async fn page_text(&self, _extracted_by: &str, page_id: u32) -> Result<Option<String>, AgentError> {
        self.text_reads.set(self.text_reads.get() + 1);
        Ok(Self::stored(page_id).then(|| format!("page {page_id} text")))
    }

    async fn page_after(&self, _extracted_by: &str, page_id: u32) -> Result<Option<u32>, AgentError> {
        Ok((page_id + 1..=FIXTURE_PAGES).find(|page| Self::stored(*page)))
    }

    async fn page_hits(&self, _extracted_by: &str, page_id: u32, _query: &str) -> Result<PageHighlights, AgentError> {
        self.hit_reads.set(self.hit_reads.get() + 1);
        if Self::hits_on(page_id) == 0 {
            return Ok(PageHighlights::NoMatch);
        }
        Ok(PageHighlights::Spans(vec![span("a ", false), span("needle", true), span(" and ", false), span("needle", true), span(" end", false)]))
    }

    /// Only `pdftotext` holds matching pages. Another source has none of its own, so it
    /// shows that one source's matches do not fill another source's batch.
    async fn matching_pages(&self, extracted_by: &str, _query: &str, after: Option<u32>) -> Result<MatchBatch, AgentError> {
        self.batch_reads.set(self.batch_reads.get() + 1);
        if extracted_by != "pdftotext" {
            return Ok(MatchBatch::default());
        }
        let rows: Vec<u32> = (after.map_or(1, |page| page + 1)..=FIXTURE_PAGES)
            .filter(|page| Self::hits_on(*page) > 0)
            .take(MATCH_BATCH_ROWS + 1)
            .collect();
        Ok(document_text::fold_match_rows(&rows, MATCH_BATCH_ROWS))
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
    assert_eq!(pages.revision("pdftotext").await.ok().map(|r| r.stored_count), Some(stored as u64));
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
        let TextHitsPage { hits, next_position: next, unverified } =
            text_hits_page(&pages, "pdftotext", "needle", after, TEXT_HITS_PAGE_SIZE)
                .await
                .ok()
                .expect("hits read");
        assert!(!unverified, "every page holds its stored text");
        let mut returned_pages: Vec<u32> = hits.iter().map(|hit| hit.page).collect();
        returned_pages.dedup();
        let resumed = usize::from(after.is_some());
        assert!(
            pages.hit_reads.get() - before <= returned_pages.len() + resumed,
            "a call reads the pages of its hits and the page it resumes on"
        );
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
    assert!(counts.len() > MATCH_BATCH_ROWS, "the walk crosses a match batch boundary");
    assert_eq!(seen.last().map(|hit| hit.0), counts.last().map(|count| count.0), "the walk reaches the last matching page");
    assert!(pages.hit_reads.get() <= counts.len() * 2, "no page body is highlighted more than twice");
}

#[tokio::test]
async fn another_source_takes_no_part_of_the_match_batches() {
    let pages = FixturePages::new();
    let page = text_hits_page(&pages, "extractous", "needle", None, TEXT_HITS_PAGE_SIZE).await.ok().expect("hits read");
    assert!(page.hits.is_empty() && page.next_position.is_none());
    assert_eq!(pages.hit_reads.get(), 0, "a source with no matching rows reads no page");
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


struct LongTextPage;

impl TextPages for LongTextPage {
    async fn revision(&self, _: &str) -> Result<SourceRevision, AgentError> {
        Ok(SourceRevision { stored_count: 1, revision: "1:7-7:3".into() })
    }
    async fn page_text(&self, _: &str, _: u32) -> Result<Option<String>, AgentError> {
        Ok(Some(format!("{}needle{}", "é".repeat(50_000), "z".repeat(10_000))))
    }
    async fn page_after(&self, _: &str, _: u32) -> Result<Option<u32>, AgentError> { Ok(None) }
    async fn page_hits(&self, _: &str, _: u32, _: &str) -> Result<PageHighlights, AgentError> {
        Ok(PageHighlights::Spans(vec![span(&"é".repeat(50_000), false), span("needle", true), span(&"z".repeat(10_000), false)]))
    }
    async fn matching_pages(&self, _: &str, _: &str, after: Option<u32>) -> Result<MatchBatch, AgentError> {
        Ok(MatchBatch { pages: if after.is_none() { vec![7] } else { Vec::new() }, continue_after: None })
    }
}

#[tokio::test]
async fn a_query_opens_a_late_passage_with_explicit_character_continuation() {
    let first = read_text_range(&LongTextPage, "raw_text", 7, Some("needle"), None, 6_000).await.ok().expect("the character range must read");
    assert!(first.0.contains("needle"));
    assert_eq!((first.1, first.2, first.3), (49_000, 55_000, 60_006));
    let again = read_text_range(&LongTextPage, "raw_text", 7, Some("needle"), None, 6_000).await.ok().expect("the character range must read");
    assert_eq!(first.0, again.0);
    let Some(AgentPosition::TextPage { source, page_id, offset: Some(offset) }) = first.4 else {
        panic!("the passage must provide its next character position");
    };
    let next = read_text_range(&LongTextPage, &source, page_id, Some("needle"), Some(offset), 6_000).await.ok().expect("the character range must read");
    assert_eq!((next.1, next.2, next.3), (55_000, 60_006, 60_006));
    assert_eq!(next.0, "z".repeat(5_006));
    assert!(next.4.is_none());
    let before = read_text_range(&LongTextPage, "raw_text", 7, None, Some(43_000), 6_000).await.ok().expect("the character range must read");
    assert_eq!((before.1, before.2), (43_000, 49_000));
}

#[test]
fn text_ranges_use_characters_and_reject_offsets_beyond_the_page() {
    assert_eq!(text_range("é中x", 1, 2).ok().expect("the character range must read"), ("中x".into(), 1, 3, 3));
    assert!(text_range("é中x", 4, 2).is_err());
    assert_eq!(text_range("é中x", 3, 2).ok().expect("the character range must read"), (String::new(), 3, 3, 3));
}

#[test]
fn a_targeted_passage_prefers_distinct_words_together() {
    let spans = vec![span("promising", true), span(&"x".repeat(50_000), false),
                     span("highly", true), span(" ", false), span("promising", true),
                     span(" ", false), span("species", true)];
    assert_eq!(matching_passage(&spans, 6_000), Some((50_009, 50_033)));
    assert_eq!(matching_passage(&spans, 10), Some((0, 9)));
}

#[test]
fn a_single_match_keeps_the_first_passage_and_no_matches_select_no_range() {
    let spans = vec![span("needle", true), span(" gap ", false), span("needle", true)];
    assert_eq!(matching_passage(&spans, 6_000), Some((0, 6)));
    assert_eq!(matching_passage(&[span("unmatched", false)], 6_000), None);
}


#[tokio::test]
async fn a_short_requested_range_still_contains_the_query_hit() {
    let result = read_text_range(&LongTextPage, "raw_text", 7, Some("needle"), None, 10)
        .await.ok().expect("the matching range must read");
    assert!(result.0.contains("needle"));
    assert_eq!((result.1, result.2), (49_996, 50_006));
}

#[test]
fn omitted_and_explicit_office_pdf_sources_select_the_preview() {
    use common::document_sources::DocumentPdfSourceItem;
    let preview=DocumentPdfSourceItem {source_kind:"preview".into(),page_count:2,..Default::default()};
    let ocr=DocumentPdfSourceItem {engine:"tesseract".into(),languages:"eng".into(),..preview.clone()};
    let available=[ocr.clone(),preview.clone()];
    assert_eq!(select_pdf_source(&available,""),Some(preview.clone()));
    assert_eq!(select_pdf_source(&available,"preview"),Some(preview));
    assert_eq!(select_pdf_source(&available,"pdfocr_tesseract_eng"),Some(ocr));
    assert!(select_pdf_source(&[],"").is_none());
}


/// Pages 1 to 6 of one source. Each holds the word `needle` twice in its stored text. The
/// index rows of page 3 hold an older text, and page 5 has index rows and no stored text.
struct CheckedPages;

impl CheckedPages {
    fn stored(page_id: u32) -> bool {
        (1..=6).contains(&page_id) && page_id != 5
    }
}

impl TextPages for CheckedPages {
    async fn revision(&self, _: &str) -> Result<SourceRevision, AgentError> {
        Ok(SourceRevision { stored_count: 5, revision: "5:1-6:9".into() })
    }
    async fn page_text(&self, _: &str, page_id: u32) -> Result<Option<String>, AgentError> {
        Ok(Self::stored(page_id).then(|| "a needle and needle".to_string()))
    }
    async fn page_after(&self, _: &str, page_id: u32) -> Result<Option<u32>, AgentError> {
        Ok((page_id + 1..=6).find(|page| Self::stored(*page)))
    }
    async fn page_hits(&self, _: &str, page_id: u32, _: &str) -> Result<PageHighlights, AgentError> {
        let current = "a <hoover4_strong>needle</hoover4_strong> and <hoover4_strong>needle</hoover4_strong>".to_string();
        let older = "an <hoover4_strong>needle</hoover4_strong> of old".to_string();
        let stored = match self.page_text("raw_text", page_id).await? {
            Some(text) => text,
            None => return Ok(PageHighlights::NoMatch),
        };
        // Page 4 has a duplicate index row. The first row that holds the stored text counts.
        let rows = match page_id {
            3 => vec![older],
            4 => vec![current.clone(), current],
            _ => vec![current],
        };
        Ok(document_text::highlights_for_body(&rows, &stored))
    }
    async fn matching_pages(&self, _: &str, _: &str, after: Option<u32>) -> Result<MatchBatch, AgentError> {
        // The stored-page check of the route drops page 5, which has no stored text.
        let rows: Vec<u32> = (after.map_or(1, |page| page + 1)..=6).filter(|page| Self::stored(*page)).collect();
        Ok(document_text::fold_match_rows(&rows, MATCH_BATCH_ROWS))
    }
}

#[tokio::test]
async fn a_page_whose_index_holds_another_text_gives_no_hit_and_marks_the_page_unverified() {
    let page = text_hits_page(&CheckedPages, "raw_text", "needle", None, TEXT_HITS_PAGE_SIZE).await.ok().expect("hits read");
    let pages: Vec<(u32, u32)> = page.hits.iter().map(|hit| (hit.page, hit.ordinal)).collect();
    assert_eq!(pages, vec![(1, 0), (1, 1), (2, 0), (2, 1), (4, 0), (4, 1), (6, 0), (6, 1)]);
    assert!(page.unverified, "page 3 holds an older index text");
    assert!(page.hits.iter().all(|hit| hit.snippet == "a needle and needle"), "every snippet is the stored text");
    // A continuation from page 3 starts after the unverified page.
    let after = text_hits_page(&CheckedPages, "raw_text", "needle", Some((3, 0)), 2).await.ok().expect("hits read");
    assert_eq!(after.hits.iter().map(|hit| hit.page).collect::<Vec<_>>(), vec![4, 4]);
    assert!(after.unverified, "the resumed page holds an older index text");
}

fn text_counts(hits: &[(&str, u32, u64)], stopped_at_limit: bool, differs: &[&str]) -> search_document_itemcount::TextCounts {
    search_document_itemcount::TextCounts {
        hits: hits
            .iter()
            .map(|(source, page_id, hit_count)| common::document_sources::DocumentTextSourceHitCount {
                extracted_by: source.to_string(),
                page_id: *page_id,
                hit_count: *hit_count,
            })
            .collect(),
        stopped_at_limit,
        differs: differs.iter().map(|source| source.to_string()).collect(),
    }
}

#[test]
fn a_source_count_is_exact_only_when_every_index_row_was_checked() {
    let exact = source_counts_of(&text_counts(&[("raw_text", 4, 2), ("raw_text", 1, 1), ("ocr", 2, 9)], false, &[]), "raw_text");
    assert_eq!((exact.pages.clone(), exact.hits(), exact.state()), (vec![(1, 1), (4, 2)], 3, "exact"));
    let limited = source_counts_of(&text_counts(&[("raw_text", 1, 1)], true, &[]), "raw_text");
    assert_eq!((limited.hits(), limited.state()), (1, "lower_bound"), "the index read stopped at its row limit");
    let differs = source_counts_of(&text_counts(&[("raw_text", 1, 1)], false, &["raw_text"]), "raw_text");
    assert_eq!(differs.state(), "lower_bound", "an index row of the source holds another text");
    let other = source_counts_of(&text_counts(&[("raw_text", 1, 1)], false, &["ocr"]), "raw_text");
    assert_eq!(other.state(), "exact", "another source's stale index row does not change this count");
    let none = source_counts_of(&text_counts(&[], true, &[]), "raw_text");
    assert_eq!((none.hits(), none.state()), (0, "lower_bound"), "no checked hit in an incomplete read is not an absence");
}

#[test]
fn a_lower_bound_search_has_no_total_and_is_partial() {
    let page = TextHitsPage { hits: Vec::new(), next_position: None, unverified: false };
    let counts = SourceHitCounts { pages: vec![(1, 2)], exact: false };
    let response = search_text_response("raw_text".into(), &counts, page.clone(), "s".into());
    assert_eq!((response.hit_count, response.count_state.as_str()), (2, "lower_bound"));
    assert_eq!((response.page_info.total, response.page_info.partial), (None, true));
    let counts = SourceHitCounts { pages: vec![(1, 2)], exact: true };
    let response = search_text_response("raw_text".into(), &counts, page, "s".into());
    assert_eq!((response.page_info.total, response.page_info.partial, response.count_state.as_str()), (Some(2), false, "exact"));
}

#[test]
fn the_text_source_follows_the_writer_version_and_refuses_an_older_form() {
    let older = SourceRevision { stored_count: 1, revision: "1:1-1:5".into() };
    let newer = SourceRevision { stored_count: 1, revision: "1:1-1:6".into() };
    let before = text_source_fingerprint("h", "raw_text", &older);
    let after = text_source_fingerprint("h", "raw_text", &newer);
    assert_ne!(before, after, "a newer body of the same extent changes the source");
    // The source of the earlier form: the page count and the highest page id.
    let legacy = "h:raw_text:1:1";
    assert_ne!(legacy, after);
    let refused = verify_expected_source(Some(legacy), &after).err().map(|error| (error.status, error.error));
    assert_eq!(refused, Some((StatusCode::CONFLICT, "source_changed")));
    assert!(verify_expected_source(Some(&after), &after).is_ok());
}
