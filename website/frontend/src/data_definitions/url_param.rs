//! The typed route segment. The type lives in `common::url_param`, so the backend and the
//! link parser (`common::links`) decode the same bytes that the router writes.

pub use common::url_param::*;
