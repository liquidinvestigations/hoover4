# FollowTheMoney mapping

[FollowTheMoney](https://followthemoney.tech/) is the schema an investigative consumer of this
service already has: people, companies, documents, bank accounts, vessels, and the properties that
hang off them. A span this scanner produces is only useful once it lands somewhere in that model, so
every rule names the schema and property its extraction feeds, and the mapping travels with the rule
rather than living in the code of a consumer.

The mapping is a field on every catalogue entry (`FtmMapping` in `src/explain/catalog.rs`) and is
served on `GET /rules/{rule_id}` beside everything else known about the rule. A rule without one
fails the test suite.

## Three things the mapping does not do

- **It is not an export format.** This service returns entities, not FollowTheMoney objects. The
  mapping says where a value belongs; assembling the object, deciding which concrete schema to build
  and deduplicating against what is already there are the consumer's job, because only the consumer
  knows what the document is about.
- **It does not promise a subject.** `LegalEntity.idNumber` says an identity number was found in the
  text. It does not say whose, and nothing in a fragment of text can.
- **It does not resolve.** A match is a mention. Whether two mentions are the same account, vessel
  or person is entity resolution, which happens downstream with far more context than a span.

## Abstract parents are named deliberately

Where a property is defined on an abstract parent, the mapping names the parent: `amount` and
`currency` on `Value`, `idNumber`, `vatCode`, `leiCode` and `phone` on `LegalEntity`. That is where
FollowTheMoney defines them, and every concrete schema a consumer builds (`Company`, `Person`,
`Payment`) inherits them. Naming `Company.leiCode` would be picking one of the inheritors for the
consumer, on evidence that does not support the choice.

## The `res:` extension namespace

FollowTheMoney does not model everything this scanner finds. There is no schema for an intermodal
container, no property for an IMEI, a MAC address, an autonomous system number, a DOI, an ORCID or a
CVE identifier. Where that is the case, the property is declared under a `res:` prefix. A local
extension of their schema, marked as ours.

The prefix is what makes the two cases distinguishable. A consumer reading `BankAccount.iban` knows exactly what to do with
it. A consumer reading `Analyzable.res:imeiMentioned` knows it has to decide where the value goes,
and knows the decision is theirs rather than something FollowTheMoney already settled. An extension
that is written down is a mapping somebody can implement; an unmarked invented property name is a
surprise that looks like an upstream one.

The extensions follow the shape of the properties they sit beside. `Analyzable` already carries
`ibanMentioned`, `ipMentioned`, `emailMentioned` and `phoneMentioned` for things found in a
document's text, so a mention this scanner adds is named the same way.

## The table

| Entity type | Rule | FollowTheMoney | Why |
|---|---|---|---|
| `date` | `date.iso8601` | `Analyzable.res:dateMentioned` | `Document.date` is the date a document carries as its own. A date inside its text is a different claim and has no property. |
| `date` | `date.rfc2822` | `Analyzable.res:dateMentioned` | As above. |
| `date` | `date.clf` | `Analyzable.res:dateMentioned` | As above. |
| `date` | `date.iso_week` | `Analyzable.res:dateMentioned` | As above. |
| `email` | `email.basic` | `Analyzable.emailMentioned` | Defined upstream, for exactly this: an address found in text. |
| `bank_account` | `bank.iban` | `BankAccount.iban` | Defined upstream. `Analyzable.ibanMentioned` is the same value seen from the document's side, and a consumer building an account entity wants the account property. |
| `bank_account` | `bank.bic` | `BankAccount.bic` | Defined upstream. |
| `bank_account` | `bank.payment_card` | `BankAccount.res:cardNumber` | `BankAccount` has `accountNumber`, `iban` and `bic` and no property for a card. Not `accountNumber`: a card is an instrument presented against an account, and merging the two pollutes the join a consumer builds on `accountNumber`. |
| `bank_account` | `bank.aba_routing` | `BankAccount.res:routingNumber` | `bic` names the institution internationally and nothing covers the domestic clearing number that says the same thing in the United States. |
| `company_id` | `company.lei` | `LegalEntity.leiCode` | Defined upstream on the abstract parent, inherited by `Company` and `Organization`. |
| `company_id` | `company.vat_eu` | `LegalEntity.vatCode` | Defined upstream on the same abstract parent, so a company, an organisation or a public body all carry it on one property. |
| `company_id` | `company.vat_non_eu` | `LegalEntity.vatCode` | The same property: FollowTheMoney does not scope `vatCode` to the Union, so every jurisdiction lands on one property. |
| `company_id` | `company.se_organisationsnummer` | `LegalEntity.registrationNumber` | Defined upstream on the abstract parent, for the number a company register knows an entity by, and inherited by `Company`, `Organization` and `PublicBody`, the same set of legal forms the number's leading digit distinguishes. |
| `security` | `security.isin` | `Security.isin` | Defined upstream. |
| `security` | `security.cusip` | `Security.res:cusip` | `Security` has `isin`, `ticker` and `figiCode` but no CUSIP property, and a North American security is routinely identified by nothing else. |
| `security` | `security.sedol` | `Security.res:sedol` | The same gap for the London Stock Exchange's own code. |
| `vessel` | `vessel.imo` | `Vessel.imoNumber` | Defined upstream. |
| `vessel` | `vessel.mmsi` | `Vessel.mmsi` | Defined upstream. |
| `cargo_container` | `container.iso6346` | `Analyzable.res:containerMentioned` | FollowTheMoney has no schema for an intermodal container and no property for its number. |
| `device` | `device.imei` | `Analyzable.res:imeiMentioned` | FollowTheMoney models no devices at all. |
| `device` | `device.mac` | `Analyzable.res:macAddressMentioned` | `ipMentioned` exists; nothing covers a hardware address. |
| `network` | `network.ip` | `Analyzable.ipMentioned` | Defined upstream. `UserAccount.ipAddress` is the address an account was used from, which a bare span cannot claim. |
| `network` | `network.asn` | `Analyzable.res:asnMentioned` | `ipMentioned` exists; nothing covers an autonomous system. |
| `vulnerability` | `vulnerability.cve` | `Analyzable.res:vulnerabilityMentioned` | FollowTheMoney models people, companies and documents. A CVE identifier is none of those. |
| `publication` | `publication.doi` | `Analyzable.res:doiMentioned` | `Document` has no DOI property. |
| `publication` | `publication.orcid` | `Analyzable.res:orcidMentioned` | `Person` has no ORCID property. |
| `phone` | `phone.international` | `Analyzable.phoneMentioned` | Defined upstream, for a number found in a document's text. `LegalEntity.phone` is the property to write once the number is known to belong to the entity, which is an assertion a span cannot make. |
| `money` | `money.iso_code` | `Value.amount` | Defined upstream on the abstract parent, alongside `Value.currency`, and inherited by `Payment`. One match supplies both: the scaled integer and the ISO 4217 code travel in the same value. |
| `money` | `money.symbol` | `Value.amount` | As above. Where the symbol names more than one currency the code is the most widely used of them, and the ambiguous-currency flag says so, a consumer that cannot tolerate that should threshold on the flag rather than on the amount. |
| `message_id` | `message.rfc5322` | `Document.messageId` | Defined upstream, and the rule only fires behind a mail header name, which is the same context the property assumes. |
| `coordinates` | `coord.decimal` | `Address.latitude` | Defined upstream. One match supplies both `latitude` and `longitude`; the mapping names a single property, so it names the first. |
| `coordinates` | `coord.dms` | `Address.latitude` | As above. |
| `coordinates` | `coord.plus_code` | `Address.latitude` | As above. A Plus Code is decoded to the centre of its cell, so it feeds the same pair of properties. |
| `crypto_wallet` | `crypto.ethereum` | `CryptoWallet.publicKey` | Defined upstream. |
| `crypto_wallet` | `crypto.bitcoin` | `CryptoWallet.publicKey` | Defined upstream. |
| `national_id` | `natid.it_codice_fiscale` | `LegalEntity.idNumber` | Defined upstream on the abstract parent. The rule detects and validates the number and decodes nothing out of it, so the mapping carries the number and no personal attribute. |
| `national_id` | `natid.es_nif_nie` | `LegalEntity.idNumber` | As above. |
| `national_id` | `natid.mx_curp` | `LegalEntity.idNumber` | As above. |
| `national_id` | `natid.in_pan` | `LegalEntity.idNumber` | As above. |
| `national_id` | `natid.pl_pesel` | `LegalEntity.idNumber` | As above. The number encodes a birth date, which the validator reads only to reject an impossible one; no property receives it. |
| `national_id` | `natid.se_personnummer` | `LegalEntity.idNumber` | As above. |

## Money is two properties from one match

`Value` defines `amount` and `currency` separately and a money match supplies both, the same shape
the coordinate rules have. The mapping names `amount`; the code is in the value beside the scaled
integer and the exponent, and setting the amount without the currency produces a number nobody can
interpret.

## The coordinate pair

`Address` defines `latitude` and `longitude` as separate properties, and a coordinate match supplies
both at once. `FtmMapping.property` holds one name, so the coordinate rules name `latitude` and say
in their note that `longitude` comes from the same match. A consumer setting one without the other
has half a position, which is worse than none; the value's `latitude` and `longitude` fields are
both there in the entity.
