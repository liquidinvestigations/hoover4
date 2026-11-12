---
name: researching-known-problems
description: Search the web for reports of a specific failure in a mature product before you diagnose it alone. Use when a known product such as Nextcloud, OpenProject, PHP-FPM, Rails, PostgreSQL, Kubernetes, containerd, Kata Containers, gVisor or Cloud Hypervisor fails, stalls or behaves in an unexpected way.
allowed-tools: WebSearch, WebFetch, Bash, Read
---

# Researching known problems

A mature product has many users. Another person has often met the same failure and recorded the cause and the fix.
Search for that record before you spend time on your own diagnosis.

Do one or two quick searches when a specific product shows specific trouble.
Examples are an unexpected error text, a stall, a failed probe, a restore that loses state, or a start that is much slower than expected.

1. Copy the exact error text or the specific symptom. Add the product name and its version.
2. Search the issue tracker of the product and its code. Use `gh search issues` or `gh search code` when the project is on GitHub.
3. Search the forums and the question sites of the product. Examples are help.nextcloud.com, community.openproject.org, Stack Overflow, Server Fault, and the GitHub discussions of the project.
4. Search the operator guidance of the product for the area, such as scaling, hosting, or snapshot and restore.

Read the two or three most relevant results. Record the cause, the fix, and the version that the source names.
Check that the source matches your version and your environment before you apply a fix from it.
Note each source link beside the finding in the plan or report that records the problem.

Stop when a source explains the failure, or after a few searches find no match.
Continue with your own diagnosis when no source matches. Record that the searches found no match.

Use a research subagent for a wide question, such as how other teams operate a product at scale.
Give it a timebox and one report file. Keep the quick searches in this skill for a single specific failure.

Searches send text to an external service. Do not put credentials, private hostnames, addresses, or tenant data in a search query.
