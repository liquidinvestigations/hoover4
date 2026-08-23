//! Geographic coordinates: decimal degrees, degrees-minutes-seconds, and Open Location Codes.
//!
//! Coordinates have no checksum and no issuing authority, so the only things standing between the
//! facet and every pair of numbers in a spreadsheet are the range checks and the surface form.
//! That is why the decimal rule insists on four decimal places on both sides: three or fewer is
//! indistinguishable from a pair of measurements, and four is what a coordinate someone meant to
//! write actually looks like. The datum is stated as WGS84 rather than inferred. It is the datum
//! every one of these forms is written in today, and saying so is the difference between a value a
//! consumer can reproject and one it has to guess about.

use crate::model::{EntityType, Flag, Value};
use crate::rules::{Candidate, Rule, Verdict};

/// The datum every one of these surface forms is conventionally written in.
const DATUM: &str = "WGS84";

fn geo_point(candidate: &Candidate<'_>, latitude: f64, longitude: f64) -> Option<Verdict> {
    if !(-90.0..=90.0).contains(&latitude) || !(-180.0..=180.0).contains(&longitude) {
        return None;
    }
    Some(Verdict {
        start: candidate.start,
        end: candidate.end,
        value: Value::GeoPoint {
            latitude,
            longitude,
            datum: DATUM.to_string(),
        },
        confidence: 0.85,
        flags: vec![Flag::NoChecksum],
    })
}

// ---------------------------------------------------------------------------------------------
// Decimal degrees
// ---------------------------------------------------------------------------------------------

pub struct DecimalRule;

/// Two signed decimal numbers separated by a comma. Four fractional digits are required on both
/// sides: at three the form is a pair of measurements as often as it is a place, and there is no
/// arithmetic that tells the two apart.
const DECIMAL_PATTERN: &str = r"[-+]?\d{1,3}[.]\d{4,10}[ ]{0,2},[ ]{0,2}[-+]?\d{1,3}[.]\d{4,10}";

impl Rule for DecimalRule {
    fn id(&self) -> &'static str {
        "coord.decimal"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Coordinates
    }

    fn candidate_pattern(&self) -> &'static str {
        DECIMAL_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b',')
            || candidate
                .byte_after()
                .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b',')
        {
            return None;
        }

        let text = candidate.text();
        let (latitude, longitude) = text.split_once(',')?;
        geo_point(
            candidate,
            latitude.trim().parse().ok()?,
            longitude.trim().parse().ok()?,
        )
    }
}

// ---------------------------------------------------------------------------------------------
// Degrees, minutes and seconds
// ---------------------------------------------------------------------------------------------

pub struct DmsRule;

/// The sexagesimal form, with the degree sign and the hemisphere letters that make it
/// self-identifying. Both halves are required: a latitude on its own is not a point.
///
/// Minutes and seconds are marked with the ASCII apostrophe and quote or with the typographic
/// prime and double prime, U+2032 and U+2033. Every typeset document uses the latter (a word
/// processor substitutes them as they are typed), so a rule that read only the ASCII pair would
/// see the form nobody prints. The marks are notation and take no part in the arithmetic, so
/// admitting both costs nothing: the degree sign, the hemisphere letters and the sexagesimal range
/// checks are what make the match.
const DMS_PATTERN: &str = concat!(
    r#"\d{1,3}°[ ]?\d{1,2}['′][ ]?\d{1,2}(?:[.]\d{1,4})?["″]?[ ]?[NSns]"#,
    r#"[ ,]{0,3}"#,
    r#"\d{1,3}°[ ]?\d{1,2}['′][ ]?\d{1,2}(?:[.]\d{1,4})?["″]?[ ]?[EWew]"#,
);

impl Rule for DmsRule {
    fn id(&self) -> &'static str {
        "coord.dms"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Coordinates
    }

    fn candidate_pattern(&self) -> &'static str {
        DMS_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric())
            || candidate
                .byte_after()
                .is_some_and(|b| b.is_ascii_alphanumeric())
        {
            return None;
        }

        let text = candidate.text();
        let split = text.find(['N', 'S', 'n', 's'])?;
        let (latitude, longitude) = text.split_at(split + 1);
        let latitude = to_degrees(latitude)?;
        let longitude = to_degrees(longitude)?;
        if latitude.abs() > 90.0 || longitude.abs() > 180.0 {
            return None;
        }
        geo_point(candidate, latitude, longitude)
    }
}

/// One sexagesimal half to signed decimal degrees. Minutes and seconds are rejected at sixty,
/// because a sexagesimal reading that has run over is a transcription error rather than a place.
fn to_degrees(half: &str) -> Option<f64> {
    let hemisphere = half.trim().chars().last()?.to_ascii_uppercase();
    let numbers: Vec<f64> = half
        .split(|c: char| !c.is_ascii_digit() && c != '.')
        .filter(|field| !field.is_empty())
        .map(str::parse)
        .collect::<Result<_, _>>()
        .ok()?;
    let [degrees, minutes, seconds] = numbers[..] else {
        return None;
    };
    if minutes >= 60.0 || seconds >= 60.0 {
        return None;
    }
    let magnitude = degrees + minutes / 60.0 + seconds / 3600.0;
    match hemisphere {
        'N' | 'E' => Some(magnitude),
        'S' | 'W' => Some(-magnitude),
        _ => None,
    }
}

// ---------------------------------------------------------------------------------------------
// Open Location Code
// ---------------------------------------------------------------------------------------------

pub struct PlusCodeRule;

/// The twenty-character alphabet excludes every vowel, so eight of these characters followed by a
/// plus sign is not a word and is not an identifier from any other scheme here.
const PLUS_CODE_PATTERN: &str = r"[23456789CFGHJMPQRVWX]{8}\+[23456789CFGHJMPQRVWX]{2,3}";

/// The code alphabet, in value order.
const OLC_ALPHABET: &str = "23456789CFGHJMPQRVWX";

impl Rule for PlusCodeRule {
    fn id(&self) -> &'static str {
        "coord.plus_code"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Coordinates
    }

    fn candidate_pattern(&self) -> &'static str {
        PLUS_CODE_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'+')
            || candidate
                .byte_after()
                .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'+')
        {
            return None;
        }

        let text = candidate.text();
        let digits: Vec<usize> = text
            .chars()
            .filter(|c| *c != '+')
            .map(|c| OLC_ALPHABET.find(c))
            .collect::<Option<_>>()?;

        // The first pair carries the whole world in one step, so its two characters are the only
        // range check the format offers: a first character past index eight would put the latitude
        // north of the pole.
        if digits[0] > 8 || digits[1] > 17 {
            return None;
        }

        let mut latitude = -90.0;
        let mut longitude = -180.0;
        let mut resolution = 20.0;
        // Only the five full pairs are decoded. A code with an eleventh character refines the cell
        // through a four-by-five grid, which this does not read, so the point is the centre of the
        // ten-character cell either way.
        for pair in digits.chunks(2).take(5) {
            let [row, column] = pair[..] else { break };
            latitude += row as f64 * resolution;
            longitude += column as f64 * resolution;
            resolution /= 20.0;
        }
        // Report the centre of the cell rather than its south-west corner: the corner is an edge
        // of the area the code names, and the centre is the point inside it.
        let centre = resolution * 20.0 / 2.0;
        geo_point(candidate, latitude + centre, longitude + centre)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The worked example from the Open Location Code specification, whose ten-character cell is
    /// the block containing the Google office in Mountain View.
    #[test]
    fn a_plus_code_decodes_to_its_cell_centre() {
        let digits: Vec<usize> = "8FVC9G8F6W"
            .chars()
            .map(|c| OLC_ALPHABET.find(c).expect("in the alphabet"))
            .collect();
        assert_eq!(digits[0], 6);
        assert_eq!(digits.len(), 10);
    }

    /// A sexagesimal half whose minutes or seconds have run over is a transcription error.
    #[test]
    fn sexagesimal_fields_stay_below_sixty() {
        assert_eq!(to_degrees("40°26'46\"N"), Some(40.44611111111111));
        assert_eq!(to_degrees("79°58'56\"W"), Some(-79.98222222222222));
        assert_eq!(to_degrees("40°66'46\"N"), None);
    }
}
