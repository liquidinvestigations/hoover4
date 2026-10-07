---
name: planning-work
description: Plan multi-stage repository work, write implementation packages, or prepare a handoff. Use when the task needs shared decisions or spans sessions.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Planning work

Keep the full requested outcome. Choose the simplest implementation that satisfies its acceptance conditions.

Use `plans/<n>-<slug>/` for working documents. One plan can contain the request, scope, decisions, design, checks, and status.
Add separate documents when they have an independent reader or use. Put supporting artifacts beside their document.
Preserve the request and material answers. Distinguish a person's decision from an agent's recommendation.
A user's instruction to start this plan authorizes its explicitly requested actions, including resets.
Do not request another confirmation for those actions. Preserve their requested targets, scope, and reset allowance.
Agent-added steps do not expand that authorization.

Ask about material product, scope, risk, and irreversible choices that existing authorization does not settle.
Choose routine implementation details within the accepted scope. Continue independent work while a material answer is pending.
Unattended operation preserves the same objective and external-action permissions.

Group implementation by dependencies and verification. Estimate pass count and uncertainty when scheduling delegated work.
Do not enforce task counts, role quotas, historical call averages, or financial estimates.
Select `executor-light` for ordinary implementation and `executor-heavy` for changes whose risk needs that role.
Use `reviewer` for independent review and `organizer` for coordination and authorized Git writes.
The harness supplies model and effort settings. Delegation requires authorization and follows the shared-checkout rule.

A technical package identifies the outcome, owned paths, relevant interfaces, failure behavior, compatibility, and acceptance checks.
Link shared design and commands instead of copying them into each package.
Name proposed commands as proposed. Do not present a command that must be created as an existing check.
Use [the package template](reference/prompt-template.md) and [technical design guidance](reference/technical-pass-design.md) when useful.

The organizer can reorder or split work within the accepted objective. Record a material execution change once in the plan.
Adding, dropping, or changing a requested capability needs the person's decision.
Record unrelated findings without adding implementation passes.

Keep status sufficient to resume. Record completed work, remaining work, blockers, tested revision, and evidence paths.
A handoff adds the next action and current Git state. It need not create another report when the plan already contains those facts.
Finish when the accepted outcome is delivered and its checks pass. Report unresolved requirements accurately.

Working plans are local scratch. Tracked documentation states current behavior without citing scratch documents.
Use descriptive names. If short tags help, define them in the document's Key table and keep them within their plan folder.
The existing tag vocabulary uses W for work, G for scope, C for cuts, Q for questions, and D for decisions.

Archive only when asked or when closing the agreed work. Preserve the folder and any evidence needed to resume.
See [archiving](reference/archiving.md) and [optional estimation evidence](reference/estimating.md) for those operations.
