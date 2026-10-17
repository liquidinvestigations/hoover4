# Read current architecture diagrams.

[The architecture index](../../docs/architecture/Readme.md) describes current components and links their source owners.
[Pipeline stages](../../docs/architecture/Pipeline_Stages.md) describe ingestion and indexing.
[The storage model](../../docs/architecture/Storage_Model.md) describes identities, bytes, and stored results.

## Preserve the historical drawings.

These drawings include earlier proposals and obsolete component names.
They do not define current capabilities.
Their PNG metadata retains the embedded draw.io source.

- [The process drawing](diagram-1-high-level-process.png) includes investigation tasks outside the application.
- [The data-flow drawing](diagram-2-data-flow.png) includes proposed integrations and analysis services.
- [The storage drawing](diagram-3-data-representation.png) includes historical stores and table names.

Current object storage uses Garage.
Current search and vector tables use Manticore, with durable vectors in ClickHouse.
The drawings do not establish current translation, classification, redaction, tagging, or external ingestion integrations.
Use the [feature register](../../docs/technical-specification/Features.md) for current capabilities.

[Return to the main services.](../Readme.md)
