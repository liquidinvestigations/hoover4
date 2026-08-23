# Architecture

Explanation: the shape of the system and the reasons behind it. Procedure lives in
[`../operations/`](../operations/Readme.md).

- `Pipeline_Stages.md`, P0–P6, what each stage consumes and produces
- `Storage_Model.md`, ClickHouse databases, Manticore shards, Garage buckets, deduplication
- `Search_Architecture.md`, the fan-out, the match builder, the caching boundary
- `Website_Backend.md`, sessions, database routing, error surfacing
- `Chat_And_Agents.md`, the chat turn, the agents behind it, citations and streaming
- `AI_Services.md`, the GPU tier and its CPU twins
