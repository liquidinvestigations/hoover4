# Read current capability contracts.

[The feature register](Features.md) lists implemented capabilities, stable identifiers, and source owners.
[Detailed contracts](Capability_Contracts.md) retain limits and behavior for longer register entries.
[The interface inventory](interface/Readme.md) maps routes to controls, states, and constraints.
[The configuration reference](../operations/Configuration_Reference.md) identifies settings and their consumers.
[Architecture](../architecture/Readme.md) explains component relationships.

## Specify behavior that a user or caller can observe.

Give each control one row with its identifier, behavior, and relevant constraint.
Link detailed storage and execution contracts from that row.
State sentinel values, limits, failure behavior, and defaults when they change a caller's result.
For example, Relevance always uses descending score order, including when a legacy URL requests ascending order.
Group routes in one interface document when they share controls and states.

## Preserve stable identifiers.

| Object | Identifier | Source |
|---|---|---|
| Page | `UI-<RouteVariant>` | The frontend route variant supplies the name. |
| Control | `<page id>.<slug>` | The specification assigns a stable control identifier. |
| Feature | `F-<area>-<nn>` | The feature register assigns the identifier and does not reuse removed identifiers. |

Source code does not need back-references to specification identifiers.
Use route variants, setting keys, and enum values to compare the specification with code.

## Update contracts with behavior.

A capability change updates its register row in the same patch.
The register describes current implementation.
Keep proposals and execution history in local working records.
[The drift check](../../website/tools/check-spec-drift.sh) compares routes, settings, and selected enum-backed controls.
[Documentation checks](../../scripts/docs/README.md) verify links, feature coverage, route coverage, and screenshot provenance.
Browser procedures verify that listed controls produce their documented effects.
Compilation and text comparisons do not establish those effects.
