//! Email rule: what the pattern proposes and what the validator keeps.

mod support;

use regex_entity_scanner::model::{EntityType, Value};

#[test]
fn extracts_and_lowercases_the_domain() {
    let scanner = support::scanner();
    let entities = scanner.scan("write to Anna.Popescu+news@Example.CO.UK today", 0);

    assert_eq!(entities.len(), 1);
    let entity = &entities[0];
    assert_eq!(entity.entity_type, EntityType::Email);
    assert_eq!(entity.text, "Anna.Popescu+news@Example.CO.UK");
    assert_eq!(entity.rule_id, "email.basic");

    // The local part is case-sensitive per RFC 5321; the domain is not, so only it is folded.
    match &entity.value {
        Value::Email {
            address,
            local,
            domain,
        } => {
            assert_eq!(address, "Anna.Popescu+news@example.co.uk");
            assert_eq!(local, "Anna.Popescu+news");
            assert_eq!(domain, "example.co.uk");
        }
        other => panic!("expected an email value, got {other:?}"),
    }
}

#[test]
fn offsets_are_absolute_in_the_source_document() {
    let scanner = support::scanner();
    let fragment = "contact: ops@example.org";
    let entities = scanner.scan(fragment, 4_000);

    assert_eq!(entities.len(), 1);
    assert_eq!(entities[0].start, 4_000 + 9);
    assert_eq!(entities[0].end, 4_000 + fragment.len());
}

#[test]
fn a_trailing_sentence_dot_is_not_part_of_the_address() {
    let scanner = support::scanner();
    let entities = scanner.scan("Mail ops@example.org.", 0);
    assert_eq!(entities.len(), 1);
    assert_eq!(entities[0].text, "ops@example.org");
}

/// The TLD list is what separates an address from a file name, and it is the single largest
/// precision win in this rule.
#[test]
fn rejects_things_shaped_like_addresses_that_have_no_registered_tld() {
    let scanner = support::scanner();
    for text in [
        "background: url(sprite@2x.png)",
        "see figure@1.5x.jpeg for detail",
        "the module lives at handler@v2.internal",
    ] {
        let entities = scanner.scan(text, 0);
        assert!(entities.is_empty(), "{text:?} produced {entities:?}");
    }
}

#[test]
fn rejects_local_parts_that_are_not_addressable() {
    let scanner = support::scanner();
    for text in [".leading@example.org", "double..dot@example.org"] {
        let entities = scanner.scan(text, 0);
        assert!(entities.is_empty(), "{text:?} produced {entities:?}");
    }
}

/// The first address ends in a top-level domain that does not exist, and the pattern's longest
/// match ends with it. Rejecting that candidate must not cost the real address beside it.
#[test]
fn a_rejected_address_does_not_hide_the_real_one() {
    let scanner = support::scanner();
    let entities = scanner.scan("notes@example.zzz billing@example.com", 0);

    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].text, "billing@example.com");
}

/// Looking inside a rejected candidate is a search for a shorter match, and a great many short
/// strings are registered top-level domains. The right-hand boundary guard is what stops the search
/// from landing on `.pn` inside a file name.
#[test]
fn shrinking_a_filename_does_not_uncover_a_country_domain() {
    let scanner = support::scanner();
    for text in [
        "background: url(sprite@2x.png)",
        "see figure@1.5x.jpeg for detail",
        "the module lives at handler@v2.internal",
    ] {
        let entities = scanner.scan(text, 0);
        assert!(entities.is_empty(), "{text:?} produced {entities:?}");
    }
}
