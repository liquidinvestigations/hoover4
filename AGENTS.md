# hoover4

How to work in this repository. Everything else loads on demand: skills carry procedure,
rules load themselves beside the code they govern, and `docs/` explains how the system fits
together.

## Orientation

hoover4 ingests document collections through a Temporal pipeline (`P0`–`P6`) into
ClickHouse, Manticore and Garage, and serves them from a Dioxus website. `main_services/`
holds the pipeline, the MCP servers, the scanner service and the CPU model twins.
`ai_services/` is the standalone GPU tier. `website/` is backend, frontend and shared types.
`./deploy` starts and rebuilds all of it. `hoover4.ini` is the one source of configuration,
and the `.env` files are generated from it, so never hand-edit those. **This repository is
public**, at `github.com/liquidinvestigations/hoover4`, so every tracked file is published and
`docs/` with it. Keep every hostname, port, address and auth boundary out of them, and out of
these skills.
Those live in the gitignored `INFRASTRUCTURE_INVENTORY.md` at the repository root.
`CONTEXT.md` at the repository root records the words this tree uses in more than one sense,
and the words that compete for one sense. Read it before you write a term that already has an
entry there.

## How work happens here

Deliver the requested outcome with the simplest complete implementation. Preserve explicit requirements.
Reuse existing code when its contract fits. Add supporting work only when the requested outcome depends on it.
Record unrelated findings without implementing them. Stop adding work when the agreed acceptance checks pass.

- Run application tooling and stack checks in the appropriate containers. Inspect the actual environment before choosing commands.
- Read the documentation beside affected code and correct the contract made false by the change.
- Use scoped `rg` searches. Exclude build roots or name the relevant paths and extensions.
- Prefer context-aware edits or symbol tools when available. Verify mechanical edits and fail on stale matches.
- Ask about material product, scope, risk, and irreversible choices. Decide ordinary implementation details within accepted requirements.
- Preserve existing authorization across turns. A recommendation or unattended mode does not authorize an objective change.
- Use `plans/<n>-<slug>/` for multi-stage work. Keep one plan unless separate documents have a concrete use.
- Delegate only when authorized. Run subagents one at a time in the shared checkout and do not edit their owned paths.
- Select `organizer`, `executor-light`, `executor-heavy`, or `reviewer` by responsibility and risk. The harness supplies model and effort settings.
- Use explicit user budgets and actual session limits. Historical measurements do not impose task quotas or default call budgets.

## How to write

Write in **Simplified Technical English**: a controlled language, defined by **ASD-STE100**,
that allows one approved word per meaning, keeps an instruction to 20 words and a description
to 25, puts one instruction in a sentence, uses the active voice and simple tenses, and admits
no figures of speech. Meet the plain-language standard **ISO 24495-1**: a reader must be able
to find what they need, understand it, and act on it. Both are named because you know them.
Apply their vocabulary and their sentence rules.

This governs every Readme, docstring, comment, plan, report and reply in this repository, and
every word the product itself shows a person: interface copy, button and field labels, error
and status messages, entity explainer cards, tool descriptions, and what a script prints. Three
things keep their exact wording, because something else depends on the bytes. Code identifiers
and the format strings that build a log line. Text quoted from another system, such as a tool's
own output or an upstream error. A value a test compares against, until the test moves with it.

- **State the claim. Do not build to a turn of phrase.** If a sentence is arranged so its last
  few words land, rewrite it. Punchy is the failure, not the goal.
- **No metaphor where a plain word exists.** Never load-bearing, seam, blast radius, surface
  area, guardrail, tripwire, footgun, escape hatch, north star, moving parts, plumbing, glue
  code, happy path, sharp edge, quality gate, long pole, table stakes, paper cut, Chesterton's
  fence. Say what depends on what, and what breaks without it.
- **No borrowed feeling, and no borrowed enthusiasm.** A machine has no feelings. Never
  unfortunately, fortunately, luckily, thankfully, sadly, happily, tragically, hopefully,
  painful, painless, beautiful, elegant, lovely, awesome, nice, neat, slick, annoying,
  frustrating, tedious, brutal, savage, afraid, worried, scary, terrifying, crazy, insane,
  mad, lunatic, bonkers, loony. Never seamless, powerful, best practice, state of the art,
  cutting edge, world-class, best-in-class, industry-leading, unprecedented, groundbreaking,
  revolutionary, game-changer, paradigm shift, robust, comprehensive. Never delve, intricate,
  meticulous, pivotal, realm, landscape, showcase, leverage, utilize, foster, streamline,
  empower, testament, tapestry, embark, journey, deep dive, dive into. Never basically,
  essentially, arguably, interestingly, stuff, gotcha, tons of, bunch of, loads of, nuke,
  blow away, at the end of the day, let's. `underscore` bans the past and present participle
  only, and `novel` bans the adjective only, so the plural noun, the third-person verb, the
  character and the book stay legal. Never honest, honesty, honestly, lie, lies, lied, lying:
  a component has no intent to misrepresent. Say accurate, correct, verifiable or complete.
  Never magic, evil, smart, clever, aggressive, nasty, ugly, deserve, deserves: no component
  earns a judgement. `polite` is banned the same way, except Crossref's own term `polite
  pool`, which keeps its exact wording. A machine has no mind: never think, thinks, believe,
  believes, believed, feel, feels, felt. `thinking` and `thought` stay legal as the name of a
  model's own reasoning feature, the way `trust`, `graceful` and `lazy` stay legal as
  established technical terms.
- **No antithesis.** Never "X, not Y" as a closer, "this is not X, it is Y", "isn't just X,
  it's Y", or "X rather than Y" used for emphasis. Write what is true. If the false reading
  matters, correct it in its own sentence.
- **No emphasis particles and no preambles.** Never "full stop", "worth stating plainly",
  "worth noting", "to be clear", "the honest answer", "here's the thing", "make no mistake",
  "the whole point", "what matters is", "earns its keep", "does the work", "carries the
  argument", "crucially", "notably", "importantly", "fundamentally", "ultimately".
- **Complete sentences only.** A verbless sentence is a rhetorical device, so it is banned even
  when it reads well.
- **Punctuation carries no rhetoric.** No em dash anywhere. Use a comma, a full stop, or
  brackets. At most one colon in a paragraph, and only to introduce a list or a literal. No
  semicolon in prose.
- **One word per meaning.** Choose verify, or confirm, or check, and use that one word for that
  one act everywhere. Synonym variety makes a reader count events that never happened.
- **Write less.** No restatement of what the section just said, and no closing line that exists
  to land.
- **Do not narrate compliance with a rule.** Follow it. A sentence that tells the reader you
  have met a requirement is overhead, and it is usually written instead of meeting it. This
  covers "as instructed", "per your request", "as the rule requires", and naming a count of
  questions before writing them out.
- **This instruction decays.** Re-read this section before writing prose after a compaction.

Some vocabulary stays legal because it is the accurate technical term here. `harness` for the
screenshot harness and the Claude Code harness. `invariant`, `contract`, `idempotent`,
`barrier`, `heartbeat`, `lease`, `shard`, `fanout`, `denormalisation`, `sidecar` and the rest
of the domain nouns. `single source of truth` where it describes `hoover4.ini` or a table that
really is one. `latency ceiling` for a measured limit that adding workers does not move.
`fail loudly` and `fail silently` describing observable tool behaviour.
`rather than` when it genuinely compares two options. `not` in a plain correction of fact, for
example "matches by column name, not position".

`.agents/check-prose-style.py` reports the phrases and the em dashes, and a hook refuses an
edit that adds one.

## Invariants

- A commit message is one lowercase line under about 50 characters, without a body, trailer, or plan tag.
- Executors and reviewers run no Git write commands. The organizer stages reviewed owned paths explicitly.
- Commits, pushes, deployments, and external communication require authorization that covers the action.
- Tracked documentation describes current behavior. Keep working history and proposals in local plans.
- Tracked files never cite working plans. Preserve durable knowledge in the affected documentation.
- A claim needs evidence tied to the relevant code, input, and environment. Reuse captured evidence while those conditions remain valid.
- Run new checks when edits, failures, or uncertainty invalidate that evidence. Distinguish compilation, runtime, browser, and model-behavior claims.
- Ask material questions in full through the available asking tool. Continue independent work while an answer is pending.
- A new refusal or capability restriction needs the person's decision. Preserve conditions attached to existing authorization.
- The organizer may reorder or split implementation inside the accepted objective. Record material execution changes once in the plan.
- Adding, dropping, or changing a requested capability needs the person's decision, including during unattended work.
- Verify environment facts before relying on them. Do not treat documentation defaults as observed state.
- Change affected comments with the code they describe.
- Do not edit an applied migration, including comments. The runner verifies a checksum of the complete file.
- Use a new migration or change the reader unless the owner explicitly authorized resetting deployments that applied the migration.
- A capability change updates its row in `docs/technical-specification/` in the same patch.
- Preserve shared constants, storage identities, access checks, idempotency, and cancellation contracts when simplifying code.
- Keep plan tags inside their defining folder. Define each short tag in a Key table when using tags.
- Preserve local plan evidence when archiving. A gitignored folder may have no recoverable copy.

## Skills

Skills provide repository-specific procedures when relevant. Load only the procedure needed for the current task.
They live in `.agents/skills/<name>/SKILL.md`. `.claude/skills` links to that directory.
Rules in `.agents/rules/` apply beside the code they govern.

| Task | Relevant skill |
|---|---|
| Plan multi-stage work or prepare a handoff. | Use `planning-work`. |
| Delegate an authorized assignment. | Use `running-consecutive-subagents`. |
| Run explicitly unattended work. | Use `running-unattended`. |
| Review a diff. | Use `reviewing-changes`. |
| Select tests or verify a result. | Use `verifying-before-claiming`. |
| Update documentation or comments. | Use `writing-project-docs`. |
| Diagnose a runtime failure. | Use `debugging-the-stack`. |
| Deploy or restart an authorized service. | Use `deploying-the-stack`. |
| Verify a page or interaction. | Use `driving-the-browser`. |
| Inspect stored data. | Use `querying-the-datastores`. |
| Work on an authorized remote deployment. | Use `operating-remote-hosts`. |
| Improve measured pipeline performance. | Use `tuning-the-pipeline`. |
