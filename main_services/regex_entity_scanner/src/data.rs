//! Loading of the vendored reference data the validators consult.
//!
//! Everything here is read once at startup and then shared immutably across scanning threads.
//! `RES_VENDORED_DIR` points at the vendored tree, the bind mount in development, a directory
//! baked into the release image otherwise.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::Deserialize;

/// What the IBAN registry says about one country's account numbers.
///
/// ISO 7064 mod-97-10 accepts roughly one malformed candidate in ninety-seven on its own. The
/// length and the positional structure are what close that gap, and they are per country, which
/// is why this is vendored data rather than a constant.
#[derive(Debug, Deserialize)]
pub struct IbanCountry {
    /// The country as the registry names it, which is not always the CLDR spelling.
    pub country: String,
    /// Total length of the compact IBAN, country code and check digits included.
    pub length: usize,
    /// The BBAN structure as a run of `<length>!<class>` groups, `n` digits, `a` letters,
    /// `c` alphanumerics.
    pub structure: String,
    /// Byte range of the bank identifier within the compact IBAN, where the registry's structure
    /// determines one. Branch identifier positions are not in this source and are not guessed.
    #[serde(default)]
    pub bank: Option<[usize; 2]>,
}

/// One ISO 4217 code: how many minor units it divides into, and what it is called.
///
/// The exponent is the whole reason this is data rather than a constant. A sum of money is stored
/// as a scaled integer, and the scale is three for the Bahraini dinar, zero for the Japanese yen
/// and two for most of the rest, so `1.5` is 1500, 1 or 150 depending only on the code beside it.
#[derive(Debug, Deserialize)]
pub struct Currency {
    /// ISO 4217 minor units: the number of decimal places the amount is scaled by.
    pub exponent: u8,
    /// The English name, for the explainer card.
    pub name: String,
}

/// The IANA list and whatever else the validators and the explainer need to distinguish a real
/// match from a plausible-looking one, and to say what it belongs to.
#[derive(Debug, Default)]
pub struct VendoredData {
    /// Top-level domains, uppercased exactly as IANA publishes them.
    tlds: HashSet<String>,
    /// ISO 3166-1 alpha-2 code to English territory name, from CLDR.
    territories: HashMap<String, String>,
    /// ISO 3166-1 alpha-2 code to the IBAN registry's entry for that country.
    iban_registry: HashMap<String, IbanCountry>,
    /// ITU Maritime Identification Digits to the ISO 3166-1 alpha-2 code of the flag state.
    maritime_ids: HashMap<String, String>,
    /// ISO 4217 code to its minor units and name, restricted to the codes in current use.
    currencies: HashMap<String, Currency>,
    /// Currency symbol to the codes it can mean, most widely used first. A one-entry list is an
    /// unambiguous symbol; a longer one is what the ambiguous-currency flag reports.
    currency_symbols: HashMap<String, Vec<String>>,
}

/// The smallest number of entries each table has to hold to be the file it was transformed from.
/// The numbers are an order of magnitude below what the current sources carry, because their job is
/// to catch a file that is empty, half-written or a placeholder, not to pin an upstream's size.
const MINIMUM_ENTRIES: &[(&str, usize)] = &[
    ("TLD list", 1_000),
    ("territory names", 200),
    ("IBAN registry", 70),
    ("maritime identification digits", 250),
    ("currency table", 120),
    ("currency symbol table", 40),
];

impl VendoredData {
    /// Reads the vendored tree at `RES_VENDORED_DIR`, defaulting to `./vendored`.
    pub fn load_from_env() -> Result<Self> {
        let root = std::env::var("RES_VENDORED_DIR").unwrap_or_else(|_| "vendored".to_string());
        Self::load(Path::new(&root))
    }

    pub fn load(root: &Path) -> Result<Self> {
        let tld_file: PathBuf = root.join("data/iana/tlds-alpha-by-domain.txt");
        let raw = std::fs::read_to_string(&tld_file)
            .with_context(|| format!("reading the vendored TLD list at {}", tld_file.display()))?;

        let tlds: HashSet<String> = raw
            .lines()
            .map(str::trim)
            .filter(|line| !line.is_empty() && !line.starts_with('#'))
            .map(str::to_uppercase)
            .collect();

        let territory_file: PathBuf = root.join("data/cldr/territories-en.json");
        let raw = std::fs::read_to_string(&territory_file).with_context(|| {
            format!(
                "reading the vendored territory names at {}",
                territory_file.display()
            )
        })?;
        let territories: HashMap<String, String> =
            serde_json::from_str(&raw).context("parsing the vendored territory names")?;

        let iban_file: PathBuf = root.join("data/iban/registry.json");
        let raw = std::fs::read_to_string(&iban_file).with_context(|| {
            format!(
                "reading the vendored IBAN registry at {}",
                iban_file.display()
            )
        })?;
        let iban_registry: HashMap<String, IbanCountry> =
            serde_json::from_str(&raw).context("parsing the vendored IBAN registry")?;

        let mid_file: PathBuf = root.join("data/itu/mids.json");
        let raw = std::fs::read_to_string(&mid_file).with_context(|| {
            format!(
                "reading the vendored maritime identification digits at {}",
                mid_file.display()
            )
        })?;
        // The source is keyed by MID and carries alpha-2, alpha-3, a subdivision and a name; only
        // the alpha-2 is used, and the rest is left in the file so the provenance stays legible.
        let raw_mids: HashMap<String, Vec<String>> = serde_json::from_str(&raw)
            .context("parsing the vendored maritime identification digits")?;
        let maritime_ids: HashMap<String, String> = raw_mids
            .into_iter()
            .filter_map(|(mid, fields)| {
                let alpha2 = fields.into_iter().next()?;
                (!alpha2.is_empty()).then_some((mid, alpha2))
            })
            .collect();

        let currency_file: PathBuf = root.join("data/cldr/iso4217.json");
        let raw = std::fs::read_to_string(&currency_file).with_context(|| {
            format!(
                "reading the vendored currency table at {}",
                currency_file.display()
            )
        })?;
        let currencies: HashMap<String, Currency> =
            serde_json::from_str(&raw).context("parsing the vendored currency table")?;

        let symbol_file: PathBuf = root.join("data/cldr/currency-symbols.json");
        let raw = std::fs::read_to_string(&symbol_file).with_context(|| {
            format!(
                "reading the vendored currency symbols at {}",
                symbol_file.display()
            )
        })?;
        let currency_symbols: HashMap<String, Vec<String>> =
            serde_json::from_str(&raw).context("parsing the vendored currency symbols")?;

        let data = Self {
            tlds,
            territories,
            iban_registry,
            maritime_ids,
            currencies,
            currency_symbols,
        };

        let incomplete = data.incomplete_tables();
        anyhow::ensure!(
            incomplete.is_empty(),
            "the vendored {} under {} {} far fewer entries than the rules that read {} need, \
             which means the file is empty or truncated",
            incomplete.join(", the vendored "),
            root.display(),
            if incomplete.len() == 1 {
                "holds"
            } else {
                "hold"
            },
            if incomplete.len() == 1 { "it" } else { "them" },
        );
        Ok(data)
    }

    /// The tables that hold too little to be the file they were transformed from. A rule whose
    /// table is empty does not fail: it matches nothing, for every request, for as long as the
    /// process runs, which is a whole facet switched off behind a green health check. That is why the
    /// counts are checked at startup and reported at `/health` rather than trusted.
    pub fn incomplete_tables(&self) -> Vec<&'static str> {
        MINIMUM_ENTRIES
            .iter()
            .filter(|(name, minimum)| self.table_len(name) < *minimum)
            .map(|(name, _)| *name)
            .collect()
    }

    fn table_len(&self, name: &str) -> usize {
        match name {
            "TLD list" => self.tlds.len(),
            "territory names" => self.territories.len(),
            "IBAN registry" => self.iban_registry.len(),
            "maritime identification digits" => self.maritime_ids.len(),
            "currency table" => self.currencies.len(),
            "currency symbol table" => self.currency_symbols.len(),
            _ => 0,
        }
    }

    /// Whether `label` is a registered top-level domain. This one membership test removes the bulk
    /// of what an email pattern otherwise matches: file names, version strings, `foo@2x.png`.
    pub fn is_known_tld(&self, label: &str) -> bool {
        self.tlds.contains(&label.to_uppercase())
    }

    pub fn tld_count(&self) -> usize {
        self.tlds.len()
    }

    /// The English name of an ISO 3166-1 alpha-2 territory. A card that can say "United Kingdom"
    /// should not say "GB".
    pub fn territory_name(&self, alpha2: &str) -> Option<&str> {
        self.territories
            .get(&alpha2.to_uppercase())
            .map(String::as_str)
    }

    /// Whether `alpha2` names an actual country rather than one of CLDR's groupings or
    /// placeholders. Identifier schemes that encode a country encode an ISO 3166-1 country, so
    /// `EU`, `ZZ` and their kind have to be excluded or every eight-letter word ending in `ZZPP`
    /// becomes a bank code.
    pub fn is_country_code(&self, alpha2: &str) -> bool {
        /// CLDR publishes these alongside the countries: political and economic groupings, the
        /// unknown-region placeholder, and the two pseudo-locales used for translation testing.
        const NOT_COUNTRIES: [&str; 7] = ["EU", "EZ", "QO", "UN", "XA", "XB", "ZZ"];

        let alpha2 = alpha2.to_uppercase();
        !NOT_COUNTRIES.contains(&alpha2.as_str()) && self.territories.contains_key(&alpha2)
    }

    /// The flag state an ITU Maritime Identification Digit triple belongs to, as an ISO 3166-1
    /// alpha-2 code. An MMSI carries no check digit, so this membership test is most of what
    /// separates a real one from any nine-digit run.
    pub fn maritime_id_country(&self, mid: &str) -> Option<&str> {
        self.maritime_ids.get(mid).map(String::as_str)
    }

    /// The IBAN registry entry for a country code, or `None` for a country that issues no IBANs,
    /// which is itself a rejection, and a decisive one.
    /// The minor units and name for an ISO 4217 code in current use. A code this returns `None`
    /// for is either historical or not a currency, and both are reasons to reject the candidate.
    pub fn currency(&self, code: &str) -> Option<&Currency> {
        self.currencies.get(code)
    }

    /// The codes a symbol can mean, most widely used first. `€` yields one code; `$` yields
    /// twenty-nine, and nothing in the text decides between them.
    pub fn currency_symbol(&self, symbol: &str) -> Option<&[String]> {
        self.currency_symbols.get(symbol).map(Vec::as_slice)
    }

    pub fn iban_country(&self, alpha2: &str) -> Option<&IbanCountry> {
        self.iban_registry.get(&alpha2.to_uppercase())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The empty value is what a rule set backed by a missing or truncated file looks like from
    /// the inside: every validator still compiles, and every membership test answers no.
    #[test]
    fn every_table_is_reported_when_nothing_loaded() {
        let names: Vec<&str> = MINIMUM_ENTRIES.iter().map(|(name, _)| *name).collect();
        assert_eq!(VendoredData::default().incomplete_tables(), names);
    }

    #[test]
    fn the_vendored_tree_loads_complete() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("vendored");
        let data = VendoredData::load(&root).expect("loading the vendored data");
        assert!(data.incomplete_tables().is_empty());
    }
}
