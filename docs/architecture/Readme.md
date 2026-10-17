# Architecture

Explanation: the shape of the system and the reasons behind it. Procedure lives in
[`../operations/`](../operations/Readme.md).

- [Pipeline_Stages.md](Pipeline_Stages.md), P0–P6, what each stage consumes and produces
- [Storage_Model.md](Storage_Model.md), ClickHouse databases, Manticore shards, Garage buckets, deduplication
- [Search_Architecture.md](Search_Architecture.md), the fan-out, the match builder, the caching boundary
- [Website_Backend.md](Website_Backend.md), sessions, database routing, error surfacing
- [Chat_And_Agents.md](Chat_And_Agents.md), the chat turn, the agents behind it, citations and streaming
- [Boards.md](Boards.md), investigation boards: the dispatcher, reasons, explores and board facts
- [AI_Services.md](AI_Services.md), the GPU tier and its CPU twins
- [Settled_Decisions.md](Settled_Decisions.md), choices that read as defects, and the reason each one stands

## The components have separate responsibilities.

Registered datasets supply source files. Temporal coordinates processing, and the website reads stored results.

```mermaid
flowchart LR
    accTitle: Hoover components and stored results
    accDescr: Temporal runs ingestion into ClickHouse, Garage and Manticore. Website and agent tools read results. Optional AI services support processing and chat.
    D[Registered datasets] --> P[Temporal processing workflows]
    P --> C[ClickHouse records and vectors]
    P --> G[Garage original and derived bytes]
    P --> M[Manticore search tables]
    W[Dioxus website] --> C
    W --> G
    W --> M
    W --> A[Research agents and typed tools]
    A --> W
    P --> AI[Configured AI services]
    A --> AI
```

[Service composition](../../main_services/ops/docker/docker-compose.yaml), [pipeline workflows](../../main_services/processing/tasks/Readme.md), and [agent services](../../main_services/agents/README.md) own these relationships.
Collection, preservation, and publication outside the application remain the investigation team's responsibility.
