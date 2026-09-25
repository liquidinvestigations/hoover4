//! Stage four: decide between accepted spans that cover the same bytes.
//!
//! Rules scan independently, so a date candidate and a phone candidate can both cover the same
//! digits and both pass their own validator. Emitting both puts one document in two facets on the
//! strength of one number, which is exactly the kind of noise that makes a facet untrustworthy.
//!
//! The order is: structural strength first, then length, then position. Strength before length
//! because a match that had to satisfy a checksum or a calendar is the less accidental reading even
//! when it is the shorter one; length after that because within one type the longer match is the
//! more completely parsed one. A full timestamp beats the bare date inside it.
//!
//! Overlap is decided by dropping, so this stage is where one false positive costs two entities.
//! An angle-bracketed address read as a message id outranks the address reading and is longer, so
//! the address is deleted and the fragment reports one wrong entity in place of one right one. The
//! ladder is not the thing to change when that happens, on a real `Message-ID:` line the
//! message-id reading is correct and the address reading must lose, and the two are mutually
//! exclusive claims about the same bytes. What has to change is the rule that proposed a reading it
//! could not justify.

use std::collections::BTreeMap;

use crate::model::Entity;

pub fn resolve(mut entities: Vec<Entity>) -> Vec<Entity> {
    entities.sort_by(|a, b| {
        b.entity_type
            .precedence()
            .cmp(&a.entity_type.precedence())
            .then_with(|| (b.end - b.start).cmp(&(a.end - a.start)))
            .then_with(|| a.start.cmp(&b.start))
    });

    // Kept spans never overlap one another, so the only one a new span can collide with is the
    // kept span starting nearest before the new one's end: every kept span before that one ends
    // before it starts. A scan with tens of thousands of entities stays linearithmic instead of
    // comparing each one with every span already kept.
    let mut kept: Vec<Entity> = Vec::with_capacity(entities.len());
    let mut ends_by_start: BTreeMap<usize, usize> = BTreeMap::new();
    for entity in entities {
        let overlaps = ends_by_start
            .range(..entity.end)
            .next_back()
            .is_some_and(|(_, &end)| entity.start < end);
        if !overlaps {
            ends_by_start.insert(entity.start, entity.end);
            kept.push(entity);
        }
    }

    kept.sort_by_key(|entity| (entity.start, entity.end));
    kept
}
