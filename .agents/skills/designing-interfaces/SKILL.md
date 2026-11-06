---
name: designing-interfaces
description: Design or review hoover4 interface layout, interaction, visual identity, and concise interface text.
---

# Design hoover4 interfaces

Use this procedure when changing visible controls, layout, loading behavior, or interface text.
Keep the requested product behavior and the existing visual identity.

## Preserve the visual identity

Hoover is a document investigation application with dense search results, document readers, tables, and administrative forms.
Keep document content and available actions prominent.
Use the existing light surfaces, dark navigation rail, restrained blue selection and links, and semantic status colors.
Use the shared Roboto typography and detail, body, section, and page roles.
Read [the shared tokens](../../../website/frontend/assets/main.css) before changing type, spacing, colors, or control dimensions.
Reuse [the frontend components](../../../website/frontend/src/components) and their established states.
Keep search cards for individual results. Group related fields through proximity before adding containers.
Avoid decorative cards, repeated badges, gradients, unrelated icons, and new font families.
Do not import a prototype framework or replace the application's design system for an isolated change.

## Keep text necessary

Add text when the person needs it to choose an action, understand a result, or recover from a failure.
Put implementation explanations in project documentation and design reasoning in the working plan.
Show a requirement through working behavior and state.
Do not add a sentence that announces that the requirement is met.

Remove these patterns from proposed interface text.

- Remove descriptions of backend mechanisms, caching, refresh behavior, or internal verification rules from ordinary controls.
- Remove captions that repeat a label, badge, selected scope, count, or page heading.
- Remove generic reassurance and explanations that defend a normal result.
- Remove decorative headings above headings, context strips, and repeated provenance lines.
- Remove unsupported estimates and implementation identifiers from ordinary labels.
- Remove parenthetical qualifications that do not change the person's immediate decision.

Keep one visible presentation of each fact where the person uses it.
Use a short field hint only when the label cannot communicate a necessary choice.
Place optional technical detail in an existing detail view or documentation.
Do not relocate unnecessary paragraphs into tooltips.
Keep errors actionable and specific. Preserve information required to understand destructive actions or unavailable capabilities.
Use the repository's terms and translation catalogs for visible text.

## Preserve interaction and identity

Keep display names and selected scope stable during background refresh and tab changes.
Retain resolved labels while an authorized refresh runs. Do not alternate them with internal identifiers.
Keep collection names, dataset names, and document titles distinct according to the view's contract.
Represent unavailable data with a bounded loading state or an actionable error.
Preserve entered values, focus, selection, and scroll position during unrelated refreshes.
Use native buttons for actions and links for navigation.
Provide visible keyboard focus, accessible names, and disabled, loading, selected, and error states where applicable.
Use text or an icon with status colors. Verify contrast and keyboard behavior for changed controls.
Avoid motion that shifts readable content or delays interaction. Respect reduced-motion preferences.

## Verify the changed view

Use [the browser procedure](../driving-the-browser/SKILL.md) for rendered behavior.
Exercise initial loading, refresh, focus changes, and navigation when they affect the change.
Use long names, translated labels, empty results, and errors where relevant.
Inspect the captured image and the action results.
Remove text or decoration that adds no information needed for the current task.
Report observed defects separately from proposed visual changes and untested accessibility behavior.
