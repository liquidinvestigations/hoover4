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

- **Everything runs in containers.** The host has almost no tooling. Run python, servers and
  every stack command inside the right container with `docker exec`. Inspect the
  infrastructure before you start, rather than assuming which container owns a job.
- **Read the `Readme.md` beside the code before you change it, and correct it as you go.**
  Fix what your change makes untrue, and leave the rest alone. Keep documentation patches as
  small as the code patch that prompted them.
- **Sub-agents run one at a time**, waited on, self-timeboxed, each with a hand-written work
  package. Do not run a swarm, do not fan out in parallel, and do not use a sub-agent to
  avoid thinking.
- **Verify with the stack.** Do not verify from memory. This system's errors routinely name
  the wrong half of the problem, so confirm what a process actually received before you edit
  the file that an error points at.

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
  blow away, at the end of the day, let's. `underscore` bans the verb only, and `novel` bans
  the adjective only, so the character and the book stay legal.
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

- **A commit message is one lowercase line under ~50 characters.** No body, no trailers, and
  no explanation anywhere in git. `git log --oneline` is a table of contents, and a changelog
  does not belong there.
- **Documentation and comments state what is true now.** No dates, no history of the work,
  nothing aspirational, and never a reference to `plans/`, which is local scratch that gets
  wiped. Keep the lesson, drop the anecdote.
- **Never search recursively without scoping it.** `grep` here is ugrep and does not skip
  `website/target`. Name the extensions or exclude the build roots. A search that has not
  returned within seconds is wrong. Stop it and scope it.
- **Evidence before claims.** Never say something builds, passes, or is fixed unless you ran
  the check in this turn and read its output. Say which you fixed, the cause or the symptom.
- **Anything you need from a person is asked, in full, where you say you need it.** Never
  name a count, such as "three things", "a few decisions" or "some open questions", and then
  leave the content somewhere else. A request that cannot be acted on from where it is
  written has not been made. The reader now knows they owe an answer, and does not know what
  it is. Either write the questions out, or link to the exact section that holds them. This
  applies hardest at the end of a long reply, where a summary tends to compress them away.
- **An assumption written into a deliverable is a question that was not asked.** A person's
  answer often creates the next decision, and that decision belongs in the round that is
  still open. Naming the assumption in a report does not settle it, because the report is
  read after the work it governs was written. Before you close a round, read what you are
  about to write and ask about every value you chose that a person could have chosen. Say
  the frontier is empty only after that read. Ask with the asking tool, and never in the
  closing prose of a reply. A question at the end of a message defers its answer by a whole
  turn, and by then the work it governs is written.
- **A fact about the environment is checked before it is written into a mechanism.**
  Repository visibility, a host's owner, a path's tracked status, and a remote's name are all
  one command away. A default stated in someone's documentation is what a system assumes, and
  never what is true here. Assert it only after running the check, and name the check beside
  the assertion.
- **A new refusal is a decision a person takes.** This covers a hook, a permission rule, a
  turn limit, and every other mechanism that stops an action the agent could take before.
  Write it as a question. It lands after a person answers. Three rules bound what may be
  proposed at all. A repeated instruction becomes evidence only after it is counted in both
  directions across the whole history, with both counts shown. A rule that carries "unless",
  "yet" or "for this task" keeps that condition, and no mechanism may remove it. Text the
  agent wrote, in a handoff, a report or a plan, is never a person asking for something. That
  holds when a person pastes it back into the conversation.
- **The organizer does not change the scope of a plan on its own.** Adding an item, dropping
  an item, or re-scoping one, in either direction, needs a grilling round first. The answer
  goes into the plan folder's answers file, and from there into the plan document it changes.
  A scope change that reaches a work package with no answer behind it is a defect in the plan.
  The pass that implemented it is not at fault.
- **Reach for the Edit/Write tools or serena's symbol operations first** when changing code.
  `sed -i` cannot fail loudly on a stale match. It silently changes nothing, while Edit
  refuses and tells you. Bash editing stays available for the cases where it is genuinely
  the practical tool. The rule is about which one you try first.
- **Change the comment in the same patch that changes what it describes.** A stale comment
  outlives the code it lied about. **An already-applied migration is the exception, because
  editing one is a breaking change, comments included.** The runner records an md5 of the
  whole file, so correcting a stale word in one makes it refuse to start on every deployment
  that already ran it. Ordinary work therefore does not touch `db_global_migrations/` or
  `db_collection_migrations/`, and the fix belongs in a new numbered file or beside the code
  that reads the table. Editing one is a decision the repository owner takes, and it comes
  with resetting every deployment that applied it. When that decision is taken, the register
  applies to those files like any other.
- **A change that adds, removes or re-scopes a capability edits its row in
  `docs/technical-specification/` in the same patch**, never in a follow-up. A capability
  with no row was never agreed. A row with no code is false. Read the affected rows before
  you change the feature.

- **A plan costs work in passes, never in developer days.** A pass is one sub-agent
  invocation, and its cost comes from a measured reference class. Nothing here has ever been
  measured in developer days, and no estimate in that unit has ever been checked against an
  outcome. Every plan that schedules work carries an estimate table, and the final report
  restates it with an actuals column. That column stops the next estimate being copied from
  the last guess. **The pass count is the number to get right.** An estimate that costs ten
  passes correctly and needed one is wrong by ten. Items that share one procedure, one check
  and one context are one pass, and a plan with more than three passes states in one line what
  forced each split. `planning-work` carries the method.
- **A plan carries the text of every item it schedules.** An item taken from a standing list,
  a defect list or an archived folder is copied into the plan. The copy carries its date and a
  link back to the source. Those sources are rewritten on their own
  schedule and can be deleted, so a link on its own is a promise the plan cannot keep. **Copy
  across a folder boundary, and link inside one**, because two copies of one sentence in one
  folder drift apart with nobody noticing. `planning-work` carries the method.
- **A short tag never leaves the plan folder that defined it.** Inside one plan folder,
  letter-and-number tags for a scope item, a decision, a question or a cut are free and
  useful, because they let a scope table and a result table line up. Outside that folder
  they are unreadable, so refer to another pass's item by naming it and linking to it. A
  bare tag in `docs/`, in `.agents/`, or in a `Readme.md` beside code is always wrong.
- **A document that uses tags opens with a `## Key` table** that gives every tag it
  mentions, what the tag is, and a link to where it is defined. Expand each tag at its first
  mention in the body. After that the bare tag is fine, in the way an acronym works. A
  document whose references cannot be resolved without opening another file has not been
  written yet. `.agents/check-doc-ids.py` enforces both rules and names every unresolvable
  tag.

Hooks refuse an unscoped recursive search, a long or multi-line `git commit -m`, and an edit
that adds a banned phrase or an em dash. The rest hold because you hold them. All of these
are re-injected after every compaction.

## Skills

Skills live in `.agents/skills/<name>/SKILL.md`. `.claude/skills` symlinks to that
directory. If your harness does not follow symlinks, read that literal path and load the
skill yourself. Rules in `.agents/rules/` load on their own when you open a file they cover.

| when you are about to | invoke |
|---|---|
| find a symbol, a caller, a config key, or a section of a long Readme | `finding-code` |
| change code, rename something, apply one edit across files | `editing-code` |
| write a test, fix a bug, or find out what a change endangers | `writing-tests` |
| say it works, is fixed, or passes (build, test, check, browser pass) | `verifying-before-claiming` |
| start or archive an epic, write a prompt/report pair, fan out artefacts | `planning-work` |
| hand work to a sub-agent | `running-consecutive-subagents` |
| run out of room, pause unfinished work, or hand a job to a fresh session | `writing-handoffs` |
| write or fix a `Readme.md`, a docstring, or a comment | `writing-project-docs` |
| review a diff before committing | `reviewing-changes` |
| deploy, rebuild, reset, or wait on a long job | `deploying-the-stack` |
| chase a hang, a connection failure, an OOM, an empty result | `debugging-the-stack` |
| make ingestion or search faster, or tune Temporal | `tuning-the-pipeline` |
| query ClickHouse, Manticore or Garage | `querying-the-datastores` |
| work on the demo box or the GPU box | `operating-remote-hosts` |
| take a screenshot or click through the UI | `driving-the-browser` |

## Settled, so stop re-deciding it

- **In demo mode an anonymous guest is an administrator, writes included.** That is deliberate
  for the MVP and its small, known audience. Do not report it as a defect and do not narrow it
  without being asked.
