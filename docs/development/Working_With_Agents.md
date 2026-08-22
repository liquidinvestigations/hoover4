# Working with agents on hoover4

Every coding agent that opens this repo is configured by the same set of files. This page is
the human-facing map of that set: what loads when, what each piece is for, how to add one,
and how to tell whether it fired.

## Contents

- [The loading ladder](#the-loading-ladder)
- [The layout](#the-layout)
- [Skills](#skills)
- [Path-scoped rules](#path-scoped-rules)
- [Hooks](#hooks)
- [MCP servers](#mcp-servers)
- [Harness compatibility](#harness-compatibility)
- [Editing discipline is a setting, not a virtue](#editing-discipline-is-a-setting-not-a-virtue)
- [Adding a skill, a rule or a hook](#adding-a-skill-a-rule-or-a-hook)
- [Knowing that it fired](#knowing-that-it-fired)
- [Publication and privacy](#publication-and-privacy)

## The loading ladder

Four rungs, cheapest first. The whole design is an argument about which rung a given piece
of knowledge belongs on.

| rung | what it is | when it loads | cost |
|---|---|---|---|
| the core | `AGENTS.md` at the repo root | every session, every turn | paid always — keep it near 60 lines |
| a skill | `.agents/skills/<name>/SKILL.md` | when the agent's task matches its `description` | paid only in matching sessions |
| a reference file | `reference/*.md` beside a skill | when the skill body sends the agent to it | paid only inside that procedure |
| a rule | `.agents/rules/<name>.md` with a `paths:` glob | when a matching file is opened | paid only while editing that kind of file |

Two consequences that decide most placement questions. A paragraph that is relevant in most
sessions but applies *one paragraph at a time* is a skill with reference files, not core
text. And **rules do not re-inject after a context compaction** — sessions here routinely
reach half a million tokens — so anything that must survive compaction belongs in the core
or in the `SessionStart` hook's `compact` path.

## The layout

`.agents/` is the single source of truth. Everything under `.claude/` is a symlink into it,
so no file is authored twice.

```
.agents/
  skills/<name>/SKILL.md        + reference/ and scripts/ beside it
  rules/<name>.md               paths:-gated
  hooks/*.py|*.sh               real executables, run from here by absolute path
  harnesses/                    reference config per harness, copied out by bootstrap.sh
  bootstrap.sh                  wires the per-harness adapters
  verify-wiring.sh              proves the wiring, in well under a minute
.claude/skills    -> ../.agents/skills          directory symlink
.claude/rules     -> ../.agents/rules           directory symlink
.claude/settings.json                           declares the hooks by their .agents/ path
AGENTS.md                                       the shared root instruction file
CLAUDE.md                                       one line: @AGENTS.md
```

The hooks are **not** symlinked into `.claude/`: the settings file names them at their
`.agents/hooks/` path directly, which is one fewer thing to be broken.

`bootstrap.sh` is idempotent, dry-runs by default, and prints `ok` / `MISSING` / `RELINK` /
`CONFLICT` per item. It also re-applies the executable bit on every hook, because a hook that
lost its mode bit fails silently — the harness reports it exactly as it reports no hook at
all.

**Editing `.claude/settings.json` is a person's job, not an agent's.** A coding agent is
prevented from changing its own harness configuration, which is the correct boundary: the
file declares which commands run on every tool call. `.agents/harnesses/claude-settings.json`
holds what the file should contain; merge it by hand and restart the session.
`verify-wiring.sh` reports whether it is in place.

Directory symlinks do not work on Windows. That is why the core also names the literal
skills path in prose: a harness that cannot follow the symlink still learns where the skills
are and can read them as ordinary files.

## Skills

A skill is a procedure the agent loads on demand. Thirteen exist, in three groups.

| skill | it answers |
|---|---|
| `planning-work` | how work is planned, staged and archived in this repo |
| `running-consecutive-subagents` | one sub-agent at a time, waited on, self-timeboxed, with a written work package |
| `verifying-before-claiming` | which evidence backs which claim, and how to wait on a long job without disturbing it |
| `writing-project-docs` | present-tense truth, small patches, honest doc comments |
| `reviewing-changes` | what a review of *this* repo checks |
| `finding-code` | locate before reading: symbol overview, references, implementations |
| `editing-code` | the edit tools and symbol operations instead of stream editors |
| `deploying-the-stack` | `./deploy`, its flags, and why `up -d` is not a deployment |
| `debugging-the-stack` | mechanism-not-wording, reproduce inside the container, the silent-failure traps |
| `tuning-the-pipeline` | Temporal concurrency, `gather` barriers, the heartbeat-as-slot-lease effect |
| `querying-the-datastores` | the recurring ClickHouse, Manticore and Garage diagnostics |
| `operating-remote-hosts` | the demo box and the GPU box — see [Remote hosts](../operations/Remote_Hosts.md) |
| `driving-the-browser` | the browser MCP surface, screenshots, typing into a Dioxus input |

The `description` field is the whole trigger mechanism: a skill that does not describe the
*situation* in the words a request uses does not load, and nothing downstream recovers from
that. Write descriptions in the second person, naming the symptom and the request phrasing.

Skill scripts are referenced by repo-relative path first and by the harness variable second,
because only one harness substitutes that variable and the others run the literal string:

> Run `.agents/skills/verifying-before-claiming/scripts/cargo-check.sh` from the repo root.
> (Where `${CLAUDE_SKILL_DIR}` is substituted, `${CLAUDE_SKILL_DIR}/scripts/cargo-check.sh`
> is the same file.)

**Every recurring incantation ships as an executable, never as a quoted command.** This is
the one design decision measured rather than assumed: a command that the always-loaded
instruction file documented in full was still retyped 143 times across 11 sessions. Prose
does not stop rediscovery; a path that can be run does.

## Path-scoped rules

Five rules, each an invariant that applies while a kind of file is open rather than a
procedure to follow.

| rule | applies to | carries |
|---|---|---|
| `rust-dioxus.md` | `website/**/*.rs` | where Rust lives in the container, the conditional-hook trap, `rsx!` interpolation, server functions not being multi-threaded, the result-reading traps |
| `frontend-ui.md` | `website/frontend/**` | no emoji and the icon crate, uncached structure queries, props not being reactive, every state being a URL, surfacing a failed call |
| `pipeline-python.md` | `main_services/processing/**/*.py` | the stage names and the mirrored constants, the text-page and extractor-key writer contracts, the two silent wire formats, timeout units |
| `migrations.md` | migration SQL | the `;`-splitting runner's three failure modes, what a header may and may not say, enum and replacing-table reading |
| `agents-mcp.md` | `main_services/agents/**` | the vendored package and its build context, one web-search tool, ids as lookup keys, undrained subprocess pipes |

**Rules are the one rung whose loading is not verified here.** Whether a given harness
resolves a symlinked rules directory the way it resolves a symlinked skills directory is
assumed by symmetry and untested. Each rule body therefore reads correctly as an ordinary
file, and nothing depends on the rule firing automatically.

## Hooks

Three, and deliberately no more. Each is stated in the core as well, so the agent knows the
rule instead of only hitting the wall.

| hook | event | what it denies |
|---|---|---|
| unscoped recursive search | `PreToolUse(Bash)` | a recursive `grep`/`ugrep` over `.` or a build-bearing directory with no `--include`/`--exclude-dir`. A scoped search at one small directory passes |
| long commit message | `PreToolUse(Bash)` | `git commit -m` with a multi-line or over-length message |
| orientation | `SessionStart`, including `compact` | denies nothing; injects the invariants and the routing table, and re-injects them after a compaction |

Three things are deliberately *not* hooked: reads of `website/target`, `node_modules` and
generated output, because debugging regularly needs exactly that source; heredocs, because
most of that signal is legitimate throwaway analysis; and prose matching words like
"previously", because those strings appear legitimately in code and documentation and a hook
on them damages the agent's work.

## MCP servers

Four servers, all streamable HTTP on loopback, ports from `hoover4.ini`:
`hoover4-web-search`, `hoover4-browser`, `hoover4-whois`, and `serena` for symbol-level
navigation and editing.

`hoover4-mcp-collections` and `hoover4-mcp-todo` are deliberately absent from the host-side
configuration: their tools require a header only the chat tier can supply — the permitted
collections for one, the chat session for the other — so an entry would be a server whose
every tool denies.

**The symbol server runs over streamable HTTP, and the reason is a failure mode worth
knowing.**
The older SSE transport carries the session in a held GET; when that stream dies — a
container restart, a redeploy, a dropped connection — the client reconnects, gets a new
server-side session, and never repeats the handshake on it, so every later call fails for
the life of the session. The signature is a harness error reading `Invalid request
parameters` while the container log reads `Received request before initialization was
complete`: the harness names the arguments, the server names the session, and only the
server is describing the actual mechanism. Streamable HTTP carries the session in a header
and requires a client told `404` to re-handshake, so a redeploy costs one failed call rather
than the session.

A tool that fails on first use teaches the agent not to reach for it, and no description
rewrite recovers from that. Transport health is therefore part of the configuration, not an
operational detail.

## Harness compatibility

| harness | instructions | skills | rules | MCP | hooks |
|---|---|---|---|---|---|
| Claude Code | `CLAUDE.md` → `@AGENTS.md`, imports expanded | `.claude/skills` symlink — verified working | `.claude/rules` symlink | `.mcp.json` | the three above |
| OpenAI Codex CLI | `AGENTS.md`, no import expansion | unverified | unverified | `[mcp_servers.NAME]` with the experimental client flag; stdio and streamable HTTP only | shape unverified, unused |
| opencode | `AGENTS.md` | native `.agents/skills/<name>/SKILL.md`; unknown frontmatter keys ignored | unverified | `opencode.json` remote entries | unverified |
| Gemini CLI | `GEMINI.md` | none | none | `.gemini/settings.json`, `httpUrl` | none |
| Cursor | `.cursor/rules/*.mdc`, generated from the shared rules | unverified | `.mdc` with `globs:` | `.cursor/mcp.json` | none |
| Kimi CLI | unverified | unverified | unverified | unverified | unverified |
| Google Antigravity | unverified | unverified | unverified | unverified | unverified |

Rows marked unverified are exactly that: nobody has run them here. Treat them as work to do,
not as support to rely on.

`allowed-tools` in skill frontmatter is one harness's spelling and is ignored by the others,
so the skills carry it and no per-harness transform exists. A transform would be a second
copy that drifts.

## Editing discipline is a setting, not a virtue

The policy is that code is read with the read and symbol tools and changed with the edit and
write tools, not with `sed`, `cat` or heredocs. The reason to state the mechanism plainly:
some harness modes carry a built-in instruction telling the agent to prefer shell reads and
stream edits, and where that mode is on it *overrides* a politely worded preference. If an
agent is paging files with `sed -n` in this repo, check the harness mode before rewriting
any instruction text — the setting is the cause and the prose is not.

Heredocs remain legitimate for throwaway analysis that writes nothing into the repo.

## Adding a skill, a rule or a hook

1. **Decide the rung.** Always relevant → the core. A procedure → a skill. A detail inside a
   procedure → a reference file beside that skill. An invariant tied to a file kind → a rule.
   If it can only be enforced mechanically and denying it is safe → a hook, and only after
   the same content exists as prose.
2. **Write it in `.agents/`**, never in `.claude/`.
3. **For a skill**, spend the effort on the `description`. Take three real past requests and
   check the skill loads without being named; a description that under-triggers is the
   single most common failure.
4. **For a hook**, write the deny message so it names the allowed form, and confirm the
   permissive case still passes before shipping it.
5. **Run `bootstrap.sh`** and then `verify-wiring.sh`.

## Knowing that it fired

- A skill that loaded appears in the session as its body text; if the agent restates a
  procedure in its own words instead, the skill did not load and the `description` is why.
- A hook that fired denies the tool call with its own message. Silence from the commit hook
  is the expected steady state — it guards a behaviour that stopped recurring.
- A rule that loaded shows up when a matching file is opened, not at session start.
- `verify-wiring.sh` checks the symlinks, the executable bits, the settings entries and the
  MCP endpoints in one run.

## Publication and privacy

**All of this is tracked and public**: `.agents/`, the two `.claude/` symlinks,
`.claude/settings.json`, `AGENTS.md` and `CLAUDE.md`. Git is the backup, and a fresh
checkout has the whole configuration already — `bootstrap.sh` only creates the machine-local
per-harness adapters on top of it.

Deliberately not tracked: `.claude/settings.local.json`, `CLAUDE.local.md`, `hoover4.ini`,
and `INFRASTRUCTURE_INVENTORY.md`.

Because they are public, **skills and rules carry the same secrecy rule as `docs/`**: no
hostname, no address, no port that identifies a real host, no credential, no description of
an authentication boundary. `operating-remote-hosts` describes the *shape* of the work on
each machine and points at `INFRASTRUCTURE_INVENTORY.md` for the specifics.

The ignore rules that make this work are worth knowing before editing either file. The
`AGENTS.md`, `CLAUDE.md` and `plans/` rules in the root `.gitignore` are **unanchored**, so
they match at any depth; the root copies are re-admitted by an explicit negation. That is
deliberate: a service's own `AGENTS.md` deeper in the tree is its author's scratch and is
free to cite the scratch folder, which the tracked tree forbids.
