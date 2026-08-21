//! Cryptocurrency addresses: Bitcoin and Ethereum.
//!
//! Both formats are checksummed, and the two rules differ in how much of that checksum a document
//! actually gives you. A Bitcoin address always carries one — base58check's truncated double
//! SHA-256 for the legacy forms, bech32's own for native segwit — so acceptance is arithmetic. An
//! Ethereum address carries one only when it is written in mixed case: EIP-55 hides the check in
//! the capitalisation, so an address typed entirely in lower case is structurally valid and
//! **unverifiable**, and saying so is the difference between a confidence that means something and
//! one that does not.

use std::collections::BTreeMap;

use sha2::{Digest, Sha256};

use crate::model::{EntityType, Flag, Value};
use crate::rules::{Candidate, Rule, Verdict};

/// Whether the neighbouring bytes make this a token in its own right rather than a slice of a
/// longer one.
fn is_standalone(candidate: &Candidate<'_>) -> bool {
    !candidate
        .byte_before()
        .is_some_and(|b| b.is_ascii_alphanumeric())
        && !candidate
            .byte_after()
            .is_some_and(|b| b.is_ascii_alphanumeric())
}

// ---------------------------------------------------------------------------------------------
// Ethereum
// ---------------------------------------------------------------------------------------------

pub struct EthereumRule;

const ETHEREUM_PATTERN: &str = r"0x[0-9A-Fa-f]{40}";

impl Rule for EthereumRule {
    fn id(&self) -> &'static str {
        "crypto.ethereum"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::CryptoWallet
    }

    fn candidate_pattern(&self) -> &'static str {
        ETHEREUM_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let body = text.get(2..)?;
        let mixed_case = body.chars().any(|c| c.is_ascii_uppercase())
            && body.chars().any(|c| c.is_ascii_lowercase());

        let (confidence, flags, compact) = if mixed_case {
            if !eip55_agrees(body) {
                return None;
            }
            (0.99, Vec::new(), text.to_string())
        } else {
            // Nothing was verified, so nothing is claimed beyond the shape — and the address is
            // reported in the lower-case form, which is the one spelling that carries no claim.
            (
                0.85,
                vec![Flag::NoChecksum],
                format!("0x{}", body.to_ascii_lowercase()),
            )
        };

        let mut parts = BTreeMap::new();
        parts.insert("chain".to_string(), "ethereum".to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "ethereum".to_string(),
                compact,
                country: None,
                parts,
            },
            confidence,
            flags,
        })
    }
}

/// EIP-55: the capitalisation of each hex letter is the corresponding nibble of the Keccak-256
/// hash of the lower-case address, above or below eight. It is a checksum hidden in case, which is
/// why an all-lower-case address is not merely unfashionable but genuinely uncheckable.
fn eip55_agrees(body: &str) -> bool {
    use sha3::Keccak256;

    let lowered = body.to_ascii_lowercase();
    let hash = Keccak256::digest(lowered.as_bytes());

    lowered
        .bytes()
        .zip(body.bytes())
        .enumerate()
        .all(|(index, (lower, actual))| {
            if !lower.is_ascii_alphabetic() {
                return lower == actual;
            }
            let nibble = if index % 2 == 0 {
                hash[index / 2] >> 4
            } else {
                hash[index / 2] & 0x0f
            };
            if nibble >= 8 {
                actual == lower.to_ascii_uppercase()
            } else {
                actual == lower
            }
        })
}

// ---------------------------------------------------------------------------------------------
// Bitcoin
// ---------------------------------------------------------------------------------------------

pub struct BitcoinRule;

/// The legacy base58 forms, whose alphabet drops the four characters that are easy to confuse, and
/// the native segwit form, whose human-readable part is a literal marker.
const BITCOIN_PATTERN: &str = r"[13][123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]{25,34}|bc1[023456789acdefghjklmnpqrstuvwxyz]{8,87}";

/// The base58 alphabet, in value order.
const BASE58: &str = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

impl Rule for BitcoinRule {
    fn id(&self) -> &'static str {
        "crypto.bitcoin"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::CryptoWallet
    }

    fn candidate_pattern(&self) -> &'static str {
        BITCOIN_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let kind = if text.starts_with("bc1") {
            // The bech32 checksum and the segwit program length are both the crate's business;
            // it rejects a mistyped character outright.
            let (_, version, program) = bech32::segwit::decode(text).ok()?;
            match (u8::from(version), program.len()) {
                (0, 20) => "p2wpkh",
                (0, 32) => "p2wsh",
                (1, 32) => "p2tr",
                _ => return None,
            }
        } else {
            let decoded = base58_decode(text)?;
            if decoded.len() != 25 || !base58check_agrees(&decoded) {
                return None;
            }
            match decoded[0] {
                0x00 => "p2pkh",
                0x05 => "p2sh",
                // Test-network and other version bytes are a different network's address, and
                // saying "bitcoin" about one would be wrong.
                _ => return None,
            }
        };

        let mut parts = BTreeMap::new();
        parts.insert("chain".to_string(), "bitcoin".to_string());
        parts.insert("address_type".to_string(), kind.to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "bitcoin".to_string(),
                compact: text.to_string(),
                country: None,
                parts,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

/// Base58 to bytes: a base conversion, with each leading `1` restored as a leading zero byte
/// because the conversion cannot represent it.
fn base58_decode(text: &str) -> Option<Vec<u8>> {
    let mut bytes: Vec<u8> = Vec::with_capacity(32);
    for character in text.chars() {
        let mut carry = BASE58.find(character)?;
        for byte in bytes.iter_mut().rev() {
            carry += 58 * usize::from(*byte);
            *byte = (carry % 256) as u8;
            carry /= 256;
        }
        while carry > 0 {
            bytes.insert(0, (carry % 256) as u8);
            carry /= 256;
        }
    }
    let leading_zeroes = text.chars().take_while(|c| *c == '1').count();
    let mut decoded = vec![0u8; leading_zeroes];
    decoded.extend(bytes);
    Some(decoded)
}

/// The last four bytes are the first four of the double SHA-256 of everything before them.
fn base58check_agrees(decoded: &[u8]) -> bool {
    let (payload, checksum) = decoded.split_at(decoded.len() - 4);
    let digest = Sha256::digest(Sha256::digest(payload));
    digest[..4] == *checksum
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The genesis coinbase address, which is the most-published base58check string there is.
    #[test]
    fn base58check_accepts_the_genesis_address() {
        let decoded = base58_decode("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa").expect("in the alphabet");
        assert_eq!(decoded.len(), 25);
        assert_eq!(decoded[0], 0x00);
        assert!(base58check_agrees(&decoded));

        // One character changed, and the truncated double hash no longer agrees.
        let broken = base58_decode("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb").expect("in the alphabet");
        assert!(!base58check_agrees(&broken));
    }

    /// The worked example from EIP-55 itself.
    #[test]
    fn eip55_reads_the_checksum_out_of_the_capitalisation() {
        assert!(eip55_agrees("5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"));
        assert!(!eip55_agrees("5aAeb6053f3E94C9b9A09f33669435E7Ef1BeAed"));
    }
}
