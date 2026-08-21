//! A two-stage entity scanner.
//!
//! Stage one is a prefilter that deliberately over-matches: one `RegexSet` pass says which rules
//! fire anywhere in the fragment, and only those rules then scan for candidate spans. Stage two
//! validates each candidate — re-imposing the guards that a linear-time engine cannot express,
//! checking calendar and checksum validity — and normalises it to a canonical typed value. What
//! survives goes through overlap resolution and comes out as [`Entity`] values.
//!
//! The split exists because matching is the cheap half. A span that is not validated and not
//! reduced to a canonical value is index noise, so nothing reaches the output without passing
//! through both stages.

pub mod data;
pub mod explain;
pub mod model;
pub mod rules;
pub mod scan;
pub mod service;

pub use explain::Explanation;
pub use model::{Entity, EntityType, Flag, Value};
pub use rules::RULE_SET_VERSION;
pub use scan::Scanner;
