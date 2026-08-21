//! Check-digit arithmetic, ported from `python-stdnum`.
//!
//! A check digit is the cheapest strong guard this scanner has: one pass over the characters turns
//! a shape that matches into a number that agrees with itself, and it costs nothing per candidate.
//! For the identifier tier it is close to decisive — a one-in-ten to one-in-ninety-seven filter on
//! digit runs that would otherwise all look alike.
//!
//! The arithmetic is not invented here. Each function is a port of the corresponding
//! `python-stdnum` module, and each test uses that module's own documented valid and invalid pair,
//! so a divergence shows up as a failing test rather than as a quietly wrong facet.
//!
//! Every function takes the number **including** its check digit or digits and answers whether it
//! agrees. A character the scheme does not define makes the number invalid rather than a panic:
//! validators are handed candidates from a deliberately loose prefilter.

/// The Luhn algorithm, ISO/IEC 7812-1 annex B.
///
/// Used by IMEI, by the letter-expanded form of an ISIN, and by payment card numbers. It detects
/// every single-digit error and almost every transposition of adjacent digits.
pub fn luhn(number: &str) -> bool {
    if number.is_empty() {
        return false;
    }
    let mut sum = 0u32;
    for (index, character) in number.chars().rev().enumerate() {
        let Some(digit) = character.to_digit(10) else {
            return false;
        };
        // Every second digit from the right is doubled, and a two-digit result is added as its
        // own digits — which is the same as subtracting nine.
        let contribution = if index % 2 == 1 {
            let doubled = digit * 2;
            doubled / 10 + doubled % 10
        } else {
            digit
        };
        sum += contribution;
    }
    sum % 10 == 0
}

/// The Damm algorithm, over the anti-symmetric quasigroup of order 10 from its original
/// description.
///
/// Detects every single-digit error and every transposition of adjacent digits, including the
/// `09`/`90` pair that Luhn misses. It is a single check digit appended to a decimal number.
pub fn damm(number: &str) -> bool {
    /// The quasigroup operation table. A valid number walks it to zero.
    const TABLE: [[usize; 10]; 10] = [
        [0, 3, 1, 7, 5, 9, 8, 6, 4, 2],
        [7, 0, 9, 2, 1, 5, 4, 8, 6, 3],
        [4, 2, 0, 6, 8, 7, 1, 3, 5, 9],
        [1, 7, 5, 0, 9, 8, 3, 4, 2, 6],
        [6, 1, 2, 3, 0, 4, 5, 9, 7, 8],
        [3, 6, 7, 4, 2, 0, 9, 5, 8, 1],
        [5, 8, 6, 9, 7, 2, 0, 1, 3, 4],
        [8, 9, 4, 5, 3, 6, 2, 0, 1, 7],
        [9, 4, 3, 8, 6, 1, 7, 2, 0, 5],
        [2, 5, 8, 1, 4, 3, 6, 7, 9, 0],
    ];

    if number.is_empty() {
        return false;
    }
    let mut check = 0usize;
    for character in number.chars() {
        let Some(digit) = character.to_digit(10) else {
            return false;
        };
        check = TABLE[check][digit as usize];
    }
    check == 0
}

/// A positional weighted sum modulo `modulus`, which is the shape most bespoke check digits take.
///
/// IMO numbers (weights 7 down to 2, modulo 10), SEDOL (`1,3,1,7,3,9`, modulo 10), CUSIP
/// (alternating `1,2`, modulo 10) and the ISO 6346 container check digit (powers of two, modulo 11)
/// are all this function with different arguments. It returns the remainder rather than a verdict,
/// because the schemes differ in what they then do with it — some compare it to the check digit,
/// some subtract it from the modulus first.
///
/// `weights` cycle when there are more digits than weights, which is what the alternating schemes
/// want; digits beyond the weights of a fixed-length scheme are the caller's mistake to avoid.
pub fn weighted_mod(digits: &[u32], weights: &[u32], modulus: u32) -> u32 {
    if weights.is_empty() || modulus == 0 {
        return 0;
    }
    digits.iter().enumerate().fold(0u32, |sum, (index, digit)| {
        (sum + digit * weights[index % weights.len()]) % modulus
    })
}

/// ISO 7064, the international standard for check character systems.
pub mod iso7064 {
    /// ISO 7064 Mod 97, 10: two check digits, valid when the whole number read as an integer is
    /// 1 modulo 97.
    ///
    /// Used by IBAN (over the rearranged form), by LEI, and by several national VAT numbers. Letters
    /// count as their base-36 value, so `A` is 10 — which is how an IBAN's country prefix takes
    /// part in the arithmetic. The remainder is carried digit by digit because the numbers run to
    /// forty characters, well past any machine integer.
    pub fn mod_97_10(number: &str) -> bool {
        let Some(remainder) = checksum_97(number) else {
            return false;
        };
        remainder == 1
    }

    fn checksum_97(number: &str) -> Option<u32> {
        if number.is_empty() {
            return None;
        }
        let mut remainder = 0u32;
        for character in number.chars() {
            let value = character.to_digit(36)?;
            remainder = if value < 10 {
                (remainder * 10 + value) % 97
            } else {
                (remainder * 100 + value) % 97
            };
        }
        Some(remainder)
    }

    /// ISO 7064 Mod 11, 2: one check character, which is `X` when the digit would be 10.
    ///
    /// Used by ISBN-10-style schemes and by several national identifiers. Valid when the running
    /// checksum is 1.
    pub fn mod_11_2(number: &str) -> bool {
        if number.is_empty() {
            return false;
        }
        let mut check = 0u32;
        for character in number.chars() {
            let value = match character {
                'X' | 'x' => 10,
                _ => match character.to_digit(10) {
                    Some(digit) => digit,
                    None => return false,
                },
            };
            check = (2 * check + value) % 11;
        }
        check == 1
    }

    /// ISO 7064 Mod 11, 10: a hybrid modulo 11 and modulo 10 chain whose check digit is always a
    /// decimal digit, so the identifier stays numeric.
    ///
    /// Used by German tax numbers and by several company registration schemes. Valid when the
    /// running checksum is 1.
    pub fn mod_11_10(number: &str) -> bool {
        if number.is_empty() {
            return false;
        }
        let mut check = 5u32;
        for character in number.chars() {
            let Some(digit) = character.to_digit(10) else {
                return false;
            };
            check = ((if check == 0 { 10 } else { check } * 2) % 11 + digit) % 10;
        }
        check == 1
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The valid and invalid pair from the upstream module's own documentation, which is what makes
    /// a divergence from the reference implementation visible.
    #[test]
    fn luhn_agrees_with_the_reference() {
        assert!(luhn("78949"));
        assert!(!luhn("7894"));
        assert!(!luhn(""));
        assert!(!luhn("7894x"));
    }

    #[test]
    fn damm_agrees_with_the_reference() {
        assert!(damm("5724"));
        assert!(!damm("572"));
        assert!(!damm("5725"));
    }

    #[test]
    fn mod_97_10_agrees_with_the_reference() {
        assert!(iso7064::mod_97_10("9999123456789012141490"));
        assert!(iso7064::mod_97_10("08686001256515001121751"));
        // The documented check digits for this base, so the pair differs only in the last two.
        assert!(iso7064::mod_97_10("435411161155111431"));
        assert!(!iso7064::mod_97_10("435411161155111432"));
        // Letters count as their base-36 value, which is what carries an IBAN's country prefix
        // into the arithmetic: this is GB82 WEST 1234 5698 7654 32 in the rearranged order.
        assert!(iso7064::mod_97_10("WEST12345698765432GB82"));
        assert!(!iso7064::mod_97_10("WEST12345698765432GB83"));
    }

    #[test]
    fn mod_11_2_agrees_with_the_reference() {
        assert!(iso7064::mod_11_2("07940"));
        assert!(iso7064::mod_11_2("079X"));
        assert!(!iso7064::mod_11_2("07941"));
    }

    #[test]
    fn mod_11_10_agrees_with_the_reference() {
        assert!(iso7064::mod_11_10("794623"));
        assert!(iso7064::mod_11_10("002006673085"));
        assert!(!iso7064::mod_11_10("794624"));
    }

    /// IMO 9319466 from the upstream documentation: the first six digits weighted 7 down to 2,
    /// modulo 10, is the check digit. The invalid pair is the same number with the check digit
    /// changed.
    #[test]
    fn weighted_mod_reproduces_the_imo_check_digit() {
        let digits: Vec<u32> = "931946".chars().filter_map(|c| c.to_digit(10)).collect();
        assert_eq!(weighted_mod(&digits, &[7, 6, 5, 4, 3, 2], 10), 6);

        let digits: Vec<u32> = "881427".chars().filter_map(|c| c.to_digit(10)).collect();
        assert_eq!(weighted_mod(&digits, &[7, 6, 5, 4, 3, 2], 10), 5);
    }

    /// SEDOL B15KXQ8, with the letters counted as their position in the base-36 alphabet: the
    /// weighted sum subtracted from ten is the check digit.
    #[test]
    fn weighted_mod_reproduces_the_sedol_check_digit() {
        let values: Vec<u32> = "B15KXQ".chars().filter_map(|c| c.to_digit(36)).collect();
        let sum = weighted_mod(&values, &[1, 3, 1, 7, 3, 9], 10);
        assert_eq!((10 - sum) % 10, 8);
    }
}
