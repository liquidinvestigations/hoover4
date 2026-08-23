---
name: rust-dioxus
description: Invariants that hold while editing the website's Rust.
paths: website/**/*.rs
---

# Editing the website's Rust

**Rust lives at `/usr/local/cargo/bin` inside the website container and is not on `$PATH`.**
Type-check there rather than waiting for a dev-server rebuild:

```
.agents/skills/verifying-before-claiming/scripts/cargo-check.sh
```

It includes the test targets. That matters: a plain `cargo check` does not build them, so a
signature change updated everywhere in `src/` leaves the check green while the test binaries
no longer compile. The tests do not fail. They are never built.

**A conditional hook traps the WebAssembly runtime** on the render that adds it, leaving the
page painted and completely inert. A type check cannot see it and a release build reports only
an `unreachable` trap with no site named. `dx check --package frontend` names the site:

```
.agents/skills/verifying-before-claiming/scripts/dx-check.sh
```

**A `key:` must be unique among its siblings, and a humanized value is not.** Keying chart
axis ticks by their formatted label gives every tick on an all-zero axis the same key. A
release build silently misdiffs; a debug build panics on the first re-diff and the page dies.
Key by index or by the raw value, never by display text.

**`dioxus-html` has no SVG `title` element.** A `title` inside an `svg` is created with
`createElement` and yields an HTML title element instead, so the tooltip never renders in
either navigation mode. Use a different tooltip mechanism rather than assuming the markup
worked.

**`rsx!` string interpolation takes an expression, not a block.** `style: "…{if x {a} else
{b}}"` fails to parse with an error naming an identifier or expression. Resolve the
conditional into a `let` above the `rsx!` and interpolate the variable.

**Server functions are not multi-threaded.** A blocking library called from one panics, and
spawning a task does not escape it. Move blocking work to the runtime that can take it.

**A result row binds by column name.** An alias shadows the column it derives from, and an
aggregate returns a row even over an empty match, so "there is a row" is not "there is
data".

**Every full-text match argument goes through the shared builder.** Assembling one in a call
site is how an escaping rule ends up implemented twice.

**A storage id from a tool payload is a lookup key, never a capability.** Resolve it to its
owner and enforce owner-or-admin. Someone else's id is a **403**, not a 404: collapsing the
two hides a real permission failure behind an apparent missing row.

**A bucket comes out of the row's stored path**, never from this process's configuration.

Before reporting a change done, run the type check above and read its output, and run
`.agents/skills/reviewing-changes/scripts/check-diff-comments.sh` over the diff.
