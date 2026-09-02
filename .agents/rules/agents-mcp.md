---
name: agents-mcp
description: Invariants that hold while editing the MCP servers and research agents.
paths: main_services/agents/**
---

# Editing the MCP servers and agents

**The shared package is vendored into the server images.** `agent_common/` is copied in at
build time, so those services' build context is `main_services/agents`, not their own
directory. A build that "cannot find the module" is almost always a context that was narrowed
to the service directory.

**There is one web-search tool, deliberately.** The metasearch server owns every open-web
source behind a single tool. Do not add a second "search the web" tool: choosing between
overlapping search tools is something a small model does badly, and that is exactly why they
are merged. New sources go inside the existing tool.

**A storage id in a tool payload is a lookup key, never a capability.** It reaches the backend
through a payload a model wrote. Every read resolves it to its owner and enforces
owner-or-admin; someone else's id is a **403**, not a 404, because collapsing the two hides a
real permission failure behind an apparent missing row.

**Derived bytes live under a prefix the disk-scan stage must never walk.** The end-to-end
verification asserts that no blob row references it. Anything a tool captures goes there.

**A tool's description is its entire trigger mechanism.** Describe the situation in the words
a request actually uses. A tool that is never selected is indistinguishable from a tool that
does not exist, and no amount of implementation quality recovers from it.

## Subprocesses

**A child process on an undrained pipe wedges, and it looks like a hang in your code.** A
browser in a container writes a continuous stream of errors to stderr; on a pipe nobody
reads, that pipe fills and the child blocks on write. Every subprocess launch needs its
output either drained by a task or sent to the null device.

**Before believing a "cannot connect to the browser" error, prove the thing you are
connecting to exists.** A library given an explicit host and port may treat that as *attach
to something already running* and silently skip launching anything. Its error then blames
your privileges. Ask the endpoint for its version from inside the container. In this area an
error message routinely names the wrong half of the problem.

**Connect-loop budgets are short and browser start-up is not.** A browser with extensions
takes several seconds to be ready; a client that allows less than that reports a connection
failure for a browser that is still starting.

## Timeouts

The HTTP client's timeout is in **seconds**. Use a `(connect, read)` two-tuple so a dead host
is detected in seconds while real work still gets minutes.

Before reporting a change done, run the server's own tests and
`.agents/skills/reviewing-changes/scripts/check-diff-comments.sh` over the diff.
