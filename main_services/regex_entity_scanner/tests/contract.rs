//! Structural properties of the wire contract, independent of any one rule.

use std::collections::{BTreeMap, HashSet};

use regex_entity_scanner::explain::catalog;
use regex_entity_scanner::model::{DatePrecision, Entity, EntityType, Flag, Value};

fn entity(entity_type: EntityType, value: Value) -> Entity {
    Entity {
        entity_type,
        start: 12,
        end: 20,
        text: "surface".to_string(),
        value,
        confidence: 0.99,
        rule_id: "rule.under.test".to_string(),
        flags: vec![Flag::NoChecksum],
    }
}

/// One instance of every value kind, so the tag carries enough to reconstruct the variant.
fn one_of_every_kind() -> Vec<Entity> {
    vec![
        entity(
            EntityType::Date,
            Value::Date {
                rfc3339: "2021-03-04T09:12:00+02:00".to_string(),
                precision: DatePrecision::Second,
                tz_known: true,
            },
        ),
        entity(
            EntityType::Email,
            Value::Email {
                address: "ops@example.org".to_string(),
                local: "ops".to_string(),
                domain: "example.org".to_string(),
            },
        ),
        entity(
            EntityType::Phone,
            Value::Phone {
                e164: "+40213101010".to_string(),
                country: "RO".to_string(),
                national: "213101010".to_string(),
                number_type: "fixed_line".to_string(),
            },
        ),
        entity(
            EntityType::Money,
            Value::Money {
                currency: "EUR".to_string(),
                amount_minor: "120000".to_string(),
                exponent: 2,
            },
        ),
        entity(
            EntityType::BankAccount,
            Value::Identifier {
                scheme: "iban".to_string(),
                compact: "RO17RZBR0000060000000000".to_string(),
                country: Some("RO".to_string()),
                parts: BTreeMap::from([
                    ("bank_code".to_string(), "RZBR".to_string()),
                    ("check_digits".to_string(), "17".to_string()),
                ]),
            },
        ),
        // The same shape with neither optional field, which is the form most identifier rules
        // without a country or a documented part layout produce.
        entity(
            EntityType::Security,
            Value::Identifier {
                scheme: "sedol".to_string(),
                compact: "B15KXQ8".to_string(),
                country: None,
                parts: BTreeMap::new(),
            },
        ),
        entity(
            EntityType::Network,
            Value::NetworkAddress {
                family: "ipv4".to_string(),
                address: "198.51.100.7".to_string(),
                prefix_length: Some(24),
            },
        ),
        entity(
            EntityType::Coordinates,
            Value::GeoPoint {
                latitude: 44.4268,
                longitude: 26.1025,
                datum: "wgs84".to_string(),
            },
        ),
    ]
}

/// The reason the value is tagged at all: an entity a client stored is an entity the service can
/// read back. An untagged union deserialises into whichever variant happens to fit first, which is
/// not the same value and not a contract.
#[test]
fn an_entity_round_trips_through_json() {
    for original in one_of_every_kind() {
        let json = serde_json::to_string(&original).expect("an entity serialises");
        let parsed: Entity = serde_json::from_str(&json)
            .unwrap_or_else(|error| panic!("{json} does not deserialise: {error}"));
        assert_eq!(parsed, original);
    }
}

/// The tag is the shape of the fields, not the facet: several entity types share one shape, and a
/// consumer dispatches on `kind` without knowing the rule set.
#[test]
fn the_value_is_tagged_on_kind() {
    let json = serde_json::to_value(one_of_every_kind()[4].clone()).expect("an entity serialises");
    assert_eq!(json["type"], "bank_account");
    assert_eq!(json["value"]["kind"], "identifier");
    assert_eq!(json["value"]["country"], "RO");
    assert_eq!(json["value"]["parts"]["bank_code"], "RZBR");

    // An empty part map and an absent country are omitted rather than serialised as null or {}.
    let bare = serde_json::to_value(one_of_every_kind()[5].clone()).expect("an entity serialises");
    assert!(bare["value"].get("parts").is_none());
    assert!(bare["value"].get("country").is_none());
}

/// Candidate patterns are re-run over a slice of the fragment when the scan loop looks inside a
/// rejected candidate, so a pattern that depends on where its haystack ends would mean something
/// different on the retry. The prefilter refuses to compile one; this pins that the compiled rule
/// set stays clean rather than relying on the error being seen at startup.
#[test]
fn no_candidate_pattern_depends_on_its_haystack_boundaries() {
    for rule in regex_entity_scanner::rules::all() {
        let pattern = rule.candidate_pattern();
        for offender in ["^", "$", "\\b"] {
            assert!(
                !pattern.contains(offender),
                "the candidate pattern for {} contains {offender}",
                rule.id()
            );
        }
    }
}

/// Every entity type in the ladder, so a new one cannot be added without deciding what evidence it
/// rests on.
const EVERY_TYPE: &[EntityType] = &[
    EntityType::Date,
    EntityType::Email,
    EntityType::Phone,
    EntityType::Money,
    EntityType::BankAccount,
    EntityType::CompanyId,
    EntityType::Security,
    EntityType::Vessel,
    EntityType::CargoContainer,
    EntityType::Device,
    EntityType::Network,
    EntityType::Publication,
    EntityType::Vulnerability,
    EntityType::CryptoWallet,
    EntityType::Coordinates,
    EntityType::NationalId,
    EntityType::MessageId,
];

/// Precedence is a ladder of bands, not a per-type ranking: types that had the same evidence
/// available to them share a number and let length and position break the tie. So the interesting
/// property is that the bands are distinct — a band that collided with its neighbour would silently
/// stop deciding anything.
#[test]
fn the_precedence_ladder_has_one_value_per_band() {
    let bands: HashSet<u8> = EVERY_TYPE.iter().map(|t| t.precedence()).collect();
    assert_eq!(bands.len(), 7, "{bands:?}");

    // The identifier tier outranks dates, which is the overlap the ladder exists to settle.
    assert!(EntityType::BankAccount.precedence() > EntityType::Date.precedence());
    assert!(EntityType::Date.precedence() > EntityType::Coordinates.precedence());
}

/// A rule with no FollowTheMoney mapping produces entities a consumer cannot put anywhere, so the
/// mapping is a requirement rather than documentation.
#[test]
fn every_documented_rule_maps_into_followthemoney() {
    for doc in catalog::all() {
        assert!(
            !doc.ftm.schema.is_empty() && !doc.ftm.property.is_empty(),
            "{} has no FollowTheMoney mapping",
            doc.rule_id
        );
        assert!(
            !doc.ftm.note.is_empty(),
            "{} maps to {}.{} without saying why",
            doc.rule_id,
            doc.ftm.schema,
            doc.ftm.property
        );
    }
}
