//! SQL builder helpers for search queries.

use common::{search_query::SearchQuery, search_result::FacetOriginalValue};

pub const SQL_FROM_CLAUSE: &'static str = "
    FROM doc_text_pages
    LEFT JOIN doc_metadata
    ON doc_text_pages.collection_dataset = doc_metadata.collection_dataset
    AND doc_text_pages.file_hash = doc_metadata.file_hash
";

pub const SQL_OPTIONS_CLAUSE: &'static str = "OPTION agent_query_timeout=60000,max_query_time=60000";


pub fn build_sql_where_clause(query: &SearchQuery) -> String {
    // automatically quote all @ symbols in the query string to avoid problems with FIELD SELECTOR manticore operator
    let query_string = query.query_string.clone().trim().replace("@", "\\@");

    let mut terms = vec![format!("
        WHERE MATCH({}, doc_text_pages)
    ", format_sql_query::QuotedData(&query_string))];

    for (field_name, values) in query.facet_filters.iter() {
        let values_str = values.iter().map(|value| {
            match value {
                FacetOriginalValue::String(s) => format_sql_query::QuotedData(s).to_string(),
                FacetOriginalValue::Int(i) => i.to_string(),
            }
        }).collect::<Vec<String>>().join(", ");
        terms.push(format!(
            "{field_name} IN ({values_str})",
        ));
    }

    terms.join("
        AND ")
}