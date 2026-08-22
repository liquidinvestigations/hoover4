# hoover4

How to work in this repository. Everything else loads on demand: skills carry procedure,
rules load themselves beside the code they govern, and `docs/` explains how the system fits
together.

## Orientation

hoover4 ingests document collections through a Temporal pipeline (`P0`–`P6`) into
ClickHouse, Manticore and Garage, and serves them from a Dioxus website. `main_services/`
holds the pipeline, the MCP servers, the scanner service and the CPU model twins;
`ai_services/` is the standalone GPU tier; `website/` is backend, frontend and shared types.
`./deploy` starts and rebuilds all of it, and `hoover4.ini` is the one source of
configuration — the `.env` files are generated from it, so never hand-edit those. `docs/` is
public: keep every hostname, port, address and auth boundary out of it, and out of these
skills. Those live in the gitignored `INFRASTRUCTURE_INVENTORY.md` at the repository root.

## How work happens here

- **Everything runs in containers.** The host has almost no tooling: run python, servers and
  every stack command inside the right container with `docker exec`. Inspect the
  infrastructure before you start rather than assuming which container owns a job.
- **Git runs on the host, and you do not push.** Commit to the working branch and leave it
  there unless you are told otherwise.
- **Read the `Readme.md` beside the code before you change it, and correct it as you go.**
  Fix what your change makes untrue; leave the rest alone. Keep documentation patches as
  small as the code patch that prompted them.
- **Sub-agents run one at a time**, waited on, self-timeboxed, each with a hand-written work
  package. Never a swarm, never parallel fan-out, and never a sub-agent to avoid thinking.
- **Verify with the stack, not from memory.** This system's errors routinely name the wrong
  half of the problem, so confirm what a process actually received before editing the file
  an error points at.

## Invariants

- **A commit message is one lowercase line under ~50 characters** — no body, no trailers, no
  explanation anywhere in git. `git log --oneline` is a table of contents, not a changelog.
- **Documentation and comments state what is true now** — no dates, no history of the work,
  nothing aspirational, and never a reference to `plans/`, which is local scratch that gets
  wiped. Keep the lesson, drop the anecdote.
- **Never search recursively without scoping it.** `grep` here is ugrep and does not skip
  `website/target`; name the extensions or exclude the build roots. A search that has not
  returned within seconds is wrong, not slow.
- **Evidence before claims.** Never say something builds, passes, or is fixed unless you ran
  the check in this turn and read its output. Say which you fixed — the cause or the symptom.
- **Anything you need from a person is asked, in full, where you say you need it.** Never
  name a count — "three things", "a few decisions", "some open questions" — and leave the
  content somewhere else. A request that cannot be acted on from where it is written has not
  been made: the reader now knows they owe an answer and not what it is. Either write the
  questions out, or link to the exact section holding them. This applies hardest at the end
  of a long reply, which is precisely where a summary tends to compress them away.
- **Reach for the Edit/Write tools or serena's symbol operations first** when changing code.
  `sed -i` cannot fail loudly on a stale match — it silently changes nothing — while Edit
  refuses and tells you. Bash editing stays available for the cases where it is genuinely
  the practical tool; the point is which one you try first.
- **Change the comment in the same patch that changes what it describes.** A stale comment
  outlives the code it lied about.
- **A change that adds, removes or re-scopes a capability edits its row in
  `docs/technical-specification/` in the same patch** — never in a follow-up. A capability
  with no row was never agreed; a row with no code is a lie. Read the affected rows before
  you change the feature.

- **A short tag never leaves the plan folder that defined it.** Inside one plan folder,
  letter-and-number tags — a scope item, a decision, a question, a cut — are free and
  useful: they are what lets a scope table and a result table line up. Outside it they are
  unreadable, so referring to another pass's item means naming it and linking to it, and a
  bare tag in `docs/`, in `.agents/`, or in a `Readme.md` beside code is always wrong.
- **A document that uses tags opens with a `## Key` table** — every tag it mentions, what
  it is, and a link to where it is defined — and expands each one at its first mention in
  the body. After that the bare tag is fine, exactly as an acronym works. A document whose
  references cannot be resolved without opening another file has not been written yet.
  `.agents/check-doc-ids.py` enforces both rules and names every unresolvable tag.

An unscoped recursive search and a long or multi-line `git commit -m` are refused by hooks;
the rest hold because you hold them. All of these are re-injected after every compaction.

## Skills

Skills live in `.agents/skills/<name>/SKILL.md`. `.claude/skills` symlinks to that
directory; if your harness does not follow symlinks, read that literal path and load the
skill yourself. Rules in `.agents/rules/` load on their own when you open a file they cover.

| when you are about to | invoke |
|---|---|
| find a symbol, a caller, a config key, or a section of a long Readme | `finding-code` |
| change code, rename something, apply one edit across files | `editing-code` |
| say it works, is fixed, or passes — build, test, check, browser pass | `verifying-before-claiming` |
| start or archive an epic, write a prompt/report pair, fan out artefacts | `planning-work` |
| hand work to a sub-agent | `running-consecutive-subagents` |
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
