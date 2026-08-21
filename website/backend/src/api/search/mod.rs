//! Search API route handlers and module exports.

mod search_for_results;
pub use search_for_results::search_for_results;

mod search_for_results_hit_count;
pub use search_for_results_hit_count::search_for_results_hit_count;

mod search_facets;
pub use search_facets::fetch_db_terms_for_ints;
pub use search_facets::search_string_facet;

pub mod date_histogram;
pub use date_histogram::{HISTOGRAM_MAX_BUCKETS, histogram_edges, search_date_histogram};

mod mentioned_date_histogram;
pub use mentioned_date_histogram::search_mentioned_date_histogram;

mod entity_terms;
pub use entity_terms::{search_entity_terms, term_field_for_column};

mod explain_entity;
pub use explain_entity::explain_entity;

mod search_range_facets;
pub use search_range_facets::{
    SIZE_BUCKET_LABELS, search_numeric_facet, size_bucket_range,
};

pub mod fanout;
pub mod search_sql;
