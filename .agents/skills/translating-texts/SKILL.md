---
name: translating-texts
description: Change an English interface or agent text together with its translations, or rewrite the translations of one language.
---

# Translating texts

English is the source of every text that the website and the research agent show in another language.
Read [the text reference](reference/texts.md) for the files, what each text does, and the format rules.

A change to an English text changes the same text in all 21 other languages in the same patch.
An agent of the harness writes each translation directly in the file.
Do not send the texts to a translation service or to a model endpoint of the stack.
A message that a translation lacks shows in English, so a missing message is a defect.

Use the term list of the language in `scripts/i18n/glossary/<code>.json` and `agent-<code>.json`.
The term meanings are in `scripts/i18n/glossary.json`, `scripts/i18n/glossary_agent.json` and [CONTEXT.md](../../../CONTEXT.md).
Add a term to the list of the language when you choose a translation for a repeated term.

Run the text check for each changed language:

```
python3 scripts/i18n/check_translations.py <code> [<code> ...]
```

Correct every error. Read each warning and correct the text when the warning names a defect.
Then run the catalog tests that the reference names.

To rewrite all the texts of one language, give one agent one language.
Give it this skill, the reference, the English sources, and the files of its language.
It reads no other part of the repository, and it writes only the files of its language.
Run the language agents one after another in a shared checkout.

Native speakers have not reviewed the translations. Record a native review in the reference when one happens.
