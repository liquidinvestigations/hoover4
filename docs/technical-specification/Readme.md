# Technical specification

What the product does, stated once, in the present tense. Three things live here:

- `Features.md`, every capability the product offers, one row each, with the code that owns
  it.
- `interface/`, one page per screen the product serves, listing the controls that screen
  carries, the states it can be in, and the constraints that govern them.
- The configuration surface is **not** duplicated here. Every setting and its consumer is
  `../operations/Configuration_Reference.md`; this tree links to it and the drift check
  covers it.

This is the specification, not the design. `../architecture/` explains *how* the system is
built and why; this tree states *what it does*, which is the thing a change is allowed to
alter only on purpose.

## The depth rule

One test, applied while writing:

> **Specify what a user can ask for, not what the screen looks like.**
> A control belongs here if removing it would change what a user can do. Layout, wording,
> colour, ordering, iconography and spacing belong to the code, which is a better record of
> them than prose ever is.

Three consequences worth stating, because each is a trap:

- **A control gets one row.** Its identifier, what it does, and (only if there is one) the
  constraint that is not obvious from the name. A control needing a paragraph is a control
  whose *behaviour* belongs in `../architecture/`, with a link from its row.
- **Sentinel values, invariants and refusals are the valuable part.** "Sort defaults to
  Relevance" is worth less than "Relevance is not a valid order with an empty query and
  resolves to newest-first". The second is what a change can silently break.
- **A page file stays under roughly 200 lines.** Past that the split is by route, never by
  section: one file may hold several routes that share a shell, never half a route.

## Identifiers

| thing | identifier | where it comes from |
|---|---|---|
| page | `UI-<RouteVariant>`, `UI-SearchPage`, `UI-AdminCollectionProcessingPage` | the variant name in the frontend's route enum, character for character |
| control | `<page id>.<slug>`, `UI-SearchPage.sort` | assigned here; lowercase, dotted, stable across renames of the visible label |
| feature | `F-<area>-<nn>`, `F-search-07` | assigned in `Features.md`, never reused after removal |

Page identifiers are deliberately not invented: they are the route variant, so a page that
is added, renamed or deleted in the code is mechanically visible against this tree. Control
and feature identifiers are assigned here and are **not** referenced back from source. That
is a considered trade: back-references buy a grep from code to spec, and cost a rename
churn in two languages plus a second place for every identifier to be wrong. The joins that
matter are made on names that already exist in the code: route variants, setting keys, and
the enums that back a control's options.

## Keeping it true

The specification is part of the change, not a report about it. A change that adds, removes
or re-scopes a capability edits the row that describes it, in the same patch that changes
the code. A capability that is agreed and not yet built has no row: this tree describes what
exists.

Two mechanisms hold it:

- `website/tools/check-spec-drift.sh` compares this tree against the code on three joins.
  Page identifiers against the route enum, setting keys against the settings the code reads,
  and enum-backed control options against their enums. It reports; it does not gate.
- The control tables in `interface/` are the walk-list for browser acceptance. A control
  that is listed and cannot be exercised is either a specification that has gone stale or a
  control that has stopped working, and both are findings. This is the mechanism that
  catches what no text comparison can: a control that still exists and does nothing.
