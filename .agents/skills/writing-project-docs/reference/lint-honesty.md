# Write descriptions that match their code.

A missing-documentation lint measures whether documentation exists.
It does not establish whether the description is correct or useful.

## Avoid repeated descriptions without a contract.

A generic description such as `Document public struct member` adds no information about a specific member.
Repeated generic descriptions can pass a presence check while leaving behavior unexplained.

## Describe constraints beyond the identifier.

A useful description can explain these properties:

- The value has a defined unit, such as bytes or milliseconds.
- The caller must preserve an invariant, such as a nonzero page number.
- The caller must hold a lock before changing the value.
- A repeated call can replace or remove earlier data.
- An absent value has a meaning that the type does not explain.

Read the implementation before selecting the description.
Leave an item undocumented when no additional contract needs explanation and the applicable lint permits that omission.
Report any remaining lint requirement that needs a repository decision.

## Verify lint findings against their purpose.

Rust `missing_docs` and Python documentation rules inspect documentation presence or structure.
`ERA001` identifies commented-out code.
Use the rule that addresses the observed defect.
A passing lint does not establish that documentation matches current behavior.
