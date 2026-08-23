//! What we know about each rule, written down once.
//!
//! This is static because it is knowledge about the rule, not about any particular match: the
//! standard that defines the format, the authority that administers it, what the validator verifies
//! and what it deliberately does not. It belongs next to the rule for the same reason a doc comment
//! does. It goes stale the moment it lives anywhere else.
//!
//! Every rule gets an entry. A rule with an entry and no shaper in [`super::cards`] still produces
//! a usable card from this alone, so the catalogue is the requirement and the shaper is the polish.
//!
//! `not_checked` deserves as much care as `checks`. A reader deciding whether to trust a match
//! needs to know that a validated address has never been delivered to, and that a valid check digit
//! says a number is well-formed and nothing whatever about whether it was ever issued.

use serde::Serialize;

use crate::model::EntityType;

#[derive(Debug, Serialize)]
pub struct RuleDoc {
    pub rule_id: &'static str,
    pub entity_type: EntityType,
    /// Human-readable name for the rule itself. A shaper may make it more specific for a given
    /// match, such as "ISO 8601 timestamp" rather than "ISO 8601 date and time".
    pub title: &'static str,
    /// One or two sentences: what shapes this rule matches, and why it is worth having.
    pub matches: &'static str,
    /// The standards the format is defined by, spelled the way a reader would search for them.
    pub standards: &'static [&'static str],
    /// What the validator verifies before a candidate is accepted.
    pub checks: &'static [&'static str],
    /// What acceptance does *not* prove.
    pub not_checked: &'static [&'static str],
    pub authorities: &'static [Authority],
    pub references: &'static [Reference],
    /// Where this extraction lands in FollowTheMoney, which is the schema an investigative
    /// consumer already has. Every rule carries one; the test suite fails otherwise.
    pub ftm: FtmMapping,
}

/// The FollowTheMoney schema and property an extraction feeds.
///
/// Where FollowTheMoney defines a property we use its exact name, and where the property sits on an
/// abstract parent (`amount` and `currency` on `Value`, `idNumber` and `leiCode` on `LegalEntity`
///), the mapping names the parent, because that is where FollowTheMoney defines it and every
/// concrete schema a consumer builds inherits it.
#[derive(Debug, Serialize)]
pub struct FtmMapping {
    /// The schema, e.g. `BankAccount`.
    pub schema: &'static str,
    /// The property on it, e.g. `iban`. **Prefixed `res:` where FollowTheMoney has no property for
    /// this and we are extending its schema locally**, an extension that is written down is a
    /// mapping a consumer can implement, and one that is not is a surprise.
    pub property: &'static str,
    /// Why this is the right property, or why FollowTheMoney has none and an extension was needed.
    pub note: &'static str,
}

#[derive(Debug, Serialize)]
pub struct Authority {
    pub name: &'static str,
    /// What this body actually does for this identifier: publishes the standard, runs the register,
    /// allocates the ranges.
    pub role: &'static str,
    pub url: &'static str,
}

#[derive(Debug, Serialize)]
pub struct Reference {
    pub title: &'static str,
    pub url: &'static str,
    pub note: &'static str,
}

/// What the confidence number means, said the same way everywhere it appears.
///
/// One string, one place, no per-rule variation: a client that offers a single threshold control
/// across every rule is only honest if the number means one thing across every rule, and a reader
/// can only believe that if the explanation beside it does not change either. It is appended to
/// every card that carries a confidence and served once at the top of `GET /rules`.
pub const CONFIDENCE_NOTE: &str = "Confidence says how likely this span is to be the thing the \
                                   rule claims, given what the validator was able to check. It is \
                                   not a probability that the identifier was ever issued, that the \
                                   address receives mail, or that the value is true, only that \
                                   the text was read correctly.";

pub fn lookup(rule_id: &str) -> Option<&'static RuleDoc> {
    RULE_DOCS.iter().find(|doc| doc.rule_id == rule_id)
}

pub fn all() -> &'static [RuleDoc] {
    RULE_DOCS
}

static RULE_DOCS: &[RuleDoc] = &[
    RuleDoc {
        rule_id: "date.iso8601",
        entity_type: EntityType::Date,
        title: "ISO 8601 date and time",
        matches: "A date written in the international machine-readable order (year, month, day, \
                  largest unit first), optionally followed by a time and a UTC offset. This is the \
                  form used by logs, exports, mail headers and databases, and it is unambiguous: \
                  unlike 03/04/2021, it cannot be read two ways.",
        standards: &[
            "ISO 8601: Date and time representations for information interchange",
            "RFC 3339, Date and Time on the Internet: Timestamps, the internet profile of ISO 8601",
        ],
        checks: &[
            "the date exists in the proleptic Gregorian calendar, so 30 February and 31 April are \
             rejected and leap years are respected",
            "the clock is a real time of day, so hour 24 and minute 61 are rejected",
            "the year falls inside a plausibility window, which is what keeps version strings and \
             identifier fragments out of the date facet",
            "nothing that could have continued the timestamp runs into the match (a digit or a \
             letter on either side, or a field separator with a digit behind it), so neither a \
             date embedded in a longer number nor a slice of a longer timestamp is reported",
            "a day carved out of a timestamp whose clock is a real time of day is refused, because \
             the day alone would be reported without the instant it was written with; where the \
             clock is not a real time of day the day is a salvage and is kept",
        ],
        not_checked: &[
            "whether the date is correct, only that it is a date that exists",
            "which time zone an offset belongs to: +02:00 is an offset from UTC, and many zones \
             share it at different times of year",
        ],
        authorities: &[
            Authority {
                name: "International Organization for Standardization",
                role: "publishes ISO 8601",
                url: "https://www.iso.org/iso-8601-date-and-time-format.html",
            },
            Authority {
                name: "Internet Engineering Task Force",
                role: "publishes RFC 3339, the profile used on the internet",
                url: "https://www.ietf.org/",
            },
        ],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:dateMentioned",
            note: "FollowTheMoney has Document.date for the date a document carries as its own, \
                   and no property for a date mentioned in its text, so the mention is a local \
                   extension alongside the other Analyzable mention properties.",
        },
        references: &[
            Reference {
                title: "RFC 3339",
                url: "https://www.rfc-editor.org/rfc/rfc3339",
                note: "the timestamp grammar this value is normalised to",
            },
            Reference {
                title: "ISO 8601 at ISO",
                url: "https://www.iso.org/iso-8601-date-and-time-format.html",
                note: "the standard itself",
            },
            Reference {
                title: "IANA time zone database",
                url: "https://www.iana.org/time-zones",
                note: "how offsets map to named zones, and why one offset is not one zone",
            },
        ],
    },
    RuleDoc {
        rule_id: "email.basic",
        entity_type: EntityType::Email,
        title: "Email address",
        matches: "An address in the ordinary local-part@domain form that people actually write. \
                  Full RFC 5322 syntax (quoted local parts, comments, folded whitespace) is \
                  deliberately not the target: it accepts a great deal nobody has ever typed, and \
                  on real documents the precision comes from checking the domain instead.",
        standards: &[
            "RFC 5321: Simple Mail Transfer Protocol, which sets the length limits",
            "RFC 5322: Internet Message Format, which defines the address grammar",
        ],
        checks: &[
            "the top-level domain is on IANA's list of delegated domains, which is what separates \
             an address from a file name such as sprite@2x.png",
            "the local part is addressable unquoted, with no leading, trailing or doubled dot",
            "the local part and the domain are inside the RFC 5321 length limits of 64 and 255 \
             characters",
            "nothing addressable runs into the match from either side, so an address is not cut \
             out of a longer token",
        ],
        not_checked: &[
            "whether the domain exists, resolves, or accepts mail. No lookup of any kind is made",
            "whether the mailbox exists or the address was ever in use",
            "whether the address belongs to the person the surrounding text is about",
            "a domain with no dot in it: the pattern requires at least two labels, so test@io is \
             not matched. message.rfc5322 does admit a single-label right-hand side, because RFC \
             5322 §3.6.4 says an id-right may be a bare dot-atom-text; the two rules disagree \
             about this on purpose and this is the one that asks for more",
            "the local-part characters RFC 5322 admits that this pattern's class does not: ! # $ \
             & ' * / = ? ^ ` { | } ~. An address using one is not merely skipped: the match \
             begins after the offending character, so the bounce address \
             bounces+866407-eeb4-penultim_o=yahoo.com@delivery.customeriomail.com is reported as \
             yahoo.com@delivery.customeriomail.com, which is a wrong value rather than a miss",
        ],
        authorities: &[Authority {
            name: "Internet Assigned Numbers Authority",
            role: "delegates top-level domains and publishes the authoritative list",
            url: "https://www.iana.org/domains/root/db",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "emailMentioned",
            note: "The property FollowTheMoney defines for an address found in a document's text, \
                   as opposed to LegalEntity.email, which asserts that the address belongs to the \
                   entity, which extraction cannot establish.",
        },
        references: &[
            Reference {
                title: "IANA Root Zone Database",
                url: "https://www.iana.org/domains/root/db",
                note: "every delegated top-level domain and who sponsors it",
            },
            Reference {
                title: "RFC 5321 §4.5.3.1",
                url: "https://www.rfc-editor.org/rfc/rfc5321#section-4.5.3.1",
                note: "the local-part and domain length limits applied here",
            },
            Reference {
                title: "RFC 5321 §2.4",
                url: "https://www.rfc-editor.org/rfc/rfc5321#section-2.4",
                note: "why the domain may be lowercased and the local part may not",
            },
        ],
    },
    RuleDoc {
        rule_id: "date.rfc2822",
        entity_type: EntityType::Date,
        title: "Mail header date",
        matches: "The date line of an email or news message, such as Tue, 04 Mar 2021 09:12:00 +0200. \
                  Written by mail software rather than by people, so it is consistently spelled, \
                  and it carries the day of the week alongside the date.",
        standards: &[
            "RFC 5322 §3.3: Internet Message Format, the date and time specification",
            "RFC 2822 §3.3: the previous revision, whose obsolete zone abbreviations are still \
             emitted",
        ],
        checks: &[
            "the day of the week agrees with the calendar date, which a mangled or fabricated \
             header rarely does",
            "the date exists in the proleptic Gregorian calendar, and the clock is a real time of \
             day",
            "the year falls inside a plausibility window",
            "the zone is a numeric offset no further than eighteen hours from UTC, or one of the \
             North American abbreviations the obsolete grammar allows",
            "nothing alphanumeric runs into the match from either side",
        ],
        not_checked: &[
            "whether the message exists, was sent, or was sent when it says",
            "which named time zone the offset belongs to. Many zones share an offset at different \
             times of year",
        ],
        authorities: &[Authority {
            name: "Internet Engineering Task Force",
            role: "publishes the Internet Message Format specification",
            url: "https://www.ietf.org/",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:dateMentioned",
            note: "FollowTheMoney has Document.date for the date a document carries as its own, \
                   and no property for a date mentioned in its text, so the mention is a local \
                   extension alongside the other Analyzable mention properties.",
        },
        references: &[
            Reference {
                title: "RFC 5322 §3.3",
                url: "https://www.rfc-editor.org/rfc/rfc5322#section-3.3",
                note: "the grammar this rule matches",
            },
            Reference {
                title: "RFC 5322 §4.3",
                url: "https://www.rfc-editor.org/rfc/rfc5322#section-4.3",
                note: "the obsolete zone abbreviations and what they mean",
            },
        ],
    },
    RuleDoc {
        rule_id: "date.clf",
        entity_type: EntityType::Date,
        title: "Web server log timestamp",
        matches: "The bracketed timestamp of the Common Log Format, such as \
                  [04/Mar/2021:09:12:00 +0200], emitted by Apache, nginx and everything that \
                  imitates them. The brackets and the colon between date and clock make it \
                  self-identifying, which is why it needs \
                  no cue word.",
        standards: &[
            "NCSA Common Log Format, as implemented by the Apache HTTP Server mod_log_config \
             %t directive",
        ],
        checks: &[
            "the surrounding brackets are present, which is what distinguishes the format from a \
             slashed date somebody wrote by hand",
            "the date exists in the proleptic Gregorian calendar, and the clock is a real time of \
             day",
            "the year falls inside a plausibility window",
            "the zone is a numeric offset no further than eighteen hours from UTC",
        ],
        not_checked: &[
            "whether the request being logged happened, or happened then",
            "which named time zone the offset belongs to",
        ],
        authorities: &[Authority {
            name: "The Apache Software Foundation",
            role: "documents the log format the rest of the ecosystem copies",
            url: "https://httpd.apache.org/docs/current/mod/mod_log_config.html",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:dateMentioned",
            note: "FollowTheMoney has Document.date for the date a document carries as its own, \
                   and no property for a date mentioned in its text, so the mention is a local \
                   extension alongside the other Analyzable mention properties.",
        },
        references: &[Reference {
            title: "Apache mod_log_config",
            url: "https://httpd.apache.org/docs/current/mod/mod_log_config.html",
            note: "the %t directive that produces this timestamp",
        }],
    },
    RuleDoc {
        rule_id: "date.iso_week",
        entity_type: EntityType::Date,
        title: "ISO week date",
        matches: "A day named by its ISO week and weekday, such as 2021-W09-4, or 2021W094 in the \
                  basic spelling. Common in manufacturing, logistics and payroll data, where the week is \
                  the planning unit.",
        standards: &["ISO 8601 §4.1.4: week date representations"],
        checks: &[
            "the week exists in that ISO year, so week 53 is accepted only in the years that have \
             one",
            "the weekday is 1 to 7 counted from Monday, as ISO numbers them",
            "the year falls inside a plausibility window",
            "nothing alphanumeric runs into the match from either side, which is what keeps the \
             shape out of serial numbers",
        ],
        not_checked: &[
            "the time of day, which the format does not carry",
            "that the ISO year is the calendar year. The first days of January can belong to the \
             previous ISO year, and the value is the calendar date it resolves to",
        ],
        authorities: &[Authority {
            name: "International Organization for Standardization",
            role: "publishes ISO 8601",
            url: "https://www.iso.org/iso-8601-date-and-time-format.html",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:dateMentioned",
            note: "FollowTheMoney has Document.date for the date a document carries as its own, \
                   and no property for a date mentioned in its text, so the mention is a local \
                   extension alongside the other Analyzable mention properties.",
        },
        references: &[Reference {
            title: "ISO 8601 at ISO",
            url: "https://www.iso.org/iso-8601-date-and-time-format.html",
            note: "the standard that defines the week numbering",
        }],
    },
    RuleDoc {
        rule_id: "bank.iban",
        entity_type: EntityType::BankAccount,
        title: "International Bank Account Number",
        matches: "An account number in the international form: a country code, two check digits \
                  and the national account number, written compactly or in the groups of four \
                  people use on invoices, separated by single spaces or hyphens. It is the \
                  strongest bank identifier in an investigative corpus, because it names one \
                  account at one institution.",
        standards: &[
            "ISO 13616: International Bank Account Number",
            "ISO 7064 Mod 97, 10: the check character system it uses",
        ],
        checks: &[
            "the country code has an entry in the IBAN registry, so a country that issues no IBANs \
             is a rejection",
            "the length is exactly what the registry gives for that country",
            "every position matches the registry's structure, with digits where it says digits and \
             letters where it says letters",
            "ISO 7064 mod-97-10 over the rearranged form, which is what makes the country code and \
             the check digits part of the arithmetic",
            "nothing alphanumeric runs into the match from the left",
        ],
        not_checked: &[
            "whether the account exists, is open, or belongs to whoever the text says",
            "the national check digits some countries embed inside their own account number, which \
             are a separate scheme per country",
            "that the bank code names a bank that still trades under that code",
        ],
        authorities: &[
            Authority {
                name: "SWIFT",
                role: "is the registration authority for ISO 13616 and publishes the IBAN registry",
                url: "https://www.swift.com/standards/data-standards/iban-international-bank-account-number",
            },
            Authority {
                name: "International Organization for Standardization",
                role: "publishes ISO 13616 and ISO 7064",
                url: "https://www.iso.org/standard/81090.html",
            },
        ],
        ftm: FtmMapping {
            schema: "BankAccount",
            property: "iban",
            note: "FollowTheMoney's BankAccount schema takes the IBAN as its own typed property \
                   and uses it as a caption, which is exactly this value.",
        },
        references: &[
            Reference {
                title: "IBAN registry",
                url: "https://www.swift.com/standards/data-standards/iban-international-bank-account-number",
                note: "the per-country length and structure this rule validates against",
            },
            Reference {
                title: "IBAN checksum validation",
                url: "https://en.wikipedia.org/wiki/International_Bank_Account_Number#Validating_the_IBAN",
                note: "the rearrangement and the mod-97 arithmetic, worked through",
            },
        ],
    },
    RuleDoc {
        rule_id: "bank.bic",
        entity_type: EntityType::BankAccount,
        title: "Business Identifier Code (SWIFT code)",
        matches: "The code that names a financial institution rather than an account: four \
                  letters of institution, two of country, two of location, and an optional branch. \
                  It is what a payment instruction carries beside the account number.",
        standards: &["ISO 9362: Business identifier code (BIC)"],
        checks: &[
            "the length is eight or eleven characters, the only two ISO 9362 defines",
            "positions five and six are an ISO 3166-1 alpha-2 country code that exists",
            "one of the words BIC, SWIFT, SWIFTBIC, IBAN, bank, beneficiary or correspondent \
             appears within 48 bytes either side",
            "nothing alphanumeric runs into the match from either side",
        ],
        not_checked: &[
            "any check digit. ISO 9362 defines none, so the structure and the label beside it are \
             the whole of what can be verified",
            "that the code is registered, or that the institution it names still exists",
            "that the branch code is one the institution actually uses",
        ],
        authorities: &[Authority {
            name: "SWIFT",
            role: "is the registration authority for ISO 9362 and allocates the codes",
            url: "https://www.swift.com/standards/data-standards/bic-business-identifier-code",
        }],
        ftm: FtmMapping {
            schema: "BankAccount",
            property: "bic",
            note: "FollowTheMoney's BankAccount schema carries the institution's BIC beside the \
                   account number, which is where a code found in a payment instruction belongs.",
        },
        references: &[
            Reference {
                title: "BIC at SWIFT",
                url: "https://www.swift.com/standards/data-standards/bic-business-identifier-code",
                note: "the structure and the registration process",
            },
            Reference {
                title: "SWIFT BIC search",
                url: "https://www.swift.com/bsl/",
                note: "where a code can be looked up against the register",
            },
        ],
    },
    RuleDoc {
        rule_id: "bank.payment_card",
        entity_type: EntityType::BankAccount,
        title: "Payment card number",
        matches: "The number embossed on a payment card, written compactly or in the groups of \
                  four a form prints it in. It is the instrument a payment was made with rather \
                  than the account behind it, and in a document it is normally beside the words \
                  that say so.",
        standards: &[
            "ISO/IEC 7812-1, Identification cards: identification of issuers, numbering system",
            "ISO/IEC 7812-2: the application and registration procedures for issuer identifiers",
        ],
        checks: &[
            "the number is thirteen to nineteen digits, written compactly or with one separator \
             character used throughout. A run mixing spaces and hyphens is refused",
            "the Luhn check digit agrees",
            "the leading digits fall in a range allocated to a card issuer, and the number is as \
             long as that issuer's cards are. A Luhn-valid run whose prefix belongs to no issuer \
             is not a card",
            "one of the words card, cardholder, Visa, Mastercard, Amex, Discover, JCB, Diners or \
             Maestro appears within 48 bytes either side, in the candidate's own field. Luhn is a \
             one-in-ten filter and the issuer table does not close it on its own: over a page of \
             invoice-like text, article and tracking numbers still pass both. The cue is what \
             makes the match defensible, and if it is ever dropped the rule goes with it",
            "nothing alphanumeric and no hyphen runs into the match from either side",
        ],
        not_checked: &[
            "whether the card was ever issued, is still valid, or belongs to whoever the text says",
            "the expiry date and the card verification value, which are separate fields this rule \
             does not read and does not pair with the number",
            "the airline range. A fifteen-digit run beginning with 1 is not matched, because that \
             is also the shape of half the reference numbers in a logistics document",
            "which account the card is presented against; a card and an account are different \
             things and this value names only the card",
        ],
        authorities: &[
            Authority {
                name: "International Organization for Standardization",
                role: "publishes ISO/IEC 7812 and defines the numbering system",
                url: "https://www.iso.org/standard/70484.html",
            },
            Authority {
                name: "American Bankers Association",
                role: "is the registration authority for issuer identification numbers",
                url: "https://www.aba.com/about-us/routing-number",
            },
        ],
        ftm: FtmMapping {
            schema: "BankAccount",
            property: "res:cardNumber",
            note: "FollowTheMoney's BankAccount has accountNumber, iban and bic and no property \
                   for a card. The card is not written to accountNumber: it is an instrument \
                   presented against an account rather than the account itself, and merging the \
                   two pollutes the join a consumer builds on accountNumber. This is a local \
                   extension in the res: namespace.",
        },
        references: &[
            Reference {
                title: "Luhn algorithm",
                url: "https://en.wikipedia.org/wiki/Luhn_algorithm",
                note: "the check digit, which is ISO/IEC 7812-1 annex B",
            },
            Reference {
                title: "Payment card number",
                url: "https://en.wikipedia.org/wiki/Payment_card_number",
                note: "the issuer identification ranges and the length each issuer uses",
            },
        ],
    },
    RuleDoc {
        rule_id: "bank.aba_routing",
        entity_type: EntityType::BankAccount,
        title: "ABA routing transit number",
        matches: "The nine-digit number that names the United States financial institution an \
                  account is held at, printed on a cheque beside the account number, and quoted \
                  in a payment instruction as the routing or transit number.",
        standards: &[
            "ABA routing transit number: the American Bankers Association's numbering system, \
             ANSI X9.13",
        ],
        checks: &[
            "the leading two digits are a Federal Reserve routing symbol that was actually \
             allocated: 00 to 12, 21 to 32, 61 to 72, or 80. Everything else is not a routing \
             number whatever its checksum says",
            "the 3-7-1 weighted sum over the nine digits is zero modulo ten",
            "one of the words routing, ABA, abarouting, bankrouting, RTN or transit appears \
             within 48 bytes either side, in the candidate's own field. Two filters over nine \
             digits are still nine digits, and a nine-digit reference number passes the checksum \
             one time in ten",
            "nothing alphanumeric runs into the match from either side",
        ],
        not_checked: &[
            "whether the number names a bank that still exists, or one that is still in the \
             Federal Reserve's directory",
            "the hyphenated fractional spelling printed on some cheques, which is not matched: \
             nine digits behind a one-in-ten checksum do not buy separator tolerance",
            "which of an institution's routing numbers this is. A bank has several, by region \
             and by transfer type",
        ],
        authorities: &[Authority {
            name: "American Bankers Association",
            role: "is the registration authority and assigns routing numbers through Accuity",
            url: "https://www.aba.com/about-us/routing-number",
        }],
        ftm: FtmMapping {
            schema: "BankAccount",
            property: "res:routingNumber",
            note: "FollowTheMoney's BankAccount names the institution with bic and has no \
                   property for a domestic routing number, which is the same fact in the United \
                   States clearing system. This is a local extension in the res: namespace.",
        },
        references: &[
            Reference {
                title: "ABA routing transit number",
                url: "https://en.wikipedia.org/wiki/ABA_routing_transit_number",
                note: "the routing symbol ranges and the 3-7-1 check digit",
            },
            Reference {
                title: "Routing number lookup",
                url: "https://routingnumber.aba.com/",
                note: "where a number can be checked against the register",
            },
        ],
    },
    RuleDoc {
        rule_id: "company.lei",
        entity_type: EntityType::CompanyId,
        title: "Legal Entity Identifier",
        matches: "The twenty-character code that identifies a party to a financial transaction: \
                  four characters naming the unit that issued it, thirteen identifying the \
                  organisation, and two check digits. It is the closest thing to a global company \
                  key, and it resolves to a named legal entity with a jurisdiction and an address.",
        standards: &[
            "ISO 17442: Legal entity identifier (LEI)",
            "ISO 7064 Mod 97, 10: the check character system it uses",
        ],
        checks: &[
            "ISO 7064 mod-97-10 over all twenty characters, with letters counting as their base-36 \
             value",
            "the length is exactly twenty, and the last two positions are digits",
            "nothing alphanumeric runs into the match from either side, which is what keeps \
             twenty characters of a hash from being read as a code",
        ],
        not_checked: &[
            "whether the identifier was ever issued. The arithmetic agrees for numbers GLEIF has \
             never allocated",
            "whether the registration is current: an LEI can lapse, and the code stays valid \
             arithmetic",
            "which company it names. The card links to GLEIF's search rather than resolving it",
        ],
        authorities: &[
            Authority {
                name: "Global Legal Entity Identifier Foundation",
                role: "operates the LEI system and publishes the full population as open data",
                url: "https://www.gleif.org/",
            },
            Authority {
                name: "International Organization for Standardization",
                role: "publishes ISO 17442",
                url: "https://www.iso.org/standard/78829.html",
            },
        ],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "leiCode",
            note: "FollowTheMoney defines leiCode on the abstract LegalEntity, which every \
                   concrete company or organisation schema inherits.",
        },
        references: &[
            Reference {
                title: "GLEIF search",
                url: "https://search.gleif.org/",
                note: "the public register, where a code resolves to the entity it names",
            },
            Reference {
                title: "ISO 17442 at ISO",
                url: "https://www.iso.org/standard/78829.html",
                note: "the standard that defines the structure and the check digits",
            },
        ],
    },
    RuleDoc {
        rule_id: "company.vat_eu",
        entity_type: EntityType::CompanyId,
        title: "EU VAT identification number",
        matches: "The tax number a business quotes for trade inside the European Union: a \
                  two-letter member-state prefix followed by that state's own registration \
                  number. Every member state is covered, each with the check-digit algorithm its \
                  own tax administration publishes. Greece is the exception to the country code. \
                  It writes EL where ISO 3166-1 writes GR.",
        standards: &[
            "Council Directive 2006/112/EC: the common system of value added tax",
            "ISO 3166-1 alpha-2: the prefix, with EL for Greece",
            "ISO 7064 Mod 11, 10: used by Germany and Croatia",
            "ISO 7064 Mod 97, 10: used by the current Dutch form",
        ],
        checks: &[
            "the prefix is one of the twenty-seven member states, and the body's length and \
             alphabet are the ones that state issues",
            "the member state's own check digit, ported from python-stdnum: Luhn for Austria, \
             Italy and Sweden, ISO 7064 for Germany, Croatia and the Netherlands, and a weighted \
             sum for the rest",
            "where a state admits a personal number as a VAT number (Bulgaria, Czechia, Latvia, \
             Romania and Slovakia), the date of birth it encodes has to be a day that exists",
            "component fields the state constrains: Italy's province code, Romania's county code, \
             Lithuania's fixed digit before the check digit, Sweden's trailing 01",
            "nothing alphanumeric runs into the match from either side, which is what keeps a \
             prefix of a longer digit run out of the facet",
        ],
        not_checked: &[
            "whether the number is registered, or registered for intra-community trade. That is \
             a VIES query, and this service makes no network calls",
            "whether the business still exists: a deregistered number keeps its arithmetic",
            "numbers written with the separators an invoice often uses. Only the compact form, \
             prefix immediately followed by the body, is matched: a check digit over a short body \
             is a weak filter, and a pattern loose enough to admit every national separator \
             convention would reach far more ordinary prefixed digit runs than the arithmetic can \
             turn away",
            "bare national company registration numbers without their VAT prefix. A nine-digit \
             run with a check digit is still a nine-digit run",
            "Romanian numbers shorter than four digits, which the register does allocate: RO and \
             two digits is a token ordinary text produces, and one check digit does not carry it",
        ],
        authorities: &[
            Authority {
                name: "European Commission, Directorate-General for Taxation and Customs Union",
                role: "operates VIES, which answers whether a number is registered",
                url: "https://ec.europa.eu/taxation_customs/vies/",
            },
            Authority {
                name: "The national tax administration of the issuing member state",
                role: "allocates the number and defines its check digit",
                url: "https://taxation-customs.ec.europa.eu/national-tax-websites_en",
            },
        ],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "vatCode",
            note: "FollowTheMoney defines vatCode on the abstract LegalEntity, so a company, an \
                   organisation or a public body all carry it on the same property.",
        },
        references: &[
            Reference {
                title: "VIES VAT number validation",
                url: "https://ec.europa.eu/taxation_customs/vies/",
                note: "the Commission's service, which confirms registration rather than form",
            },
            Reference {
                title: "python-stdnum",
                url: "https://arthurdejong.org/python-stdnum/",
                note: "the reference implementation the member-state arithmetic is ported from",
            },
        ],
    },
    RuleDoc {
        rule_id: "company.vat_non_eu",
        entity_type: EntityType::CompanyId,
        title: "VAT identification number outside the European Union",
        matches: "The same VATIN shape outside the Union: an ISO 3166-1 alpha-2 country code \
                  followed by that country's own tax number. Eight countries are covered: the \
                  United Kingdom and the Isle of Man (GB), Switzerland (CH), Norway (NO), Serbia \
                  (RS), Montenegro (ME), North Macedonia (MK), Russia (RU) and Türkiye (TR). The \
                  Swiss and Norwegian numbers carry the tax abbreviation their own \
                  administrations append, MWST, TVA, IVA or TPV for Switzerland and MVA for \
                  Norway.",
        standards: &[
            "ISO 3166-1 alpha-2: the country prefix",
            "ISO 7064 Mod 11, 10: used by Serbia",
        ],
        checks: &[
            "the prefix is one of the eight countries whose check digit is implemented, and the \
             body's length and alphabet are the ones that country issues",
            "the country's own check digit, ported from python-stdnum: the weighted sum modulo 97 \
             for Great Britain, modulo 11 for Switzerland, Norway, Montenegro, North Macedonia and \
             Russia, ISO 7064 for Serbia, and a positional doubling ladder for Türkiye",
            "the tax suffix Switzerland and Norway require, which is part of the number rather \
             than of the surrounding text",
            "component fields the country constrains: a British government department's serial \
             runs below 500 and a health authority's from 500 up, and a British branch identifier \
             takes no part in the arithmetic",
            "nothing alphanumeric runs into the match from either side, which is what keeps a \
             prefix of a longer digit run out of the facet",
        ],
        not_checked: &[
            "whether the number is registered. That is a query against the national register, \
             and this service makes no network calls",
            "whether the business still exists: a deregistered number keeps its arithmetic",
            "numbers written with the separators an invoice often uses. Only the compact form, \
             prefix immediately followed by the body, is matched: a check digit over a short body \
             is a weak filter, and a pattern loose enough to admit every national separator \
             convention would reach far more ordinary prefixed digit runs than the arithmetic can \
             turn away",
            "countries whose VAT number carries no check digit, such as Albania, Iceland and San \
             Marino: a prefix with no arithmetic behind it is a two-letter string in front of a \
             digit run, which is the shape this rule exists to avoid",
            "bare national company registration numbers without their country prefix. A \
             nine-digit run with a check digit is still a nine-digit run",
            "the five-character British GD and HA form, which the scheme gives no check digit at \
             all; it is accepted on the literal marker and the serial range, and reported with the \
             no-checksum flag",
        ],
        authorities: &[
            Authority {
                name: "HM Revenue & Customs",
                role: "allocates the British VAT registration number",
                url: "https://www.gov.uk/government/organisations/hm-revenue-customs",
            },
            Authority {
                name: "The national tax administration of the issuing country",
                role: "allocates the number and defines its check digit",
                url: "https://www.oecd.org/tax/automatic-exchange/crs-implementation-and-assistance/tax-identification-numbers/",
            },
        ],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "vatCode",
            note: "The same property the EU numbers use: FollowTheMoney's vatCode is not scoped to \
                   the Union, so one property carries every jurisdiction.",
        },
        references: &[
            Reference {
                title: "Check a UK VAT number",
                url: "https://www.gov.uk/check-uk-vat-number",
                note: "HMRC's service, which confirms registration rather than form",
            },
            Reference {
                title: "python-stdnum",
                url: "https://arthurdejong.org/python-stdnum/",
                note: "the reference implementation the country arithmetic is ported from",
            },
        ],
    },
    RuleDoc {
        rule_id: "company.se_organisationsnummer",
        entity_type: EntityType::CompanyId,
        title: "Organisationsnummer (Sweden)",
        matches: "The ten-digit number Bolagsverket assigns to a Swedish company, association, \
                  foundation or public body, written compactly or with the hyphen in front of the \
                  last four digits. It is the first ten digits of the country's VAT number, and it \
                  is what a Swedish filing, invoice or register extract identifies a company by.",
        standards: &[
            "Organisationsnummer, lag (1974:174) om identitetsbeteckning för juridiska personer",
            "Luhn algorithm, ISO/IEC 7812-1 annex B",
        ],
        checks: &[
            "Luhn over the ten digits",
            "the leading digit is a legal form that was allocated: 1 an estate, 2 a public \
             authority, 3 a foreign company, 5 a limited company, 6 a simple partnership, 7 a \
             cooperative, 8 an association or foundation, 9 a partnership. 0 and 4 were never used",
            "the third digit is at least 2, which is what separates this from a personnummer \
             written the same way: that digit is the tens of a month field there and never reaches \
             two",
            "one of the words organisationsnummer, orgnummer, orgnr, org nr, org.nr, \
             företagsnummer, company identity or company registration appears within 48 bytes \
             either side, in the candidate's own field. This is the one bare-numeric company \
             register number that ships, and it ships because it carries Luhn and a legal-form \
             digit and a mandatory cue; if the cue requirement is ever dropped, the rule goes \
             with it",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "whether the number is registered, or whether the body it names still trades",
            "which of the eight legal forms is the right one for the body named beside it in the \
             text. The leading digit is read as written",
            "the Swedish VAT number this sits inside. SE556016068001 is a VAT number containing an \
             organisationsnummer, and the longer VAT reading wins the overlap on length",
        ],
        authorities: &[
            Authority {
                name: "Bolagsverket",
                role: "assigns organisationsnummer to companies and associations",
                url: "https://bolagsverket.se/",
            },
            Authority {
                name: "Skatteverket",
                role: "assigns them to the remaining legal forms and builds the VAT number on top",
                url: "https://www.skatteverket.se/",
            },
        ],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "registrationNumber",
            note: "FollowTheMoney defines registrationNumber on the abstract parent, for exactly \
                   this: the number a company register knows an entity by. It is inherited by \
                   Company, Organization and PublicBody, which is the same set of legal forms the \
                   leading digit distinguishes.",
        },
        references: &[
            Reference {
                title: "Organisationsnummer",
                url: "https://sv.wikipedia.org/wiki/Organisationsnummer",
                note: "the legal-form groups the leading digit names",
            },
            Reference {
                title: "stdnum/se/orgnr.py",
                url: "https://arthurdejong.org/python-stdnum/doc/stdnum.se.orgnr.html",
                note: "the reference implementation, which checks the length and Luhn",
            },
        ],
    },
    RuleDoc {
        rule_id: "security.isin",
        entity_type: EntityType::Security,
        title: "International Securities Identification Number",
        matches: "The twelve-character code that names a tradable instrument worldwide: a \
                  two-letter prefix, a nine-character national identifier and a check digit. It is \
                  the join key between a holding in one filing and the same holding in another.",
        standards: &[
            "ISO 6166: Securities and related financial instruments, international securities \
             identification numbering system",
        ],
        checks: &[
            "the Luhn check digit over the letter-expanded form, so the prefix takes part in the \
             arithmetic",
            "the prefix is an ISO 3166-1 country, or one of the allocations ISO 6166 makes to \
             substitute agencies and to internationally cleared securities",
            "the length is exactly twelve and the last position is a digit",
            "nothing alphanumeric runs into the match from either side",
        ],
        not_checked: &[
            "whether the instrument exists, is listed, or is still traded",
            "the national identifier inside it, which may be a CUSIP or a SEDOL with its own check \
             digit that this rule does not separately verify",
            "that the prefix says where the issuer is. It says which agency allocated the number",
        ],
        authorities: &[
            Authority {
                name: "Association of National Numbering Agencies",
                role: "is the registration authority for ISO 6166 and coordinates the national \
                       numbering agencies",
                url: "https://www.anna-web.org/",
            },
            Authority {
                name: "International Organization for Standardization",
                role: "publishes ISO 6166",
                url: "https://www.iso.org/standard/78502.html",
            },
        ],
        ftm: FtmMapping {
            schema: "Security",
            property: "isin",
            note: "FollowTheMoney's Security schema takes the ISIN as a typed property and uses it \
                   as the entity's caption.",
        },
        references: &[Reference {
            title: "ANNA, the ISIN registration authority",
            url: "https://www.anna-web.org/standards/isin-iso-6166/",
            note: "how the numbers are allocated and by whom",
        }],
    },
    RuleDoc {
        rule_id: "security.cusip",
        entity_type: EntityType::Security,
        title: "CUSIP number",
        matches: "The nine-character code used for securities issued in the United States and \
                  Canada: six characters of issuer, two of issue and a check digit. It is a bare \
                  alphanumeric token, which is why it is only accepted beside a word that says \
                  what it is.",
        standards: &["CUSIP, as administered by CUSIP Global Services under ANSI X9.6"],
        checks: &[
            "the check digit, a Luhn variant with alternating weights of one and two",
            "one of the words CUSIP, SEDOL, ISIN, ticker, security or CIK appears within 48 bytes \
             either side",
            "the length is exactly nine and the last position is a digit",
            "nothing alphanumeric runs into the match from either side",
        ],
        not_checked: &[
            "whether the security exists or was ever issued",
            "the extended alphabet: CUSIPs containing *, @ or # are used for some private \
             placements and are not matched",
            "whether the issuer prefix belongs to the company the surrounding text names",
        ],
        authorities: &[Authority {
            name: "CUSIP Global Services",
            role: "allocates CUSIP numbers and operates the register",
            url: "https://www.cusip.com/",
        }],
        ftm: FtmMapping {
            schema: "Security",
            property: "res:cusip",
            note: "FollowTheMoney's Security schema has isin, ticker and figiCode but no CUSIP \
                   property, so this is a local extension in the res: namespace.",
        },
        references: &[Reference {
            title: "CUSIP Global Services",
            url: "https://www.cusip.com/",
            note: "the administrator, and where a number can be looked up",
        }],
    },
    RuleDoc {
        rule_id: "security.sedol",
        entity_type: EntityType::Security,
        title: "SEDOL number",
        matches: "The seven-character code the London Stock Exchange assigns to securities traded \
                  in the United Kingdom and Ireland. Its alphabet has no vowels, which is the only \
                  self-identification it offers, so it is accepted only beside a word that says \
                  what it is.",
        standards: &["SEDOL, the Stock Exchange Daily Official List numbering scheme"],
        checks: &[
            "the check digit, a weighted sum with weights 1, 3, 1, 7, 3, 9 modulo ten",
            "the alphabet excludes the vowels, which is written into the pattern itself",
            "numbers issued since 2004 begin with a letter and older ones are entirely numeric, so \
             a digit followed by letters is neither",
            "one of the words CUSIP, SEDOL, ISIN, ticker, security or CIK appears within 48 bytes \
             either side",
            "nothing alphanumeric runs into the match from either side",
        ],
        not_checked: &[
            "whether the security exists or is still listed",
            "which instrument it names. Resolution needs the exchange's own data",
        ],
        authorities: &[Authority {
            name: "London Stock Exchange",
            role: "assigns SEDOL numbers and publishes the masterfile",
            url: "https://www.lseg.com/en/data-analytics/financial-data/identifiers/sedol",
        }],
        ftm: FtmMapping {
            schema: "Security",
            property: "res:sedol",
            note: "FollowTheMoney's Security schema has isin, ticker and figiCode but no SEDOL \
                   property, so this is a local extension in the res: namespace.",
        },
        references: &[Reference {
            title: "SEDOL masterfile",
            url: "https://www.lseg.com/en/data-analytics/financial-data/identifiers/sedol",
            note: "the issuing authority and the scheme's own documentation",
        }],
    },
    RuleDoc {
        rule_id: "vessel.imo",
        entity_type: EntityType::Vessel,
        title: "IMO ship identification number",
        matches: "The seven-digit number that identifies a ship's hull for its whole life, \
                  regardless of how often it is renamed, reflagged or resold. That permanence is \
                  what makes it the anchor for sanctions and ownership work, where the name on the \
                  stern is the least stable thing about a vessel.",
        standards: &[
            "IMO Resolution A.1078(28): IMO ship identification number scheme",
            "ISO 8712: Ships and marine technology, IMO ship identification number",
        ],
        checks: &[
            "the check digit, a weighted sum of the first six digits with weights seven down to \
             two, modulo ten",
            "either the literal marker IMO stands immediately before the digits, or one of the \
             words IMO, vessel, ship, tanker, hull or flag appears within 48 bytes either side",
            "the run is exactly seven digits and nothing alphanumeric touches it on either side",
        ],
        not_checked: &[
            "whether the ship exists, is still in class, or was ever registered. Many hulls carry \
             a number whose check digit does not agree, and those are rejected here",
            "the ship's current name, flag or owner, none of which the number encodes",
        ],
        authorities: &[Authority {
            name: "International Maritime Organization",
            role: "owns the scheme; IHS Markit allocates the numbers on its behalf",
            url: "https://www.imo.org/",
        }],
        ftm: FtmMapping {
            schema: "Vessel",
            property: "imoNumber",
            note: "FollowTheMoney's Vessel schema defines imoNumber and features it in the caption, \
                   which is exactly this number.",
        },
        references: &[Reference {
            title: "IMO ship identification number scheme",
            url: "https://www.imo.org/en/OurWork/MSAS/Pages/IMO-identification-number-scheme.aspx",
            note: "the scheme, the allocation process and the check-digit rule",
        }],
    },
    RuleDoc {
        rule_id: "vessel.mmsi",
        entity_type: EntityType::Vessel,
        title: "MMSI (Maritime Mobile Service Identity)",
        matches: "The nine-digit identity a ship's radio and AIS transponder broadcast. Unlike an \
                  IMO number it belongs to the station rather than the hull, so it changes when a \
                  ship is reflagged, which is itself the signal an investigator is often looking \
                  for.",
        standards: &[
            "ITU-R M.585: Assignment and use of identities in the maritime mobile service",
        ],
        checks: &[
            "the first three digits are a Maritime Identification Digit triple the ITU has \
             actually allocated, which is also where the flag state comes from",
            "one of the words MMSI, AIS, call sign, callsign, vessel or ship appears within 48 \
             bytes either side",
            "the run is exactly nine digits and nothing alphanumeric touches it on either side",
        ],
        not_checked: &[
            "a check digit. An MMSI has none, which is why the match carries the no-checksum flag",
            "coast-station, group-call and craft-associated identities, where the MID sits at \
             another position; reading the wrong three digits as a flag state is worse than not \
             reading them, so those forms are not matched",
            "whether the station is licensed or the transponder is transmitting the truth",
        ],
        authorities: &[Authority {
            name: "International Telecommunication Union",
            role: "allocates Maritime Identification Digits to administrations",
            url: "https://www.itu.int/en/ITU-R/terrestrial/fmd/Pages/mid.aspx",
        }],
        ftm: FtmMapping {
            schema: "Vessel",
            property: "mmsi",
            note: "FollowTheMoney's Vessel schema defines mmsi for exactly this identity.",
        },
        references: &[Reference {
            title: "ITU Maritime Identification Digits",
            url: "https://www.itu.int/en/ITU-R/terrestrial/fmd/Pages/mid.aspx",
            note: "the allocated triples and the administration each belongs to",
        }],
    },
    RuleDoc {
        rule_id: "container.iso6346",
        entity_type: EntityType::CargoContainer,
        title: "ISO 6346 container number",
        matches: "The eleven-character number stencilled on an intermodal shipping container: \
                  three letters of owner code, a category letter, six digits of serial and a check \
                  digit. It is what ties a bill of lading to a physical box, which is why it \
                  matters for trade and sanctions-evasion work.",
        standards: &["ISO 6346: Freight containers, coding, identification and marking"],
        checks: &[
            "the check digit, each character's value times a power of two, summed, modulo eleven \
             then modulo ten",
            "the fourth character is one of U, J, Z or R, the only equipment categories the \
             standard defines, which is what makes the format self-identifying",
            "single spaces inside the grouped written form are stripped before checking",
            "nothing alphanumeric runs into the match from either side",
        ],
        not_checked: &[
            "whether the owner code is registered with the Bureau International des Containers",
            "the size and type code, which is stencilled beside the number and is not part of it",
            "whether the container exists or what it holds",
            "the number written in lower case: the standard's alphabet is capitals, that is how a \
             container is stencilled and how a bill of lading prints it, and a lower-case eleven \
             character run in running text is a hash fragment or a file name far more often than \
             it is a container",
        ],
        authorities: &[Authority {
            name: "Bureau International des Containers et du Transport Intermodal",
            role: "maintains the owner-code register the standard depends on",
            url: "https://www.bic-code.org/",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:containerMentioned",
            note: "FollowTheMoney has no schema for an intermodal container and no property for \
                   its number, so this is a local extension in the res: namespace, following the \
                   shape of its own ipMentioned and ibanMentioned properties.",
        },
        references: &[Reference {
            title: "BIC container code register",
            url: "https://www.bic-code.org/bic-codes/",
            note: "where an owner code can be resolved to a company",
        }],
    },
    RuleDoc {
        rule_id: "device.imei",
        entity_type: EntityType::Device,
        title: "IMEI (International Mobile Equipment Identity)",
        matches: "The fifteen-digit number that identifies a mobile handset rather than its \
                  subscriber. It survives a change of SIM, which is what makes it the durable half \
                  of a mobile identity.",
        standards: &["3GPP TS 23.003: Numbering, addressing and identification"],
        checks: &[
            "the Luhn check digit over all fifteen digits",
            "one of the words IMEI, handset or device appears within 48 bytes either side",
            "the digits total exactly fifteen once the hyphens or spaces of the grouped written \
             form are stripped",
            "nothing alphanumeric and no hyphen touches the match on either side, so a slice of a \
             longer code is not read as a handset",
        ],
        not_checked: &[
            "the sixteen-digit IMEISV form, which carries a software version instead of a check \
             digit and so cannot be verified",
            "whether the type allocation code was issued, or to which manufacturer. The GSMA \
             database that answers that is not public",
            "whether the handset exists or is in service",
        ],
        authorities: &[Authority {
            name: "GSM Association",
            role: "allocates type allocation codes and runs the IMEI database",
            url: "https://www.gsma.com/services/imei-database/",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:imeiMentioned",
            note: "FollowTheMoney has no device schema and no IMEI property, so this is a local \
                   extension in the res: namespace, shaped like its own ipMentioned property.",
        },
        references: &[Reference {
            title: "GSMA IMEI allocation and approval process",
            url: "https://www.gsma.com/services/imei-database/",
            note: "how type allocation codes are assigned",
        }],
    },
    RuleDoc {
        rule_id: "device.mac",
        entity_type: EntityType::Device,
        title: "MAC address",
        matches: "The six-octet hardware address of a network interface, written with colons, \
                  hyphens or as the three dotted quads Cisco equipment prints. It ties a log line \
                  to a physical piece of equipment rather than to an account.",
        standards: &["IEEE 802: MAC address format and the OUI registry"],
        checks: &[
            "the separators are consistent, so two adjacent hex fields that happen to sit beside \
             different punctuation are not read as one address",
            "exactly twelve hexadecimal digits once the separators are removed",
            "no separator and nothing alphanumeric touches the match on either side, which is what \
             keeps a twenty-octet certificate fingerprint out of the device facet",
        ],
        not_checked: &[
            "a check digit, because the format has none, so the match carries the no-checksum flag",
            "the bare twelve-hex spelling, which is indistinguishable from half a hash and is \
             deliberately not matched",
            "which manufacturer the leading three octets belong to: the IEEE OUI registry is not \
             vendored, so the bytes are reported and not resolved",
            "whether the address is locally administered, spoofed, or in use",
        ],
        authorities: &[Authority {
            name: "Institute of Electrical and Electronics Engineers",
            role: "allocates organisationally unique identifiers and publishes the registry",
            url: "https://standards.ieee.org/products-programs/regauth/",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:macAddressMentioned",
            note: "FollowTheMoney has ipMentioned but no property for a hardware address, so this \
                   is a local extension in the res: namespace following the same shape.",
        },
        references: &[Reference {
            title: "IEEE Registration Authority",
            url: "https://standards.ieee.org/products-programs/regauth/",
            note: "where an organisationally unique identifier can be looked up",
        }],
    },
    RuleDoc {
        rule_id: "network.ip",
        entity_type: EntityType::Network,
        title: "IP address",
        matches: "An IPv4 or IPv6 address, on its own or with a CIDR prefix length, including the \
                  IPv4-mapped form that writes the last four bytes as a dotted quad. Addresses are \
                  what tie a log line, a mail header and a hosting record to each other.",
        standards: &[
            "RFC 791: Internet Protocol",
            "RFC 4291: IP Version 6 Addressing Architecture",
            "RFC 4632: Classless Inter-domain Routing",
        ],
        checks: &[
            "the address parses through the standard library's own parsers, which enforce octet \
             ranges, group counts and the single :: elision. No arithmetic is duplicated in the \
             pattern",
            "a CIDR prefix length is within the address family's range",
            "none of the words version, versions, release, build, firmware, revision or semver \
             appears within 48 bytes either side, because a four-component dotted number is also \
             how a release is written and nothing in the number itself separates the two",
            "nothing alphanumeric and no dot, colon or slash continues the address on either side",
        ],
        not_checked: &[
            "whether the address is routable, allocated or reachable. Private, loopback and \
             documentation ranges are all matched",
            "who holds the allocation: resolving that needs registry data this service does not \
             carry",
            "that a dotted quad in a document is an address at all, beyond the negative context \
             test, so the match carries the no-checksum flag",
        ],
        authorities: &[Authority {
            name: "Internet Assigned Numbers Authority",
            role: "allocates address space to the regional internet registries",
            url: "https://www.iana.org/numbers",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "ipMentioned",
            note: "FollowTheMoney's Analyzable schema defines ipMentioned for an address found in \
                   a document's text; UserAccount.ipAddress is the property for an address an \
                   account was used from, which is a claim this service cannot make.",
        },
        references: &[Reference {
            title: "IANA IPv4 address space registry",
            url: "https://www.iana.org/assignments/ipv4-address-space/ipv4-address-space.xhtml",
            note: "which registry holds each block",
        }],
    },
    RuleDoc {
        rule_id: "network.asn",
        entity_type: EntityType::Network,
        title: "Autonomous system number",
        matches: "The number identifying a network that announces its own routes, such as AS64512 \
                  or ASN 64512. It is the unit at which hosting and transit are actually bought, so it is \
                  the level at which infrastructure ownership is visible.",
        standards: &[
            "RFC 4271: A Border Gateway Protocol 4",
            "RFC 6793: BGP support for four-octet autonomous system number space",
        ],
        checks: &[
            "the literal prefix AS or ASN is part of the match; a bare number is never accepted",
            "a space is allowed only after the three-letter spelling, because AS followed by a \
             space is the English word far more often than it is a network",
            "the number fits the allocated 32-bit space and is not zero, which is reserved",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "whether the number is allocated, or to whom. That needs regional registry data this \
             service does not carry",
            "the private and reserved ranges, which are matched like any other",
            "a check digit, because the format has none, so the match carries the no-checksum flag",
        ],
        authorities: &[Authority {
            name: "Internet Assigned Numbers Authority",
            role: "allocates autonomous system number blocks to the regional registries",
            url: "https://www.iana.org/numbers",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:asnMentioned",
            note: "FollowTheMoney has ipMentioned but no property for an autonomous system, so \
                   this is a local extension in the res: namespace following the same shape.",
        },
        references: &[Reference {
            title: "IANA autonomous system number registry",
            url: "https://www.iana.org/assignments/as-numbers/as-numbers.xhtml",
            note: "the allocated blocks and the registry each belongs to",
        }],
    },
    RuleDoc {
        rule_id: "vulnerability.cve",
        entity_type: EntityType::Vulnerability,
        title: "CVE identifier",
        matches: "The public identifier of a disclosed software vulnerability, such as CVE-2021-44228 \
                  its kind. The literal prefix makes it unmistakable, which is why it needs no \
                  check digit and no word beside it.",
        standards: &["The CVE Program's identifier syntax, CVE-YYYY-NNNN with four or more digits"],
        checks: &[
            "the literal prefix CVE- is part of the match",
            "the year falls between 1999, when the scheme started, and 2100",
            "the sequence is at least four digits, which is the minimum the syntax allows",
            "nothing alphanumeric and no hyphen touches the match on either side",
        ],
        not_checked: &[
            "whether the identifier has been assigned, published or rejected. A reserved entry \
             looks exactly like a published one",
            "the severity, the affected product, or whether the vulnerability applies to anything \
             the surrounding text names",
        ],
        authorities: &[Authority {
            name: "The CVE Program, operated by MITRE for CISA",
            role: "assigns identifiers through its CVE Numbering Authorities",
            url: "https://www.cve.org/",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:vulnerabilityMentioned",
            note: "FollowTheMoney models people, companies and documents and has no vulnerability \
                   property, so this is a local extension in the res: namespace.",
        },
        references: &[Reference {
            title: "CVE record lookup",
            url: "https://www.cve.org/CVERecord",
            note: "where a record can be read, including whether it is reserved",
        }],
    },
    RuleDoc {
        rule_id: "publication.doi",
        entity_type: EntityType::Publication,
        title: "DOI (Digital Object Identifier)",
        matches: "The persistent identifier of a published work: the directory code 10, a \
                  registrant code, and a suffix the registrant chooses. It resolves to a document \
                  long after the URL it was published at has gone.",
        standards: &["ISO 26324: Digital object identifier system"],
        checks: &[
            "the directory code is 10 and is followed by a registrant code of four to nine digits",
            "a slash and a non-empty suffix follow the registrant code",
            "sentence punctuation the suffix collected in prose is trimmed off the span",
            "nothing alphanumeric and no dot runs into the match from the left",
        ],
        not_checked: &[
            "a check digit, because the format has none, so the match carries the no-checksum flag",
            "whether the DOI resolves, or that the registrant code was ever allocated",
            "the suffix, which is opaque by design and may hold almost any character",
        ],
        authorities: &[Authority {
            name: "International DOI Foundation",
            role: "governs the DOI system; registration agencies such as Crossref allocate prefixes",
            url: "https://www.doi.org/",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:doiMentioned",
            note: "FollowTheMoney's Document schema has no DOI property, so this is a local \
                   extension in the res: namespace.",
        },
        references: &[Reference {
            title: "DOI resolution",
            url: "https://doi.org/",
            note: "resolves an identifier to the work it names",
        }],
    },
    RuleDoc {
        rule_id: "publication.orcid",
        entity_type: EntityType::Publication,
        title: "ORCID identifier",
        matches: "The sixteen-digit identifier that distinguishes one researcher from another with \
                  the same name, written in four hyphenated groups. It is the closest thing \
                  academic publishing has to a persistent author key.",
        standards: &["ISO 27729: International Standard Name Identifier, of which ORCID is a block"],
        checks: &[
            "the ISO 7064 mod 11-2 check character, where a final X stands for the value ten",
            "the four groups of four and the hyphens between them",
            "nothing alphanumeric and no hyphen touches the match on either side, which is what \
             keeps it out of longer hyphenated digit runs",
        ],
        not_checked: &[
            "whether the identifier was issued, or whom it belongs to. The ORCID registry answers \
             that and is not consulted here",
            "whether the record is public: many are restricted, and the identifier looks the same",
        ],
        authorities: &[Authority {
            name: "ORCID",
            role: "issues the identifiers and runs the registry",
            url: "https://orcid.org/",
        }],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "res:orcidMentioned",
            note: "FollowTheMoney's Person schema has no ORCID property, so this is a local \
                   extension in the res: namespace.",
        },
        references: &[Reference {
            title: "ORCID registry",
            url: "https://orcid.org/",
            note: "where an identifier resolves to a researcher record",
        }],
    },
    RuleDoc {
        rule_id: "message.rfc5322",
        entity_type: EntityType::MessageId,
        title: "Message-ID",
        matches: "The globally unique identifier a mail or news client puts on a message, written \
                  in angle brackets. It is what threads a conversation together, and what says two \
                  copies of a mail in two archives are the same mail.",
        standards: &["RFC 5322: Internet Message Format, section 3.6.4"],
        checks: &[
            "the angle brackets, which are what distinguish a message id from an address and are \
             part of the span but not of the value",
            "an at sign separating a non-empty left side from a right side",
            "one of the header names Message-ID, In-Reply-To, References or Resent-Message-ID \
             labels the value: everything between that name's colon and the value is whitespace, \
             list punctuation or complete angle-bracketed groups. Without such a label, an \
             angle-bracketed address in a From or To line has exactly the same shape, and a header \
             name merely mentioned nearby names nothing",
        ],
        not_checked: &[
            "whether the message exists, or that the generating host owns the domain. The right \
             side is conventionally a domain and is not required to be one",
            "uniqueness, which the standard asks of the generator and nobody can verify from the \
             text",
            "the left-side characters RFC 5322 atext admits that this pattern's class does not, \
             $, ^ and the backtick. The Outlook-style id \
             <000401c3daea$062d4b60$c589498e@ds.mda.ca> is therefore not matched, and because \
             email.basic reads the tail of it as an address the field yields one missed message id \
             and one spurious email rather than nothing",
        ],
        authorities: &[Authority {
            name: "Internet Engineering Task Force",
            role: "publishes RFC 5322, which defines the field",
            url: "https://www.ietf.org/",
        }],
        ftm: FtmMapping {
            schema: "Document",
            property: "messageId",
            note: "FollowTheMoney's Document schema defines messageId for exactly this identifier.",
        },
        references: &[Reference {
            title: "RFC 5322 section 3.6.4",
            url: "https://www.rfc-editor.org/rfc/rfc5322#section-3.6.4",
            note: "the identification fields and what a message id is required to be",
        }],
    },
    RuleDoc {
        rule_id: "coord.decimal",
        entity_type: EntityType::Coordinates,
        title: "Decimal degree coordinates",
        matches: "A latitude and longitude written as two signed decimal numbers separated by a \
                  comma, which is the form a mapping tool copies to the clipboard.",
        standards: &["WGS84: World Geodetic System 1984, the datum these values are read in"],
        checks: &[
            "the latitude is within ninety degrees of the equator and the longitude within a \
             hundred and eighty of the meridian",
            "both numbers carry at least four decimal places, because at three the form is a pair \
             of measurements as often as it is a place and no arithmetic separates the two",
            "nothing alphanumeric and no dot or comma continues the pair on either side",
        ],
        not_checked: &[
            "the datum, which is stated as WGS84 rather than read from the text. Every one of \
             these surface forms is conventionally written in it",
            "coarser coordinates: a pair with three or fewer decimal places is not matched, and \
             the degrees-minutes-seconds and Plus Code forms are where coarse positions are found",
            "whether the point is on land, in the country the surrounding text names, or anywhere \
             meaningful",
        ],
        authorities: &[Authority {
            name: "National Geospatial-Intelligence Agency",
            role: "maintains the World Geodetic System",
            url: "https://earth-info.nga.mil/",
        }],
        ftm: FtmMapping {
            schema: "Address",
            property: "latitude",
            note: "FollowTheMoney's Address schema defines latitude and longitude as separate \
                   properties; one match supplies both, and this names the first of the pair.",
        },
        references: &[Reference {
            title: "World Geodetic System 1984",
            url: "https://earth-info.nga.mil/index.php?dir=wgs84&action=wgs84",
            note: "the datum, and why a coordinate without one is ambiguous",
        }],
    },
    RuleDoc {
        rule_id: "coord.dms",
        entity_type: EntityType::Coordinates,
        title: "Degrees, minutes and seconds",
        matches: "A latitude and longitude in the sexagesimal form, such as 40°26'46\"N 79°58'56\"W. The degree \
                  sign and the hemisphere letters make it unmistakable, which is why it \
                  needs no cue word. Minutes and seconds may be marked with the ASCII apostrophe \
                  and quote or with the typographic prime and double prime a typeset document \
                  substitutes for them.",
        standards: &["WGS84: World Geodetic System 1984, the datum these values are read in"],
        checks: &[
            "both halves are present with their hemisphere letter; a latitude on its own is not a \
             point",
            "minutes and seconds are below sixty, because a sexagesimal reading that has run over \
             is a transcription error rather than a place",
            "the latitude is within ninety degrees and the longitude within a hundred and eighty, \
             after the hemisphere letter has been applied as the sign",
        ],
        not_checked: &[
            "the datum, which is stated as WGS84 rather than read from the text",
            "forms without a degree sign, and forms that write the hemisphere letter first",
            "whether the point is anywhere meaningful",
        ],
        authorities: &[Authority {
            name: "National Geospatial-Intelligence Agency",
            role: "maintains the World Geodetic System",
            url: "https://earth-info.nga.mil/",
        }],
        ftm: FtmMapping {
            schema: "Address",
            property: "latitude",
            note: "FollowTheMoney's Address schema defines latitude and longitude as separate \
                   properties; one match supplies both, and this names the first of the pair.",
        },
        references: &[Reference {
            title: "World Geodetic System 1984",
            url: "https://earth-info.nga.mil/index.php?dir=wgs84&action=wgs84",
            note: "the datum, and why a coordinate without one is ambiguous",
        }],
    },
    RuleDoc {
        rule_id: "coord.plus_code",
        entity_type: EntityType::Coordinates,
        title: "Plus Code (Open Location Code)",
        matches: "A short code that names a rectangle of the earth's surface rather than a point, \
                  8FVC9G8F+6W and its kind. It is used where street addresses do not exist, which \
                  is exactly the material a place name cannot be resolved from.",
        standards: &["Open Location Code specification, and WGS84 as the datum"],
        checks: &[
            "every character is in the twenty-character alphabet, which excludes all the vowels; \
             eight of them followed by a plus sign is not a word",
            "the first character puts the latitude south of the pole and the second puts the \
             longitude inside the meridian's range. The only range check the format offers",
            "the plus sign sits after the eighth character, where the format puts it",
            "nothing alphanumeric and no further plus sign touches the code on either side",
        ],
        not_checked: &[
            "the grid refinement character an eleven-character code carries: the point reported is \
             the centre of the ten-character cell, which is about fourteen metres across",
            "short codes, which omit the leading characters and are meaningless without a \
             reference location this service does not hold",
            "a check digit, because the format has none, so the match carries the no-checksum flag",
        ],
        authorities: &[Authority {
            name: "Google, as the specification's author",
            role: "publishes the Open Location Code specification and reference implementations",
            url: "https://github.com/google/open-location-code",
        }],
        ftm: FtmMapping {
            schema: "Address",
            property: "latitude",
            note: "FollowTheMoney's Address schema defines latitude and longitude as separate \
                   properties; one match supplies both, and this names the first of the pair.",
        },
        references: &[Reference {
            title: "Open Location Code specification",
            url: "https://github.com/google/open-location-code/blob/main/docs/olc_definition.adoc",
            note: "the alphabet, the encoding and the cell sizes",
        }],
    },
    RuleDoc {
        rule_id: "crypto.ethereum",
        entity_type: EntityType::CryptoWallet,
        title: "Ethereum address",
        matches: "The twenty-byte account address used by Ethereum and by every chain that copied \
                  its address format, written as 0x and forty hexadecimal characters.",
        standards: &[
            "EIP-55: Mixed-case checksum address encoding",
            "The Ethereum yellow paper's account address definition",
        ],
        checks: &[
            "0x followed by exactly forty hexadecimal characters, with nothing alphanumeric \
             touching the match on either side",
            "where the address is written in mixed case, the EIP-55 checksum: each hex letter's \
             capitalisation is the corresponding nibble of the Keccak-256 hash of the lower-case \
             address, above or below eight",
        ],
        not_checked: &[
            "an address written entirely in one case, which carries no checksum at all. Those \
             are reported with the no-checksum flag and a markedly lower confidence, because \
             nothing about them was verified",
            "whether the account exists, holds a balance, or is a contract rather than a wallet",
            "which chain it belongs to: the same address is valid on every EVM network",
        ],
        authorities: &[Authority {
            name: "Ethereum Foundation",
            role: "stewards the specification and the EIP process",
            url: "https://ethereum.org/",
        }],
        ftm: FtmMapping {
            schema: "CryptoWallet",
            property: "publicKey",
            note: "FollowTheMoney's CryptoWallet schema uses publicKey as the address; the chain \
                   is carried in the value's parts rather than invented as a property.",
        },
        references: &[Reference {
            title: "EIP-55",
            url: "https://eips.ethereum.org/EIPS/eip-55",
            note: "the mixed-case checksum, and why a lower-case address cannot be checked",
        }],
    },
    RuleDoc {
        rule_id: "crypto.bitcoin",
        entity_type: EntityType::CryptoWallet,
        title: "Bitcoin address",
        matches: "A Bitcoin payment address in any of the forms in use: the legacy base58check \
                  addresses beginning 1 or 3, and the native segwit addresses beginning bc1.",
        standards: &[
            "BIP-13: Address format for pay-to-script-hash",
            "BIP-173 and BIP-350: Bech32 and bech32m addresses for native segwit",
        ],
        checks: &[
            "for a base58 address, the base58check checksum: the last four bytes are the first \
             four of the double SHA-256 of everything before them",
            "the version byte is 0 or 5, so a test-network address is not reported as a Bitcoin one",
            "for a bc1 address, the bech32 or bech32m checksum, plus a witness version and program \
             length the standard actually defines",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "whether the address has ever been used, holds a balance, or belongs to anyone the \
             surrounding text names",
            "addresses of other chains that share the base58check format. The version byte is \
             what excludes them, and it excludes them silently",
        ],
        authorities: &[Authority {
            name: "The Bitcoin Improvement Proposal process",
            role: "publishes the address format specifications",
            url: "https://github.com/bitcoin/bips",
        }],
        ftm: FtmMapping {
            schema: "CryptoWallet",
            property: "publicKey",
            note: "FollowTheMoney's CryptoWallet schema uses publicKey as the address; the chain \
                   is carried in the value's parts rather than invented as a property.",
        },
        references: &[Reference {
            title: "BIP-173, bech32 addresses",
            url: "https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki",
            note: "the segwit address format and its checksum",
        }],
    },
    RuleDoc {
        rule_id: "natid.it_codice_fiscale",
        entity_type: EntityType::NationalId,
        title: "Codice fiscale (Italy)",
        matches: "The sixteen-character Italian tax code issued to individuals. Its fixed pattern \
                  of letter and digit positions is what makes it recognisable in running text \
                  without a label beside it.",
        standards: &["Codice fiscale, as defined by the Agenzia delle Entrate"],
        checks: &[
            "the CIN check character, a two-table weighted sum modulo twenty-six",
            "the fixed letter and digit pattern, including the omocodia substitutions that put \
             letters into digit positions when two people would otherwise collide",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "the date of birth and the sex the identifier encodes: the validator does not read those positions, the value does not carry them, and this service derives no personal attribute from an identifier",
            "the place-of-birth code, which resolves through a register this service does not carry",
            "whether the code was issued, or that it belongs to the person the text names",
        ],
        authorities: &[Authority {
            name: "Agenzia delle Entrate",
            role: "issues codici fiscali and operates the tax register",
            url: "https://www.agenziaentrate.gov.it/",
        }],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "idNumber",
            note: "FollowTheMoney's LegalEntity schema defines idNumber for a government-issued identifier; which scheme it is comes from the value's parts rather than from a new property.",
        },
        references: &[Reference {
            title: "Agenzia delle Entrate",
            url: "https://www.agenziaentrate.gov.it/",
            note: "the issuing authority",
        }],
    },
    RuleDoc {
        rule_id: "natid.es_nif_nie",
        entity_type: EntityType::NationalId,
        title: "NIF and NIE (Spain)",
        matches: "The Spanish tax identity number: eight digits and a check letter for a resident, \
                  or a leading X, Y or Z for a foreign national and K, L or M for the residual \
                  categories.",
        standards: &["NIF and NIE, as administered by the Agencia Tributaria"],
        checks: &[
            "the check letter, selected from a twenty-three letter alphabet by the number modulo \
             twenty-three, with X, Y and Z standing for a leading 0, 1 and 2",
            "the check alphabet itself, which omits the letters that would be confused with \
             digits and is written into the pattern",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "the CIF form issued to companies, which shares the length and uses a different check",
            "whether the number was issued, or to whom",
            "the number written in lower case, or split by hyphens as a form often prints it, such \
             as X-5253868-R. One check letter over a seven-digit body turns away twenty-two in \
             twenty-three, and the hyphenated shape is also the shape of a part number, so only \
             the compact upper-case form is matched",
        ],
        authorities: &[Authority {
            name: "Agencia Estatal de Administración Tributaria",
            role: "administers the NIF and the NIE",
            url: "https://sede.agenciatributaria.gob.es/",
        }],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "idNumber",
            note: "FollowTheMoney's LegalEntity schema defines idNumber for a government-issued identifier; which scheme it is comes from the value's parts rather than from a new property.",
        },
        references: &[Reference {
            title: "Agencia Tributaria",
            url: "https://sede.agenciatributaria.gob.es/",
            note: "the issuing authority",
        }],
    },
    RuleDoc {
        rule_id: "natid.mx_curp",
        entity_type: EntityType::NationalId,
        title: "CURP (Mexico)",
        matches: "The eighteen-character Clave Única de Registro de Población, issued to citizens \
                  and residents of Mexico. The fixed letter and digit pattern plus the state code \
                  make it self-identifying.",
        standards: &["CURP, as administered by RENAPO"],
        checks: &[
            "the check digit, each character's value in the registry alphabet weighted by its \
             distance from the end",
            "the two-character state code is one the registry uses, including NE for a birth \
             registered abroad",
            "the fixed pattern of four letters, six digits, six letters and two check positions",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "the date of birth and the sex the identifier encodes: the validator does not read those positions, the value does not carry them, and this service derives no personal attribute from an identifier",
            "the name positions, and the blocked-word list the registry applies to them",
            "whether the code was issued, or to whom",
        ],
        authorities: &[Authority {
            name: "Registro Nacional de Población",
            role: "assigns the CURP and operates the population register",
            url: "https://www.gob.mx/curp/",
        }],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "idNumber",
            note: "FollowTheMoney's LegalEntity schema defines idNumber for a government-issued identifier; which scheme it is comes from the value's parts rather than from a new property.",
        },
        references: &[Reference {
            title: "Consulta tu CURP",
            url: "https://www.gob.mx/curp/",
            note: "the registry's own lookup",
        }],
    },
    RuleDoc {
        rule_id: "natid.in_pan",
        entity_type: EntityType::NationalId,
        title: "PAN (India)",
        matches: "The ten-character Permanent Account Number issued for Indian income tax, held by \
                  individuals and by companies alike. Its fourth character says which.",
        standards: &["Permanent Account Number, as issued by the Income Tax Department of India"],
        checks: &[
            "the fourth character is one of the holder-type letters the department assigns",
            "the four-digit serial is not all zeroes, which the department does not issue",
            "one of the words PAN, income tax, Aadhaar, ITR or assessee appears within 48 bytes \
             either side",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "the check character, whose algorithm the department has never published, so the match \
             carries the no-checksum flag and the lower confidence",
            "the fifth character, which is the first letter of a surname or of an entity name",
            "whether the number was issued, or to whom",
        ],
        authorities: &[Authority {
            name: "Income Tax Department, Government of India",
            role: "issues Permanent Account Numbers",
            url: "https://incometaxindia.gov.in/",
        }],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "idNumber",
            note: "FollowTheMoney's LegalEntity schema defines idNumber for a government-issued identifier; which scheme it is comes from the value's parts rather than from a new property.",
        },
        references: &[Reference {
            title: "Permanent Account Number",
            url: "https://incometaxindia.gov.in/tutorials/1.permanent%20account%20number%20(pan).pdf",
            note: "the department's own description of the format",
        }],
    },
    RuleDoc {
        rule_id: "natid.pl_pesel",
        entity_type: EntityType::NationalId,
        title: "PESEL (Poland)",
        matches: "The eleven-digit number on the Polish population register, held by every Polish \
                  national and by resident foreigners. It is digits and nothing else, so it is \
                  reported only where the text says what it is.",
        standards: &[
            "PESEL: Powszechny Elektroniczny System Ewidencji Ludności, the Polish population \
             register",
        ],
        checks: &[
            "the weighted check digit agrees, over the first ten digits with the weights 1, 3, 7 \
             and 9 repeating",
            "the six leading digits are a day that exists in the calendar. The century is folded \
             into the month field, twenty being added to it once per century, so a month of 38 is \
             February of a year in the 2000s rather than a malformed month",
            "the word PESEL appears within 48 bytes either side, in the candidate's own field. \
             Eleven digits with one check digit is a one-in-ten filter and every long reference \
             number in a document passes it at that rate; the date and the word beside it are the \
             other two filters, and if the word is ever dropped the rule goes with it",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "whether the number was issued, or to whom",
            "the date of birth and the sex the number encodes. The date is read for one purpose, \
             to reject a number whose date could never have existed, and neither it nor the sex \
             reaches the value: detecting that a document mentions an identity number is a \
             different act from deriving personal attributes out of it",
            "the hyphenated spellings some forms print, which are not matched. The number is \
             registered as eleven digits",
        ],
        authorities: &[Authority {
            name: "Ministerstwo Cyfryzacji",
            role: "runs the PESEL register and assigns the numbers",
            url: "https://www.gov.pl/web/gov/uzyskaj-numer-pesel",
        }],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "idNumber",
            note: "FollowTheMoney's LegalEntity schema defines idNumber for a government-issued identifier; which scheme it is comes from the value's parts rather than from a new property.",
        },
        references: &[Reference {
            title: "PESEL check digit",
            url: "https://en.wikipedia.org/wiki/PESEL#Check_digit",
            note: "the weights and the century encoding in the month field",
        }],
    },
    RuleDoc {
        rule_id: "natid.se_personnummer",
        entity_type: EntityType::NationalId,
        title: "Personnummer (Sweden)",
        matches: "The Swedish personal identity number, in the ten-digit form or the twelve-digit \
                  one that spells out the century, with or without the separator in front of the \
                  last four digits. The coordination number issued to somebody who has no \
                  personnummer shares the format and is matched with it.",
        standards: &[
            "Personnummer, Folkbokföringslagen (1991:481) §18",
            "Luhn algorithm, ISO/IEC 7812-1 annex B",
        ],
        checks: &[
            "Luhn over the last ten digits, which is the number without its century, so the two \
             spellings of one number agree",
            "the leading digits are a day that could exist. The twelve-digit form carries its \
             century and gets a full calendar check; the ten-digit form is checked for a real \
             month and a day in range, and a day sixty past the month is a coordination number",
            "one of the words personnummer, samordningsnummer, personal identity, person number \
             or pnr appears within 48 bytes either side, in the candidate's own field. Ten digits \
             behind Luhn is a one-in-ten filter, and the word beside it is what makes the match \
             defensible; if it is ever dropped the rule goes with it",
            "nothing alphanumeric touches the match on either side",
        ],
        not_checked: &[
            "whether the number was issued, or to whom",
            "the date of birth and the sex the number encodes. The date is read only to reject a \
             number whose date could never have existed, and neither it nor the sex reaches the \
             value",
            "which century a ten-digit number belongs to. The separator says it (a plus sign \
             once the holder turns 100), and resolving it into a year needs the date the document \
             was written, which this service does not hold. The value therefore keeps the \
             separator instead of stripping it, which is the one place this scheme departs from \
             compact-form normalisation: two people born a hundred years apart write the same ten \
             digits and differ only in that sign",
        ],
        authorities: &[Authority {
            name: "Skatteverket",
            role: "runs the population register and assigns personal identity numbers",
            url: "https://www.skatteverket.se/privat/folkbokforing/personnummerochsamordningsnummer.4.3810a01c150939e893f18c29.html",
        }],
        ftm: FtmMapping {
            schema: "LegalEntity",
            property: "idNumber",
            note: "FollowTheMoney's LegalEntity schema defines idNumber for a government-issued identifier; which scheme it is comes from the value's parts rather than from a new property.",
        },
        references: &[Reference {
            title: "Personal identity number (Sweden)",
            url: "https://en.wikipedia.org/wiki/Personal_identity_number_(Sweden)",
            note: "the two spellings, the century separator and the coordination number",
        }],
    },
    RuleDoc {
        rule_id: "phone.international",
        entity_type: EntityType::Phone,
        title: "Telephone number, international form",
        matches: "A number written the way it would be dialled from another country, with a \
                  leading plus sign, or with the 00 prefix that stands for one. Punctuation is \
                  read as written: spaces, hyphens, dots and an area code in brackets all reach \
                  the same number. A number in national form is deliberately not matched, because \
                  the same digits name a different subscriber in every country and nothing in the \
                  text says which one is meant.",
        standards: &[
            "ITU-T E.164: The international public telecommunication numbering plan",
            "ITU-T E.123: Notation for national and international telephone numbers",
        ],
        checks: &[
            "the country calling code is one the ITU has assigned, and the national number matches \
             a pattern that country actually issues, both taken from Google's libphonenumber \
             metadata",
            "where no line type claims the digits but the region's own pattern still accepts them, \
             the number is reported at the lower confidence rather than dropped. That is where a \
             number written before a renumbering lands",
            "brackets open, hold digits and close, so a number is not assembled across two pieces \
             of text",
            "the span is not the page range and year of a citation, and not the leading half of a \
             timestamp whose minutes follow it",
            "nothing alphanumeric, no currency sign and no separator that continues the token \
             touches the match, so a plus-addressed mailbox or a longer code is not read as a \
             number; an extension marker is the one thing that may, and the span ends in front \
             of it",
        ],
        not_checked: &[
            "national-format numbers, which need a region the document does not supply; no default \
             region exists, because assuming one mislabels every document written elsewhere",
            "whether the number is assigned, in service, or belongs to whoever the text is about",
            "extensions, which are dropped rather than parsed. The span ends at the number itself",
            "vanity spellings such as 1-800-FLOWERS, and short codes, neither of which is \
             dialable from abroad",
        ],
        authorities: &[
            Authority {
                name: "International Telecommunication Union",
                role: "assigns country calling codes and publishes the E.164 numbering plan",
                url: "https://www.itu.int/en/ITU-T/inr/Pages/default.aspx",
            },
            Authority {
                name: "Google libphonenumber",
                role: "maintains the numbering metadata every check here rests on",
                url: "https://github.com/google/libphonenumber",
            },
        ],
        ftm: FtmMapping {
            schema: "Analyzable",
            property: "phoneMentioned",
            note: "The property FollowTheMoney defines for a number found in a document's text. \
                   LegalEntity.phone is the one to write when the number is known to belong to the \
                   entity, which is an assertion extraction cannot make on its own.",
        },
        references: &[
            Reference {
                title: "ITU-T Recommendation E.164",
                url: "https://www.itu.int/rec/T-REC-E.164",
                note: "the numbering plan the canonical form comes from",
            },
            Reference {
                title: "ITU list of country calling codes",
                url: "https://www.itu.int/pub/T-SP-E.164D",
                note: "which code belongs to which administration",
            },
        ],
    },
    RuleDoc {
        rule_id: "money.iso_code",
        entity_type: EntityType::Money,
        title: "Sum of money, ISO 4217 code",
        matches: "An amount written beside its three-letter currency code, such as EUR 1.234,56 \
                  or 1,234.56 USD. The code is the unambiguous way to write a currency, which makes \
                  this the high-precision half of the money facet.",
        standards: &[
            "ISO 4217: Codes for the representation of currencies",
            "Unicode CLDR supplemental currency data, for the minor units each code divides into",
        ],
        checks: &[
            "the code is in current use: a CLDR region entry with no end date and tender status, \
             which leaves out withdrawn codes and the non-tender metals and funds",
            "every thousands group is exactly three digits, whether it is grouped by a space or by \
             the apostrophe Switzerland writes, which is what rejects version strings, chapter \
             numbers and dotted reference numbers",
            "the fraction is no longer than the currency's own minor units, so a four-decimal \
             rate is not read as a price",
            "a code that is also an ordinary English capitalised word (ALL, TOP, CUP, TRY, PEN, \
             GEL, MOP, COP, MAD, BOB, SOS) additionally needs a word about money within 48 bytes",
            "nothing alphanumeric touches the match, and a dot, comma or hyphen beside it is read \
             as punctuation only when no digits follow it, so an amount may end a sentence or a \
             list item, while a separator with digits on the far side means the number continues \
             past the span",
        ],
        not_checked: &[
            "that the amount is correct, or that the transaction happened",
            "any arithmetic over the digits: a sum of money carries no check digit, so acceptance \
             rests on the amount's structure and the code's membership of the list",
            "the decimal convention where the number allows both readings: a single separator \
             followed by three digits is read as a thousands group and reported with the \
             separator-inferred flag",
            "currency names and national symbols spelled out in words, lei, złoty, kroner",
            "an amount whose separator is followed by a space and then more digits (1.837, 32), \
             which is one number in some documents and two in others: the span is refused rather \
             than truncated at the separator, because a wrong amount is worse than no amount",
        ],
        authorities: &[
            Authority {
                name: "International Organization for Standardization",
                role: "publishes ISO 4217 and maintains the code list",
                url: "https://www.iso.org/iso-4217-currency-codes.html",
            },
            Authority {
                name: "Unicode CLDR",
                role: "publishes the minor-unit digits and the symbols for each code",
                url: "https://cldr.unicode.org/",
            },
        ],
        ftm: FtmMapping {
            schema: "Value",
            property: "amount",
            note: "FollowTheMoney defines amount and currency on the abstract Value schema, which Payment and the other monetary schemas inherit; the code travels in the same value as the scaled integer, so both properties come from one match.",
        },
        references: &[Reference {
            title: "ISO 4217 currency codes",
            url: "https://www.iso.org/iso-4217-currency-codes.html",
            note: "the code list this rule tests membership of",
        }],
    },
    RuleDoc {
        rule_id: "money.symbol",
        entity_type: EntityType::Money,
        title: "Sum of money, currency symbol",
        matches: "An amount written beside a currency sign, such as €1.234,56, $1,200 or R$49,90. Most \
                  money in running text is written this way, and most currency signs are shared \
                  by several currencies.",
        standards: &[
            "ISO 4217: Codes for the representation of currencies",
            "Unicode CLDR currency display data, for the sign each code is written with",
        ],
        checks: &[
            "the sign is one CLDR publishes for a currency in current use, in either its standard \
             or its narrow form",
            "capitals in front of the sign are kept only where the pair is a symbol somebody \
             writes, such as A$, CN¥ and R$. Otherwise the span narrows to the sign alone",
            "an ISO 4217 code standing immediately in front of the sign settles which of the \
             sign's currencies is meant (NZD $100.70 is not United States dollars), and the code \
             has to be one that sign is actually written for",
            "every thousands group is exactly three digits, whether it is grouped by a space or by \
             the apostrophe Switzerland writes",
            "the fraction is no longer than the currency's own minor units; beside a sign it may \
             also stand alone, so the $.75 of a shelf label is seventy-five cents",
            "nothing alphanumeric touches the match, and a dot, comma or hyphen beside it is read \
             as punctuation only when no digits follow it, so an amount may end a sentence or a \
             list item, while a separator with digits on the far side means the number continues \
             past the span",
        ],
        not_checked: &[
            "which currency a shared sign means when no code stands beside it: $ is written for \
             twenty-nine currencies and £ for six, so the value names the most widely used of them \
             and carries the ambiguous-currency flag, which is the case that flag exists for",
            "the decimal convention where the number allows both readings, reported with the \
             separator-inferred flag",
            "currency names spelled out in words, and the letter-only symbols such as kr and zł",
            "an amount whose separator is followed by a space and then more digits ($ 8. 94), \
             which is one number in some documents and two in others: the span is refused rather \
             than truncated at the separator, because a wrong amount is worse than no amount",
        ],
        authorities: &[Authority {
            name: "Unicode CLDR",
            role: "publishes the currency signs and the minor-unit digits",
            url: "https://cldr.unicode.org/",
        }],
        ftm: FtmMapping {
            schema: "Value",
            property: "amount",
            note: "FollowTheMoney defines amount and currency on the abstract Value schema, which Payment and the other monetary schemas inherit; a symbol that resolves to more than one code sets the ambiguous-currency flag rather than picking silently.",
        },
        references: &[Reference {
            title: "CLDR currency display data",
            url: "https://github.com/unicode-org/cldr-json",
            note: "where the symbol table is transformed from",
        }],
    },
];
