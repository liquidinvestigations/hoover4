# What a UI claim needs

A claim about the interface needs the interface. `cargo check` passing says nothing about
whether a page renders, and a Dioxus build that fails leaves the site returning 500 rather
than a visibly broken page.

Minimum for "the UI change works":

1. Load the page through the browser tooling (`driving-the-browser`).
2. Take an accessibility snapshot or a screenshot showing the changed element.
3. Exercise the interaction the change is about, such as the click, the filter or the
   submit.
4. Check the browser console for errors introduced by the change.

Preserve raw browser evidence in the local plan.
Publish reviewed documentation screenshots with their public provenance through the screenshot procedure.
