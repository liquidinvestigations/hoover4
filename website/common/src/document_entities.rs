//! Shared per-document entity models (for document viewer).

use serde::{Deserialize, Serialize};

/// What kind of thing a value is, across both extractors.
///
/// The first five are a model's guess at a span of prose; the rest are a rule's
/// arithmetic on a run of characters. They are listed in one enum because the panel
/// shows them in one place, and they are kept apart as variants because the confidence
/// behind them is not comparable: a name is a judgement, an IBAN either has a valid
/// check digit or it does not.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Hash, PartialOrd, Ord)]
pub enum DocumentEntityType {
    Per,
    Org,
    Loc,
    Misc,
    Email,
    Phone,
    BankAccount,
    CompanyId,
    Money,
    CryptoWallet,
    /// A date the document's TEXT names, which is not a date the document HAS. A memo
    /// written this year that discusses 1936 mentions 1936 and was created now.
    MentionedDate,
    Unknown,
}

impl DocumentEntityType {
    /// The scanner's own type name for a rule-found value, or `Unknown`.
    ///
    /// The scanner emits more types than the viewer has sections for (coordinates,
    /// vessels, publications), and those arrive as `Unknown` rather than being dropped,
    /// so a rule added upstream shows up as an unlabelled row instead of vanishing.
    pub fn from_scanner_type(name: &str) -> Self {
        match name.trim().to_lowercase().as_str() {
            "email" => Self::Email,
            "phone" => Self::Phone,
            "bank_account" => Self::BankAccount,
            "company_id" => Self::CompanyId,
            "money" => Self::Money,
            "crypto_wallet" => Self::CryptoWallet,
            "date" => Self::MentionedDate,
            _ => Self::Unknown,
        }
    }

    /// Whether the value came from a rule with a validator rather than from a model.
    ///
    /// The two halves of the panel behave differently: a rule-found value has an
    /// explainer card and a surface form that is frequently not the value, and a
    /// model-found one has neither.
    pub fn is_rule_found(&self) -> bool {
        matches!(
            self,
            Self::Email
                | Self::Phone
                | Self::BankAccount
                | Self::CompanyId
                | Self::Money
                | Self::CryptoWallet
                | Self::MentionedDate
        )
    }

    /// The section heading this type is listed under.
    pub fn label(&self) -> &'static str {
        match self {
            Self::Per => "Person",
            Self::Org => "Organization",
            Self::Loc => "Location",
            Self::Misc => "Misc",
            Self::Email => "Email",
            Self::Phone => "Phone",
            Self::BankAccount => "Bank account",
            Self::CompanyId => "Company ID",
            Self::Money => "Money",
            Self::CryptoWallet => "Crypto wallet",
            Self::MentionedDate => "Mentioned Date",
            Self::Unknown => "Other",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Hash, PartialOrd, Ord)]
pub struct DocumentEntityItem {
    pub entity_type: DocumentEntityType,
    pub value: String,
    pub hit_count: u64,
    /// Which NER models found this value, sorted and deduplicated.
    ///
    /// The pipeline runs more than one NER provider and more than one text variant per
    /// document, so the same name is found several times. The rows are aggregated by
    /// value rather than listed, because a panel that shows "Voronkov" four times reads as
    /// a bug, but *which* provider found it is real provenance and the reason this is a
    /// list rather than a count.
    #[serde(default)]
    pub providers: Vec<String>,
    /// The rule that accepted this value. Empty for a model-found entity.
    ///
    /// It is half of the key the explainer card is fetched with; the other half is
    /// [`Self::value_json`].
    #[serde(default)]
    pub rule_id: String,
    /// The canonical value object, exactly as the scan stage stored it.
    ///
    /// Passed back to the explainer untouched. Re-deriving it from `value` would lose
    /// everything the validator worked out (the country inside an IBAN, the currency
    /// and minor units inside an amount), and would silently produce a thinner card.
    #[serde(default)]
    pub value_json: String,
    /// The text as the document wrote it, which a normalised value frequently is not.
    ///
    /// `+442075623419` never appears verbatim in a document that wrote
    /// `+44 (0)20 7562 3419`, so this is what a find-in-page click must search for.
    /// Empty when the value is its own surface form.
    #[serde(default)]
    pub surface_text: String,
    /// The magnitude bucket a money value is filed under (`USD 10k-100k`). Empty for
    /// everything else. Canonical ASCII: the en-dash is a render-time concern, because a
    /// label spelling change must never be a reindex.
    #[serde(default)]
    pub bucket: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocumentEntitiesResponse {
    pub items: Vec<DocumentEntityItem>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_scanner_types_the_viewer_has_sections_for_are_mapped() {
        for (name, expected) in [
            ("email", DocumentEntityType::Email),
            ("phone", DocumentEntityType::Phone),
            ("bank_account", DocumentEntityType::BankAccount),
            ("company_id", DocumentEntityType::CompanyId),
            ("money", DocumentEntityType::Money),
            ("crypto_wallet", DocumentEntityType::CryptoWallet),
            ("date", DocumentEntityType::MentionedDate),
        ] {
            assert_eq!(DocumentEntityType::from_scanner_type(name), expected);
        }
    }

    /// The scanner finds vessels, coordinates and publications too. None of those has a
    /// section, and they must arrive as an unlabelled row rather than disappear, a rule
    /// added upstream should show up as something to name, not as nothing.
    #[test]
    fn a_scanner_type_with_no_section_is_unknown_rather_than_dropped() {
        assert_eq!(
            DocumentEntityType::from_scanner_type("vessel"),
            DocumentEntityType::Unknown
        );
    }

    #[test]
    fn only_rule_found_types_claim_a_validator() {
        assert!(DocumentEntityType::BankAccount.is_rule_found());
        assert!(DocumentEntityType::MentionedDate.is_rule_found());
        assert!(!DocumentEntityType::Per.is_rule_found());
        assert!(!DocumentEntityType::Unknown.is_rule_found());
    }
}
