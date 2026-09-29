---
name: querying-the-datastores
description: Verify stored data in ClickHouse, Manticore, or object storage with credential-safe repository helpers.
allowed-tools: Bash, Read, Grep, Glob
---

# Querying the datastores

Use the helpers so credentials come from the service environment.

```sh
.agents/skills/querying-the-datastores/scripts/ch.sh "SHOW DATABASES"
.agents/skills/querying-the-datastores/scripts/manticore.sh "SHOW TABLES"
.agents/skills/querying-the-datastores/scripts/garage.sh bucket list
```

Verify actual database and table names before querying a collection.
Use the stored bucket and object identity when reading a blob.
Keep derived output outside the disk scanner's input prefix.

Count the records that answer the question.
File rows establish scanning, text-page rows establish extraction, and search-engine rows establish indexing.
A writer's source code does not establish that its output exists.

Read [query procedures](reference/queries.md) for stage counts and document tracing.
Use the vectors daemon when inspecting vector tables.

ClickHouse result fields bind by column name.
Avoid aliases that shadow the source column used elsewhere in the query.
An aggregate over no matches still returns a row. Read its value.

The folder tree changes during ingestion and uses uncached reads.
Preserve the separate caching behavior for ordinary search.
