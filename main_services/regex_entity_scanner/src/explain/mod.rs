//! Explainer cards: what a match means, for the person looking at it.
//!
//! A client holds an entity exactly as `/scan` returned it. When a reader clicks the highlight, the
//! client posts that entity back, unchanged, and gets a card: a title, a subtitle, and a longer
//! body, plus the facts and reference links behind them.
//!
//! Two properties shape this module.
//!
//! **The entity is the whole input.** Nothing is looked up in a session, a cache or the original
//! document. An entity is self-describing, so a card can be produced from one that was extracted
//! months ago by a client that has kept it. Only `rule_id` is required; every other field is used
//! if present and ignored if not, because an entity from an older rule set must still explain
//! itself rather than fail.
//!
//! **The knowledge is static and lives in [`catalog`].** What a rule matches, which standard
//! defines it, which authority administers it, what the validator checked and (equally)
//! what it did not check, are properties of the rule, written down once next to it. The per-rule
//! shapers in [`cards`] add what only this particular match can say: its country, its precision,
//! the authority register entry for its own top-level domain.

pub mod cards;
pub mod catalog;

use serde::{Deserialize, Serialize};

use crate::data::VendoredData;
use crate::model::{EntityType, Flag};

/// An entity as the client received it. Unknown fields are accepted and ignored, which is what
/// makes "post it back unchanged" a contract that survives a rule-set upgrade.
#[derive(Debug, Clone, Deserialize)]
pub struct ExplainRequest {
    pub rule_id: String,
    #[serde(default)]
    pub text: Option<String>,
    /// The canonical value, kept as raw JSON. The shapers read the fields they know; a value shape
    /// from a version this build has never seen degrades to a thinner card instead of an error.
    #[serde(default)]
    pub value: serde_json::Value,
    #[serde(default)]
    pub confidence: Option<f32>,
    #[serde(default)]
    pub flags: Vec<Flag>,
}

impl ExplainRequest {
    /// A string field of the entity's value, if the value is an object and the field is a string.
    pub fn value_str(&self, field: &str) -> Option<&str> {
        self.value.get(field)?.as_str()
    }

    pub fn value_bool(&self, field: &str) -> Option<bool> {
        self.value.get(field)?.as_bool()
    }

    /// One entry of an identifier value's `parts` map, the bank code inside an IBAN, the issuing
    /// unit inside an LEI. Nested one level, so it needs its own accessor.
    pub fn value_part(&self, name: &str) -> Option<&str> {
        self.value.get("parts")?.get(name)?.as_str()
    }
}

/// The card. `title`, `subtitle` and `body` are the three text fields a UI renders; `facts` and
/// `references` are the same material in structured form, for a UI that would rather draw chips and
/// links than parse prose.
#[derive(Debug, Clone, Serialize)]
pub struct Explanation {
    pub rule_id: String,
    pub entity_type: EntityType,
    /// Human-readable name for what was matched: "ISO 8601 timestamp", not `date.iso8601`.
    pub title: String,
    /// One line of what this particular match is: country, authority, precision, register.
    pub subtitle: String,
    /// The long text, in Markdown, with links inline.
    pub body: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub facts: Vec<Fact>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub references: Vec<Link>,
}

/// One labelled piece of sub-metadata: `Country`, `United Kingdom`.
#[derive(Debug, Clone, Serialize)]
pub struct Fact {
    pub label: String,
    pub value: String,
}

impl Fact {
    pub fn new(label: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            label: label.into(),
            value: value.into(),
        }
    }
}

/// A reference the reader can follow: the standard, the register, the authority.
#[derive(Debug, Clone, Serialize)]
pub struct Link {
    pub title: String,
    pub url: String,
    /// Why this link is worth following, in a few words.
    pub note: String,
}

impl Link {
    pub fn new(title: impl Into<String>, url: impl Into<String>, note: impl Into<String>) -> Self {
        Self {
            title: title.into(),
            url: url.into(),
            note: note.into(),
        }
    }
}

/// Builds the card, or `None` when no rule of that identifier is documented, which a UI treats as
/// "show no card" rather than as an error.
pub fn explain(request: &ExplainRequest, data: &VendoredData) -> Option<Explanation> {
    let doc = catalog::lookup(&request.rule_id)?;
    Some(cards::build(doc, request, data))
}
