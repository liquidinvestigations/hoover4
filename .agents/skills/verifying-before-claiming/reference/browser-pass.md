# What a UI claim needs

A claim about the interface needs the interface. `cargo check` passing says nothing about
whether a page renders, and a Dioxus build that fails leaves the site returning 500 rather
than an obviously broken page.

Minimum for "the UI change works":

1. Load the page through the browser tooling (`driving-the-browser`).
2. Take an accessibility snapshot or a screenshot showing the changed element.
3. Exercise the interaction the change is about — the click, the filter, the submit.
4. Check the browser console for errors introduced by the change.

Screenshots that support a claim belong beside the document that makes it, in the fan-out
folder described by `planning-work`.
