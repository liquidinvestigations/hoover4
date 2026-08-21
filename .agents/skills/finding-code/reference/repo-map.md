# Which file answers which question

The skill-side index. The full directory map, with what each area holds, is
`docs/development/Repo_Map.md`.

| question | file |
|---|---|
| what the product is, and how to install it | root `Readme.md` |
| how a pipeline stage works | `main_services/processing/tasks/P<N>_*/Readme.md` |
| the schema and how migrations run | `main_services/processing/database/Readme.md` |
| which containers exist and what they expose | `main_services/ops/Readme.md` |
| what an MCP server does and how it is built | `main_services/agents/README.md`, then the per-server one |
| how the site is structured | `website/Readme.md`, then `docs/architecture/` |
| every configuration key and its consumer | `docs/operations/Configuration_Reference.md` |
| how a subsystem is shaped, and why | `docs/architecture/` |
| a procedure someone repeats | `docs/operations/`, `docs/development/` |
| what the product does, as agreed | `docs/technical-specification/` |
| how the agent configuration works | `docs/development/Working_With_Agents.md` |

## Reading a long one

Several of these run to tens of kilobytes. Get the outline first rather than paging:

```
.agents/skills/finding-code/scripts/doc-toc.sh website/Readme.md
```

Then read the one section. Any document here over about a hundred lines opens with its own
table of contents for the same reason.
