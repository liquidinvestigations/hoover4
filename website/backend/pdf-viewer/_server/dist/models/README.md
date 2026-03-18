<div align="center">
  <a href="https://www.embedpdf.com">
    <img alt="EmbedPDF logo" src="https://www.embedpdf.com/logo-192.png" height="96">
  </a>
  <h1>EmbedPDF</h1>

<a href="https://www.npmjs.com/package/@embedpdf/models"><img alt="NPM version" src="https://img.shields.io/npm/v/@embedpdf/models.svg?style=for-the-badge&labelColor=000000"></a> <a href="https://github.com/embedpdf/embed-pdf-viewer/blob/main/packages/models/LICENSE"><img alt="License" src="https://img.shields.io/npm/l/@embedpdf/models.svg?style=for-the-badge&labelColor=000000"></a> <a href="https://github.com/embedpdf/embed-pdf-viewer/discussions"><img alt="Join the community on GitHub" src="https://img.shields.io/badge/Join%20the%20community-blueviolet.svg?style=for-the-badge&labelColor=000000"></a>

</div>

# @embedpdf/models

Centralised **type definitions & helper utilities** shared by every EmbedPDF runtime and UI package. Keep your codebase error‑free with a single source of truth for documents, pages, annotations, geometry, async tasks, permissions, and more.

## Documentation

Full reference & examples live at:

**[Official Documentation](https://www.embedpdf.com/docs)**

## Why `@embedpdf/models`?

- **Single source of truth** – all packages agree on data shapes (e.g. `PdfDocumentObject`, `PdfAnnotationObject`).
- **Strong typing** – exhaustive enums, discriminated unions, generics; a huge boost to DX.
- **Zero runtime cost** – pure type exports & tiny helper functions, fully tree‑shakable.

## Features

- Geometry helpers (`transformRect`, `rotateRect`, `boundingRect`, …)
- Logger with pluggable transports & log‑level filtering
- Promise‑like **Task** abstraction (cancellable / abortable)
- Rich PDF domain model: documents, pages, bookmarks, annotations, form fields, permissions, search
- Utility helpers (`unionFlags`, `PdfTaskHelper`, …)

## Installation

```bash
npm install @embedpdf/models
```

## Basic Usage

```typescript
import { Rect, transformRect, Rotation } from '@embedpdf/models';

const pageSize = { width: 612, height: 792 }; // Letter size
const annotation: Rect = {
  origin: { x: 100, y: 150 },
  size: { width: 200, height: 50 },
};

// Rotate 90° and scale by 1.5×
const transformed = transformRect(pageSize, annotation, Rotation.Degree90, 1.5);
console.log(transformed);
```

## Learn More

Check the docs for deep dives into:

- **Geometry API** – positions, quads, rectangles
- **Task abstraction** – cancellable async workflows
- **Complete Type Reference** – every interface & enum used across the stack

## License

MIT – see the [LICENSE](https://github.com/embedpdf/embed-pdf-viewer/blob/main/packages/models/LICENSE) file.
