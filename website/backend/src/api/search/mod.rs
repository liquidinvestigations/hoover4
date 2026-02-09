//! Search API route handlers and module exports.

mod search_for_results;
pub use search_for_results::search_for_results;

mod search_for_results_hit_count;
pub use search_for_results_hit_count::search_for_results_hit_count;


mod search_facets;
pub use search_facets::search_string_facet;

pub mod search_sql;