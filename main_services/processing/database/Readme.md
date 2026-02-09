# Database Access, Definitions, and Migrations

This directory centralizes database utilities and schema definitions used by the processing pipeline.

## Contents

- `clickhouse_migrations/` - SQL migrations for ClickHouse schemas (datasets, VFS tables, parsed content, metadata, and processing state).
- `clickhouse.py` - ClickHouse client configuration and migration runner.
- `manticore.py` - Manticore index maintenance and search configuration utilities.
- `minio.py` - MinIO client helpers and bucket initialization.
- `milvus_example.py` - Example integration pattern for Milvus vector storage.

## Navigation

-  [Go Back](../Readme.md)