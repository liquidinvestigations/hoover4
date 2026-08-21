---
name: frontend-ui
description: Interface conventions that hold while editing the frontend.
paths: website/frontend/**
---

# Frontend conventions

**No emoji, anywhere in the interface.** Every glyph comes from the icon crate, so it scales,
inherits colour, and renders identically on every platform. The families in use are listed in
`website/frontend/Cargo.toml`; a family that is not enabled produces a compile error naming
only the icon, which reads like a typo rather than a missing dependency — check the feature
list before assuming the name is wrong.

**Structure queries never go through the search cache.** The collection's tree changes while
ingestion runs, and a stale tree is worse than a slow one, so it uses the uncached primitive
deliberately. Ordinary search must keep using the caching primitive: that cache is what keeps
repeated facet fan-outs off the search engine.

**Props are not reactive.** Only a signal read *inside* a resource hook re-runs it; passing a
changed value down as a prop does not. A `key:` on a lone child does nothing.

**A hook behind a condition traps the runtime.** See the Rust rule for the check that names
the site.

**Every state a user can reach is a URL.** Query, filters, sort, page, selection and viewer
arrangement all live in the address, so any state is a link that can be sent. Fields added to
an encoded parameter later must decode from an older link by taking their default, so an old
bookmark keeps working rather than shifting every value after the missing one.

**Surface a failed server call on the page.** A failure that collapses into an empty result
list is indistinguishable from a query that matched nothing, and the two need different
reactions from the user.

**Say which number you are showing.** The total match count and the reachable page range are
deliberately different numbers here; wherever a user meets both, the page states the
difference rather than implying the rest are reachable.

## Before you claim it renders

A type check does not see any of this. Load the page:

```
website/take-screenshots.sh --only <page>
```

and read the snapshot beside the image, not only the image. `driving-the-browser` covers the
rest, including the two input traps that make typing into this frontend silently do nothing.

## If you add, remove or re-scope a control

Edit its row in `docs/technical-specification/interface/` in the **same patch**. A control
with no row was never agreed; a row with no control is a lie. Layout, wording, colour and
ordering are not specified there — only what a user can ask for.
