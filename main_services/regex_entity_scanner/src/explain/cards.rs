//! Per-rule shapers: what only this particular match can say.
//!
//! The catalogue supplies everything true of the rule. A shaper adds what is true of the match in
//! front of the reader (the country behind its top-level domain, the weekday its date fell on,
//! the register entry for its own identifier), and that is the half that makes a card worth
//! opening.
//!
//! A rule with no shaper still gets a card from the catalogue alone. That fallback is what keeps
//! documenting a new rule cheap: write the entry, ship a usable card, refine it later.

use crate::data::VendoredData;
use crate::explain::catalog::{self, RuleDoc};
use crate::explain::{ExplainRequest, Explanation, Fact, Link};

pub fn build(doc: &'static RuleDoc, request: &ExplainRequest, data: &VendoredData) -> Explanation {
    let mut card = Explanation {
        rule_id: doc.rule_id.to_string(),
        entity_type: doc.entity_type,
        title: doc.title.to_string(),
        subtitle: String::new(),
        body: String::new(),
        facts: Vec::new(),
        references: doc
            .references
            .iter()
            .map(|reference| Link::new(reference.title, reference.url, reference.note))
            .collect(),
    };

    // The paragraph about this specific match, which is also where a shaper adjusts the title,
    // subtitle, facts and links.
    let specifics = match doc.rule_id {
        "date.iso8601" => date_iso(&mut card, request),
        "email.basic" => email(&mut card, request, data),
        "company.lei" => company_lei(&mut card, request),
        "company.vat_eu" | "company.vat_non_eu" => company_vat(&mut card, request, data),
        "bank.iban" => bank_iban(&mut card, request, data),
        "bank.bic" => bank_bic(&mut card, request, data),
        "security.isin" => security_isin(&mut card, request, data),
        "vessel.mmsi" => vessel_mmsi(&mut card, request, data),
        "phone.international" => phone(&mut card, request, data),
        "money.iso_code" | "money.symbol" => money(&mut card, request, data),
        _ => None,
    };

    if let Some(confidence) = request.confidence {
        card.facts
            .push(Fact::new("Confidence", format!("{confidence:.2}")));
    }
    card.body = body(doc, request, specifics);
    card
}

/// Assembles the long text. The order is fixed across rules so that a reader who has opened one
/// card knows where to look in the next: what this is, what this one says, what was verified, what
/// verification does not cover, who defines it, where to read more.
fn body(doc: &'static RuleDoc, request: &ExplainRequest, specifics: Option<String>) -> String {
    let mut blocks: Vec<String> = vec![doc.matches.to_string()];

    if let Some(text) = &request.text {
        blocks.push(format!("**Matched text:** `{text}`"));
    }
    if let Some(specifics) = specifics {
        blocks.push(specifics);
    }

    if !doc.checks.is_empty() {
        blocks.push(format!(
            "**What was checked**\n{}",
            bullets(doc.checks.iter().copied())
        ));
    }
    if !doc.not_checked.is_empty() {
        blocks.push(format!(
            "**What this does not prove**\n{}",
            bullets(doc.not_checked.iter().copied())
        ));
    }
    if !doc.standards.is_empty() {
        blocks.push(format!(
            "**Defined by**\n{}",
            bullets(doc.standards.iter().copied())
        ));
    }
    if !doc.authorities.is_empty() {
        blocks.push(format!(
            "**Authorities**\n{}",
            bullets(doc.authorities.iter().map(|authority| format!(
                "[{}]({}) — {}",
                authority.name, authority.url, authority.role
            )))
        ));
    }
    if !doc.references.is_empty() {
        blocks.push(format!(
            "**References**\n{}",
            bullets(doc.references.iter().map(|reference| format!(
                "[{}]({}) — {}",
                reference.title, reference.url, reference.note
            )))
        ));
    }
    // The same sentence on every card that carries a number, because a single threshold across
    // thirty-one rules only works if the number means one thing, and the reader can only believe
    // that if the explanation does not vary either.
    if request.confidence.is_some() {
        blocks.push(format!(
            "**About confidence**\n{}",
            catalog::CONFIDENCE_NOTE
        ));
    }

    blocks.join("\n\n")
}

fn bullets(items: impl Iterator<Item = impl std::fmt::Display>) -> String {
    items
        .map(|item| format!("- {item}"))
        .collect::<Vec<_>>()
        .join("\n")
}

/// ISO 8601: precision decides what to call it, and the calendar gives the reader the one thing the
/// digits do not, which day of the week it was.
fn date_iso(card: &mut Explanation, request: &ExplainRequest) -> Option<String> {
    let rfc3339 = request.value_str("rfc3339")?;
    let precision = request.value_str("precision").unwrap_or("day");
    let tz_known = request.value_bool("tz_known").unwrap_or(false);

    card.title = match precision {
        "day" => "ISO 8601 date",
        _ => "ISO 8601 timestamp",
    }
    .to_string();

    let date: jiff::civil::Date = rfc3339.get(..10)?.parse().ok()?;
    let weekday = weekday_name(date.weekday());
    let readable = format!(
        "{weekday}, {} {} {}",
        date.day(),
        month_name(date.month()),
        date.year()
    );

    let zone = match (tz_known, offset_of(rfc3339)) {
        (true, Some("Z")) => "UTC".to_string(),
        (true, Some(offset)) => format!("UTC{offset}"),
        _ => "no time zone stated".to_string(),
    };

    card.subtitle = format!("{readable} · {precision} precision · {zone}");
    card.facts.push(Fact::new("Canonical value", rfc3339));
    card.facts.push(Fact::new("Day of the week", weekday));
    card.facts.push(Fact::new("Precision", precision));
    card.facts.push(Fact::new("Time zone", zone.as_str()));
    let week = date.iso_week_date();
    card.facts.push(Fact::new(
        "ISO week",
        format!("{}-W{:02}", week.year(), week.week()),
    ));

    let mut specifics = format!("This is {readable}.");
    if !tz_known {
        specifics.push_str(
            " No offset was written, so the instant it refers to depends on where the document was \
             produced — the date is certain, the moment is not.",
        );
    }
    if request.text.as_deref().is_some_and(|text| text != rfc3339) {
        specifics.push_str(&format!(
            " It was written differently from the canonical form above; both spellings normalise to \
             `{rfc3339}`, which is what makes a date range query find them together."
        ));
    }
    Some(specifics)
}

/// LEI: the checksum says the code is well-formed and nothing about which company it names. GLEIF
/// publishes that answer for free, so the card links straight to the entry for this exact code
/// rather than leaving the reader to find the register.
fn company_lei(card: &mut Explanation, request: &ExplainRequest) -> Option<String> {
    let compact = request.value_str("compact")?;
    let lou = request.value_part("lou").unwrap_or_default();

    card.subtitle = format!("{compact} · issued by LOU {lou}");
    card.facts.push(Fact::new("Identifier", compact));
    if !lou.is_empty() {
        card.facts.push(Fact::new("Issuing unit", lou));
    }

    card.references.insert(
        0,
        Link::new(
            format!("GLEIF record for {compact}"),
            format!("https://search.gleif.org/#/record/{compact}"),
            "the register entry: legal name, jurisdiction, address and registration status",
        ),
    );

    Some(format!(
        "The check digits agree, so `{compact}` is a well-formed Legal Entity Identifier. Whether \
         it was ever issued, and to whom, is a question for the register — the link above goes to \
         the entry for this exact code."
    ))
}

/// IBAN: the first two characters are the country whose registry decided the account number's
/// length and layout, which is both what the validator checked against and the one fact a reader
/// wants first.
fn bank_iban(
    card: &mut Explanation,
    request: &ExplainRequest,
    data: &VendoredData,
) -> Option<String> {
    let compact = request.value_str("compact")?;
    let (alpha2, country) = encoded_country(request, data)?;

    card.subtitle = format!("{compact} · {country}");
    card.facts.push(Fact::new("Identifier", compact));
    card.facts.push(Fact::new("Country", country.as_str()));
    if let Some(bank) = request.value_part("bank_code") {
        card.facts.push(Fact::new("Bank identifier", bank));
    }
    if let Some(bban) = request.value_part("bban") {
        card.facts.push(Fact::new("Domestic account number", bban));
    }

    Some(format!(
        "`{alpha2}` in the first two positions is {country}, and it is that country's entry in the \
         IBAN registry that fixes how long the rest of the number is and which positions hold \
         letters. The check digits agree with the account number, so the two were written down \
         together correctly. The country is where the account is held, which is not necessarily \
         where its holder lives."
    ))
}

/// VAT: the prefix is the tax administration that issued the number, and it is the only part of
/// the code that is a country. Greece writes `EL` where ISO 3166-1 writes `GR`, so the prefix as
/// written and the country in the value are not always the same two letters.
fn company_vat(
    card: &mut Explanation,
    request: &ExplainRequest,
    data: &VendoredData,
) -> Option<String> {
    let compact = request.value_str("compact")?;
    let (alpha2, country) = encoded_country(request, data)?;
    let prefix = request.value_part("prefix").unwrap_or_default();

    card.subtitle = format!("{compact} · {country}");
    card.facts.push(Fact::new("Identifier", compact));
    card.facts.push(Fact::new("Country", country.as_str()));
    if !prefix.is_empty() {
        card.facts.push(Fact::new("Tax prefix", prefix));
    }
    if let Some(number) = request.value_part("number") {
        card.facts.push(Fact::new("National number", number));
    }

    let spelling = if prefix.is_empty() || prefix == alpha2 {
        String::new()
    } else {
        format!(
            " The prefix is written `{prefix}`, which is what that administration uses; the value \
             carries `{alpha2}` so the number joins with every other identifier that encodes a \
             country."
        )
    };
    Some(format!(
        "The number is registered with the tax administration of {country}, whose own check-digit \
         rule the digits satisfy.{spelling} A valid number is one that was formed correctly — \
         whether it is currently registered, and to whom, is a question for that administration's \
         own register."
    ))
}

/// BIC: positions five and six are the country, and they are the only part of the code checked
/// against a list. The institution and branch letters are whatever SWIFT allocated.
fn bank_bic(
    card: &mut Explanation,
    request: &ExplainRequest,
    data: &VendoredData,
) -> Option<String> {
    let compact = request.value_str("compact")?;
    let (alpha2, country) = encoded_country(request, data)?;

    card.subtitle = format!("{compact} · {country}");
    card.facts.push(Fact::new("Identifier", compact));
    card.facts.push(Fact::new("Country", country.as_str()));
    if let Some(institution) = request.value_part("institution") {
        card.facts.push(Fact::new("Institution code", institution));
    }
    if let Some(location) = request.value_part("location") {
        card.facts.push(Fact::new("Location code", location));
    }
    match request.value_part("branch") {
        Some(branch) => card.facts.push(Fact::new("Branch code", branch)),
        None => card
            .facts
            .push(Fact::new("Branch code", "none — the head office")),
    }

    Some(format!(
        "`{alpha2}` in positions five and six is {country}, the country of the office this code \
         addresses. A BIC carries no check digit, so the country and the shape are all the \
         arithmetic there is: whether SWIFT ever allocated this exact code is a question for their \
         directory."
    ))
}

/// ISIN: the prefix is the country of the national numbering agency that issued the number, which
/// is where the security was issued and not where its issuer is domiciled.
fn security_isin(
    card: &mut Explanation,
    request: &ExplainRequest,
    data: &VendoredData,
) -> Option<String> {
    let compact = request.value_str("compact")?;
    card.facts.push(Fact::new("Identifier", compact));
    if let Some(national) = request.value_part("national_number") {
        card.facts.push(Fact::new("National number", national));
    }

    let Some((alpha2, country)) = encoded_country(request, data) else {
        // The substitute-agency prefixes (XS for Eurobonds and the rest) name no place, so the
        // card says what the prefix is instead of naming a country that does not exist.
        let prefix = compact.get(..2).unwrap_or_default();
        card.subtitle = format!("{compact} · issued by a substitute numbering agency");
        return Some(format!(
            "`{prefix}` is not a country: it belongs to the substitute agencies that number \
             securities with no single national home, such as Eurobonds cleared internationally. \
             The check digit agrees, so the code is well-formed."
        ));
    };

    card.subtitle = format!("{compact} · {country}");
    card.facts.push(Fact::new("Country", country.as_str()));

    Some(format!(
        "`{alpha2}` in the first two positions is {country}, whose national numbering agency \
         allocated the nine characters that follow. That says where the security was numbered, not \
         where its issuer is domiciled or where it trades."
    ))
}

/// MMSI: the first three digits are the ITU Maritime Identification Digits, which name the
/// administration that assigned the number. The flag the station sails under.
fn vessel_mmsi(
    card: &mut Explanation,
    request: &ExplainRequest,
    data: &VendoredData,
) -> Option<String> {
    let compact = request.value_str("compact")?;
    let (_, country) = encoded_country(request, data)?;
    let mid = request.value_part("mid").unwrap_or_default();

    card.subtitle = format!("{compact} · {country}");
    card.facts.push(Fact::new("Identifier", compact));
    card.facts.push(Fact::new("Flag state", country.as_str()));
    if !mid.is_empty() {
        card.facts
            .push(Fact::new("Maritime identification digits", mid));
    }

    Some(format!(
        "The leading `{mid}` is an ITU Maritime Identification Digit triple allocated to \
         {country}, so that is the administration the station is registered with. An MMSI carries \
         no check digit and is reassigned when a vessel changes flag or owner, so it identifies a \
         radio station at a point in time rather than a hull for life."
    ))
}

/// Phone: the interesting part is the country the calling code names and the line type the
/// numbering plan gives the number, neither of which is legible in the digits themselves.
fn phone(card: &mut Explanation, request: &ExplainRequest, data: &VendoredData) -> Option<String> {
    let e164 = request.value_str("e164")?;
    let national = request.value_str("national").unwrap_or_default();
    let region = request.value_str("country").unwrap_or_default();
    let number_type = request.value_str("number_type").unwrap_or_default();
    let readable_type = number_type.replace('_', " ");

    let country = data.territory_name(region).map(ToString::to_string);
    card.subtitle = match &country {
        Some(name) => format!("{e164} · {name}"),
        None => format!("{e164} · global service"),
    };

    card.facts.push(Fact::new("E.164", e164));
    if !national.is_empty() {
        card.facts.push(Fact::new("National number", national));
    }
    match &country {
        Some(name) => card.facts.push(Fact::new("Country", name.as_str())),
        None => card
            .facts
            .push(Fact::new("Country", "none — a global service")),
    }
    if !readable_type.is_empty() {
        card.facts
            .push(Fact::new("Line type", readable_type.as_str()));
    }

    let where_it_is = match &country {
        Some(name) => format!("The calling code belongs to {name}"),
        None => "The calling code belongs to no country: +800 freephone, +870 satellite and the \
                 other global services are allocated by the ITU directly"
            .to_string(),
    };
    Some(format!(
        "{where_it_is}, and `{e164}` is the number in E.164 form — the one spelling that is the \
         same wherever it is written down, which is what makes it usable as an index key. The \
         numbering plan classifies it as a {readable_type} number. What was checked is the number, \
         not the subscriber: nothing here says the line is in service or whose it is."
    ))
}

/// Money: the stored value is a scaled integer, which is the right thing to index and the wrong
/// thing to show. The card puts the digits back where a reader expects them and names the currency
/// the code stands for.
fn money(card: &mut Explanation, request: &ExplainRequest, data: &VendoredData) -> Option<String> {
    let code = request.value_str("currency")?;
    let minor = request.value_str("amount_minor")?;
    let exponent = usize::try_from(request.value.get("exponent")?.as_u64()?).ok()?;

    let name = data.currency(code).map(|currency| currency.name.as_str());
    let readable = with_decimal_point(minor, exponent);

    card.subtitle = match name {
        Some(name) => format!("{readable} {code} · {name}"),
        None => format!("{readable} {code}"),
    };
    card.facts.push(Fact::new("Amount", readable.clone()));
    card.facts.push(Fact::new("Currency", code));
    if let Some(name) = name {
        card.facts.push(Fact::new("Currency name", name));
    }
    card.facts.push(Fact::new("Minor units", minor));
    card.facts
        .push(Fact::new("Minor unit digits", exponent.to_string()));

    Some(format!(
        "The value is stored as `{minor}`, an integer number of minor units, together with the \
         code `{code}` and the {exponent} decimal places that code divides into — never as a \
         decimal fraction, because binary floating point cannot hold one exactly and a sum of \
         money that has lost a cent has lost it silently. Written out, that is {readable} {code}."
    ))
}

/// The minor-unit integer with its decimal point put back, for display only.
fn with_decimal_point(minor: &str, exponent: usize) -> String {
    if exponent == 0 {
        return minor.to_string();
    }
    let padded = format!("{minor:0>width$}", width = exponent + 1);
    let split = padded.len() - exponent;
    format!("{}.{}", &padded[..split], &padded[split..])
}

/// The country an identifier carries in its own characters, resolved to a name a reader knows.
/// Every such rule already puts the alpha-2 in the value, so the shaper is a lookup rather than a
/// second parse of the text.
fn encoded_country(request: &ExplainRequest, data: &VendoredData) -> Option<(String, String)> {
    let alpha2 = request.value_str("country")?;
    let name = data.territory_name(alpha2)?;
    Some((alpha2.to_string(), name.to_string()))
}

/// Email: the domain is the interesting part, because it is the only part anything was verified
/// against. A country-code top-level domain also names a country, which is usually the single most
/// useful thing on the card.
fn email(card: &mut Explanation, request: &ExplainRequest, data: &VendoredData) -> Option<String> {
    let address = request.value_str("address")?;
    let local = request.value_str("local").unwrap_or_default();
    let domain = request.value_str("domain")?;
    let tld = domain.rsplit('.').next()?;

    let kind = tld_kind(tld, data);
    card.subtitle = match &kind.country {
        Some(country) => format!("{domain} · {country}"),
        None => format!("{domain} · {}", kind.description),
    };

    card.facts.push(Fact::new("Address", address));
    if !local.is_empty() {
        card.facts.push(Fact::new("Local part", local));
    }
    card.facts.push(Fact::new("Domain", domain));
    card.facts
        .push(Fact::new("Top-level domain", format!(".{tld}")));
    card.facts
        .push(Fact::new("Domain type", kind.description.as_str()));
    if let Some(country) = &kind.country {
        card.facts.push(Fact::new("Country", country.as_str()));
    }

    // The register entry for this specific domain: who sponsors it and under what policy.
    card.references.insert(
        0,
        Link::new(
            format!("IANA register entry for .{tld}"),
            format!("https://www.iana.org/domains/root/db/{tld}.html"),
            "who sponsors this top-level domain and under what policy",
        ),
    );

    let mut specifics = if local.is_empty() {
        format!("The address names a mailbox at `{domain}`.")
    } else {
        format!(
            "The local part `{local}` identifies a mailbox at `{domain}`. The domain is compared \
             case-insensitively and is stored lowercased; the local part is case-sensitive and is \
             left exactly as written."
        )
    };
    match &kind.country {
        Some(country) => specifics.push_str(&format!(
            " `.{tld}` is the country-code top-level domain for {country}, which says where the \
             domain is registered — not necessarily where its holder is."
        )),
        None => specifics.push_str(&format!(" `.{tld}` is a {}.", kind.description)),
    }
    Some(specifics)
}

struct TldKind {
    description: String,
    country: Option<String>,
}

/// A two-letter top-level domain is a country code, with the handful of historical exceptions that
/// do not match their ISO 3166 code.
fn tld_kind(tld: &str, data: &VendoredData) -> TldKind {
    let lower = tld.to_lowercase();

    if lower.starts_with("xn--") {
        return TldKind {
            description: "internationalised top-level domain".to_string(),
            country: None,
        };
    }

    if lower.len() == 2
        && lower
            .chars()
            .all(|character| character.is_ascii_alphabetic())
    {
        // `.uk` predates ISO 3166 assigning GB, and was never renamed.
        let alpha2 = match lower.as_str() {
            "uk" => "GB",
            other => other,
        };
        let country = data.territory_name(alpha2).map(str::to_string);
        return TldKind {
            description: "country-code top-level domain".to_string(),
            country,
        };
    }

    TldKind {
        description: "generic top-level domain".to_string(),
        country: None,
    }
}

/// The offset as written at the end of an RFC 3339 timestamp, if there is one.
fn offset_of(rfc3339: &str) -> Option<&str> {
    if rfc3339.ends_with('Z') {
        return Some("Z");
    }
    let time = rfc3339.split_once('T')?.1;
    let index = time.rfind(['+', '-'])?;
    Some(&time[index..])
}

fn weekday_name(weekday: jiff::civil::Weekday) -> &'static str {
    use jiff::civil::Weekday::*;
    match weekday {
        Monday => "Monday",
        Tuesday => "Tuesday",
        Wednesday => "Wednesday",
        Thursday => "Thursday",
        Friday => "Friday",
        Saturday => "Saturday",
        Sunday => "Sunday",
    }
}

fn month_name(month: i8) -> &'static str {
    const MONTHS: [&str; 12] = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ];
    MONTHS
        .get((month - 1).clamp(0, 11) as usize)
        .copied()
        .unwrap_or("")
}
