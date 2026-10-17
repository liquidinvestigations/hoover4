# Hoover4 processes and searches document collections.

Hoover4 is a self-hosted document processing and investigation application from [Liquid Investigations](https://liquid-investigations.org/index.html).
It ingests registered filesystem datasets, extracts content, and serves search, document reading, chat, and investigation boards.
It is the successor to [hoover-search](https://github.com/liquidinvestigations/hoover-search).

## Read the documentation for your task.

- [The user manual](docs/user-manual/User_Manual.md) explains search, filters, document sources, folders, chat, and boards.
- [Architecture](docs/architecture/Readme.md) explains components, processing, identities, and request flows.
- [Operations](docs/operations/Readme.md) explains deployment, configuration, diagnostics, and maintenance.
- [Development](docs/development/Readme.md) explains code ownership and verification.
- [The feature register](docs/technical-specification/Features.md) identifies current capabilities and their source owners.

## The components have separate responsibilities.

| Component | Responsibility |
|---|---|
| [Main services](main_services/Readme.md) | Temporal workflows, parsing services, CPU model services, agents, and datastore management. |
| [ClickHouse storage](main_services/processing/database/Readme.md) | Collection data, metadata, extracted content, durable vectors, and global application records. |
| [Manticore indexing](docs/architecture/Search_Architecture.md) | Sharded full-text search, facets, and disposable vector tables. |
| [Garage object storage](main_services/ops/docker/garage/Readme.md) | Original bytes and derived document or chat artifacts. |
| [AI services](ai_services/README.md) | Optional GPU embeddings, reranking, NER, OCR, and self-hosted model servers. |
| [Website](website/Readme.md) | Dioxus Rust backend and WebAssembly frontend for users and administrators. |

[The architecture diagram](docs/architecture/Readme.md#the-components-have-separate-responsibilities) shows these relationships.

## Ingest supported document formats.

The [processing pipeline](main_services/processing/Readme.md) runs stages P0 through P6.
It scans paths, deduplicates bytes, computes plans, parses files, extracts entities, creates vectors when enabled, and indexes search data.
Archives and email attachments create member documents that pass through the pipeline.

Readers support archives, email, PDF, images, text, spreadsheets, delimited text, audio, video, and formats handled by Tika.
Supported extraction varies by format and configured service.
[Parser documentation](main_services/processing/tasks/P3_parse_files/Readme.md) identifies the implemented readers.

Content hashes identify deduplicated bytes.
Dataset and content hash identify a searchable document.
A collection groups datasets and defines document access.
A dataset belongs to its collection permanently.
[The storage model](docs/architecture/Storage_Model.md) explains these identities.

Dataset ingestion starts from registered directories available to the worker.
The repository does not establish general wiki, team-chat, or remote database ingestion connectors.
Collection export and restore transfer stored collection data for recovery.
They do not define a general reporting export format.
[Administrative workflows](main_services/processing/tasks/P_admin/Readme.md) describe supported maintenance operations.

## Select model capabilities through configuration.

The main services can run without a GPU.
Tesseract provides CPU OCR, and an enabled spaCy service provides CPU NER.
OCR engines retain separate source identities.
GPU NER can use a configured spaCy fallback after a connection failure.
Embeddings and reranking have no CPU fallback.
An empty embedding endpoint skips chunking and embedding.

Chat uses the configured provider and model catalog.
The optional local servers support separate models for agent turns and structured or summary work.
[AI architecture](docs/architecture/AI_Services.md) explains provider selection and disabled capabilities.
[Provider configuration](docs/operations/Configuration_Reference.md) defines the accepted configuration keys.

## Install and configure the application.

Use a supported container runtime and Compose implementation.
GPU services also require compatible NVIDIA drivers and the configured GPU runtime.
Resource requirements depend on document content, stored data, enabled models, and concurrency.
Measure the intended workload before selecting hardware.

Copy one public configuration template to the local configuration file.

```sh
cp hoover4.ini.release hoover4.ini
$EDITOR hoover4.ini
./deploy
```

[The development template](hoover4.ini.development) enables development tooling.
[The release template](hoover4.ini.release) describes release configuration.
The local `hoover4.ini` is the single source of truth.
Deployment generates environment files, which must not be edited by hand.
Store credential file paths in configuration and credential values in files outside the checkout.
Keep deployment addresses and access details in the gitignored `INFRASTRUCTURE_INVENTORY.md`.

[The deployment procedure](docs/operations/Deploying.md) explains builds, service selection, and verification.
[The configuration reference](docs/operations/Configuration_Reference.md) links each setting to its consumer.
[Development checks](docs/quality-assurance/Running_Checks.md) describe container-based verification.

## Read the license.

Hoover4 uses the [GNU Affero General Public License v3.0](LICENSE).
