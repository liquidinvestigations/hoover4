# Executor triage marker study

## Purpose

This reference backs the role selection rule in [`planning-work`](../SKILL.md#selecting-pass-roles).
It contains no prompt text, response text, source identity, session identifier, or project name.

## Sample and method

The corpus analysis read every normalized user record available across the five current
harnesses. It included 11 named projects and 153 records whose project field was null. The
analysis kept null projects in a separate bucket.

The analysis excluded 16 correction prompts from original-work populations. It defined high
friction as an unfinished final response or tool calls at or above the population p75. It used a
two-sided Fisher exact test and Benjamini-Hochberg adjustment across 105 available term tests.

| population | records | named projects | unknown-project records | p75 calls | high-friction records | high-friction rate |
|---|---:|---:|---:|---:|---:|---:|
| Original passes | 387 | 10 | 31 | 110 | 127 | 32.8 percent |
| Organizer sessions | 249 | 6 | 122 | 133 | 66 | 26.5 percent |
| All chat records | 636 | 11 | 153 | 115 | 195 | 30.7 percent |

The generator joined record and text files by checked position. It rejected unequal lengths and
different normalized keys. Its self-test covered duplicate keys, null projects, and negated final
states. A separate report comparison checked every generated aggregate table. Both checks exited
with status zero.

## Pass results used for selection

The study tested nine generic categories and 55 literal markers. `unattended` was the only pass
term with an adjusted q-value below 0.05. It matched 65 passes across four harnesses and two named
projects. Its high-friction rate was 64.6 percent, which was 38.2 percentage points above
unmatched passes. Its adjusted q-value was 0.00000053. Its cross-harness reproduction was limited,
with two higher directions and one lower direction among three eligible harnesses.

`unattended` describes execution mode. It does not describe task complexity. The association can
also reflect the selection of more complex work for unattended runs.

The acceptance and evidence category was the strongest task-related positive category. It
matched 56 passes across four harnesses and five named projects. Its friction rate was 42.9
percent, which was 11.8 percentage points above unmatched passes. Its risk ratio was 1.379 and its
reproduction was limited. No task-related literal term had an adjusted q-value below 0.05.

## Limits

Phrase matching misses concepts written with other words. It can match incidental wording. The
harness samples are not independent project samples. Several marker and harness combinations have
fewer than three matches. Association does not show causation.

The result supports a semantic checklist. It does not support a literal automatic trigger. An
organizer must name the concrete task relationship that justifies each point.
