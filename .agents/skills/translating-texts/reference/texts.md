# The translated texts

The supported codes are `de`, `es`, `fr`, `pl`, `pt`, `ar`, `he`, `hi`, `zh`, `it`, `nl`, `da`, `nb`, `sv`, `el`, `hr`, `ro`, `ru`, `ja`, `ko` and `tr`.
`pt` is Portuguese of Portugal. `zh` is Simplified Chinese. `nb` is Norwegian Bokmål, so use no Nynorsk forms. `hr` is Croatian, so use no Serbian forms.

## Files of one language

| Text | English source | Translation |
|---|---|---|
| Website interface | `website/frontend/i18n/en/*.ftl` | `website/frontend/i18n/<code>/*.ftl` |
| Worker notes | `main_services/processing/tasks/P_agent/i18n/en/notes.ftl` | `main_services/processing/tasks/P_agent/i18n/<code>/notes.ftl` |
| Agent system prompt | `research_agent/prompts/agent.md.j2` | `research_agent/prompts/<code>/agent.md.j2` |
| Agent role lines | `ROLE_LINES` in `research_agent/prompts/__init__.py` | `research_agent/prompts/<code>/role_lines.json` |
| Agent skills | `research_agent/skills/*.md.j2` and `skills/partials/*.j2` | `research_agent/skills/<code>/` with the same names |
| Agent tool texts | `research_agent/tool_texts/en.json` | `research_agent/tool_texts/<code>.json` |
| Term lists | `scripts/i18n/glossary.json` and `glossary_agent.json` | `scripts/i18n/glossary/<code>.json` and `agent-<code>.json` |

`research_agent/` is `main_services/agents/research_agent/research_agent/`.

## The website interface

The website shows each message of the catalogs. A person reads it on the page.
The message id names the component and then the English words. For example, `file-browser-` messages are on the file browser page, `chat-composer-` messages are in the chat input box, and `admin-` messages are on the administration pages.

| Catalog | Pages |
|---|---|
| `main.ftl` | The language settings page and the navigation rail. |
| `search.ftl` | The search page: the result cards, the filters, the facets and the folder tree. |
| `document.ftl` | The document viewer: the preview tabs, the text, table, archive and PDF views, and the document locations. |
| `storage.ftl` | The file browser and the uploads pages. |
| `chat.ftl` | AI Chat and the investigation boards. |
| `admin.ftl` | The administration pages: collections, datasets, operations, processing updates, errors, users, groups, models and settings. |
| `shared.ftl` | Text that the server and the shared Rust code return in English. The page finds the English message that matches the text and shows its translation. |

Use the usual register of software interfaces in the language, and use one form of address in all catalogs.
Translate a button or a menu item as a short command or a noun, as the platforms of the language do.
Keep a status value short, because it shows in a table cell or a badge.

## The worker notes

The worker adds a note to a running chat turn when the model must change what it does, for example after searches that found nothing new.
The model reads the note as an instruction, and the transcript shows it to the person.
Some messages are the text of a turn that the worker ends. The person reads them.
Write the notes as direct instructions to the model, in the form of address that the agent prompt of the language uses.

## The agent texts

The research agent is the model that answers in AI Chat and does the explores of the boards.
It reads these texts in the agent language of the run. It writes its answer in the language that the system prompt names.

- `agent.md.j2` is the system prompt. It gives the role, the answer language, the list of skills and tools, and the work rules.
- The role lines are the first lines of the system prompt. Each profile has one.
- A skill is a method text. The prompt lists the name and the `description` of each skill. The model reads the body with `read_skill` when it needs the method. Skill search matches the `description`, `terms` and `not_for` headers, so `terms` lists the words that a person of the language uses for the subject. Keep the English words of `terms` that people also use, such as `Excel` or `CSV`.
- A partial is a part of a skill that two skills include.
- A tool text is the description of a tool or of a tool argument. The model reads it in the tool definitions. The key is the English text. The value is the translation.

Address the model in the second person, with one form of address in all agent texts and notes of the language.
Keep the meaning, the order and the strength of each rule. Do not add a rule, an example or an explanation.

## Text that stays as it is

- Message ids, Fluent variables `{ $name }`, and the keys of every JSON file.
- Jinja statements `{% ... %}`, expressions `{{ ... }}` and their order. The text between them changes.
- Tool names, argument names, enum values, skill names, citation handles, file names, paths and URLs.
- Inline code spans in backticks. A word inside backticks is a name that the code reads.
- The `name`, `group` and `tools` headers of a skill.
- The keys in a fenced JSON example. A value in the example can change when it is prose, for example a goal text.
- Product names (Hoover, Hoover4), format names (PDF, CSV, JSON), and the terms that the term list marks with `keep`.
- Jinja comments `{# ... #}` are not text for the model. A translation can omit them.
- A string literal inside a Jinja expression is text for the model when the template prints it, for example `else 'A tool'`. Translate it.
- A quoted phrase that the model writes in its answer, such as "not found in the documents", is translated. No code matches it.
- `{{ citation_artefact }}` prints the English word `report` in every profile. Write the word of the language for the report in its place, with the correct grammar, and omit the variable.

## Fluent rules

- Keep each message on its id. Indent each continuation line.
- `{" "}` is a space that must stay at the start or the end of the message. Keep it.
- Some messages are parts of one sentence. The page puts a link, a value or a name between them in the English order. Translate each part so that the sentence reads correctly in that order.
- A selector `{ $count -> [one] ... *[other] ... }` selects a plural form. Use the CLDR cardinal categories of the language, and keep the default variant `*[other]`. Chinese, Japanese and Korean have only `other`, so a translation can drop a selector that only selects the plural.
- A selector on a named value, such as `{ $state -> [running] ... }`, keeps the variant keys of English.
- A variable named `$if_<name>_1_else_s` holds the English plural ending, `""` or `"s"`. The count variable beside it is a number. Select the plural on the count, and keep the ending variable in a selector that prints nothing. Chinese, Japanese and Korean can omit it. The variant starts on a new line, as in every Fluent selector:

  ```
  { $if_retries_len_1_else_s ->
     *[other] {""}
  }
  ```

- `$direction` is `above` or `below`. A selector on it keeps those two keys and gives the word of the language for each.
- `$tool` is the name of a tool, such as `search_collections`. `$label` and `$kind` are text that the page already translated.
- A variable named `$if_<name>_1_tr_chat_transcript_...` holds the word "call" or "calls" from the messages `chat-transcript-call` and `chat-transcript-calls` of the same language. Place it where that word belongs.
- The worker notes allow only plain text, `{ $name }` variables and `{"..."}` literals. Do not add a selector there.
- Keep the first comment line of each translated catalog: `# Translation of en/<file>. Change it together with the English catalog.`

## Punctuation

The repository edit hook refuses an em dash (U+2014) in a `.j2` file. Use a comma, a colon, brackets or a full stop in the agent templates.

## Checks

| Check | Command |
|---|---|
| Ids, variables, selectors, Jinja tags, skill headers and tool text keys | `python3 scripts/i18n/check_translations.py <code>` |
| Website catalogs parse and keep the English variables | `cargo test --offline -p frontend --lib i18n` in `hoover4-website`, with `/usr/local/cargo/bin` on `PATH` and `/app` as the folder |
| Worker notes stay in the subset | [pytest-unit.sh](../../verifying-before-claiming/scripts/pytest-unit.sh) `tests/unit/test_agent_notes.py` |
| Agent texts load | [pytest-research-agent.sh](../../verifying-before-claiming/scripts/pytest-research-agent.sh) `tests/test_localization.py` |
