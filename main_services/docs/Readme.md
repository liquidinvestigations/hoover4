## System Architecture Diagrams

This directory contains visual references for the Hoover4 processing pipeline, data flow, and storage model.

### High-Level Process Overview
![High-Level Process](diagram-1-high-level-process.png)

The lifecycle from source acquisition to processing, review, analysis, and internal presentation. It situates Hoover4 as the processing core that turns raw collections into searchable, labeled, and analysis-ready data products.


- Source material is identified, collected, and preserved into an original dataset. This dataset is then loaded into our software.
- Processing is staged: filesystem and archive enumeration with de-duplication; metadata extraction and OCR with thumbnails and PDF conversion; and text-level AI such as language detection and NER.
- The Hoover4 core services include ClickHouse for analytics tables, Tika for metadata and text extraction, Manticore for search (plus vector indexing), object-level storage in S3-compatible systems, and a processing dashboard.
- Review workflows provide search, tagging, and data labeling, plus AI-assisted redaction, privilege detection, classification, and predictive coding.
- Analysis workflows extend search with chat/LLM interfaces, pattern detection, and analytical dashboards.
- Production and presentation focus on analyst synthesis, cross-referenced outputs, and internal knowledge delivery. This stage happens outside of Hoover4; data is exported from the system before publication and production.

### Data Flow Architecture
![Data Flow](diagram-2-data-flow.png)

The end-to-end flow from raw inputs through extraction and normalization into storage and index layers, then onward to search, analytics, and AI-driven interfaces.


- Unstructured sources (web listings, archives, emails, documents, media) are ingested, deduplicated, and passed through extractors that produce text and metadata.
- Structured sources are normalized into ClickHouse tables alongside the extracted metadata and text.
- AI labeling enriches text with language detection, named entities, and translation.
- ClickHouse stores normalized records and metadata; Manticore provides keyword search; vector indexing supports similarity and RAG workflows.
- Downstream applications include operational dashboards, search interfaces, chat/LLM tools, analytics dashboards, and classification workflows.

### Data Representation
![Data Representation](diagram-3-data-representation.png)

The relational model that connects datasets, files, derived artifacts, and indexing outputs. It provides a map of how raw source material is transformed into searchable and analyzable representations.


- Datasets map to virtual filesystem tables for directories and files, with file types and blob records as the base layer.
- Specialized tables capture parsed artifacts for archives, email, PDFs, images, audio, and video, including OCR outputs and extracted text.
- Processing state and lineage are tracked through plans, workflow outputs, and error tables.
- Search and retrieval layers link text chunks, entity hits, and indexing metadata to the original file records.

## Navigation

-  [Go Back](../Readme.md)
