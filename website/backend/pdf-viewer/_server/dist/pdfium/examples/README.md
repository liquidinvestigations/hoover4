# @embedpdf/pdfium Examples

This directory contains examples demonstrating how to use the `@embedpdf/pdfium` package in Node.js environments.

## Overview

The examples showcase various PDFium capabilities including:

- Loading and rendering PDF documents
- Text extraction and analysis
- Page manipulation
- Metadata extraction
- Image rendering

## Node.js Examples

### Location: `node/`

The Node.js examples demonstrate server-side PDF processing capabilities.

#### Setup

1. Install dependencies:

   ```bash
   cd node/
   npm install
   ```

2. Build the parent PDFium package if needed:
   ```bash
   cd ../../
   npm run build
   cd examples/node/
   ```

#### `basic-example.js` - Comprehensive PDF Processing

A complete example showcasing multiple PDFium features:

**Features:**

- PDF document loading
- Document information extraction
- Page dimension analysis
- Text extraction
- Metadata retrieval
- Page rendering to bitmap
- PPM image file output

**Usage:**

```bash
# Run with your own PDF
node basic-example.js /path/to/your/file.pdf

# Or place a file named 'sample.pdf' in the node/ directory and run:
node basic-example.js
```

**What it does:**

1. Initializes PDFium WebAssembly
2. Loads the specified PDF document
3. Extracts document information (page count, permissions)
4. Analyzes first few pages (dimensions)
5. Extracts text from the first page
6. Retrieves PDF metadata
7. Renders first page to a bitmap image file
8. Saves output as PPM file

#### `text-extraction-example.js` - Advanced Text Processing

A specialized example focused on comprehensive text extraction and analysis:

**Features:**

- Full document text extraction
- Page-by-page text analysis
- Word frequency analysis
- Text search functionality
- Statistical reporting
- File output (text and analysis reports)

**Usage:**

```bash
# Run with your own PDF
node text-extraction-example.js /path/to/your/file.pdf

# Or use npm scripts
npm run example:text /path/to/your/file.pdf
```

**Output Files:**

- `extracted-text.txt` - Complete text extraction with page breakdown
- `analysis-report.txt` - Statistical analysis and word frequency report

**What it does:**

1. Extracts text from all pages
2. Counts characters and words per page
3. Generates document statistics
4. Performs word frequency analysis
5. Searches for common terms
6. Saves comprehensive text and analysis reports

## API Usage Examples

### Basic Initialization

```javascript
import { init } from '@embedpdf/pdfium';

// Initialize PDFium
const wasmBinary = await fetch('path/to/pdfium.wasm').then((r) =>
  r.arrayBuffer(),
);
const pdfium = await init({ wasmBinary });
pdfium.PDFiumExt_Init();
```

### Loading a PDF Document

```javascript
// From file buffer
const pdfBuffer = new Uint8Array(/* your PDF data */);
const dataPtr = pdfium.pdfium._malloc(pdfBuffer.length);
pdfium.pdfium.HEAPU8.set(pdfBuffer, dataPtr);

const document = pdfium.FPDF_LoadMemDocument(dataPtr, pdfBuffer.length, null);
pdfium.pdfium._free(dataPtr);
```

### Rendering a Page

```javascript
const page = pdfium.FPDF_LoadPage(document, pageIndex);
const width = pdfium.FPDF_GetPageWidthF(page);
const height = pdfium.FPDF_GetPageHeightF(page);

const bitmap = pdfium.FPDFBitmap_Create(width, height, 0);
pdfium.FPDFBitmap_FillRect(bitmap, 0, 0, width, height, 0xffffffff);
pdfium.FPDF_RenderPageBitmap(bitmap, page, 0, 0, width, height, 0, 0);

// Get bitmap data
const bufferPtr = pdfium.FPDFBitmap_GetBuffer(bitmap);
const imageData = new Uint8Array(
  pdfium.pdfium.HEAPU8.buffer,
  bufferPtr,
  width * height * 4,
);

// Cleanup
pdfium.FPDFBitmap_Destroy(bitmap);
pdfium.FPDF_ClosePage(page);
```

### Text Extraction

```javascript
const page = pdfium.FPDF_LoadPage(document, pageIndex);
const textPage = pdfium.FPDFText_LoadPage(page);
const charCount = pdfium.FPDFText_CountChars(textPage);

let text = '';
for (let i = 0; i < charCount; i++) {
  const unicode = pdfium.FPDFText_GetUnicode(textPage, i);
  if (unicode > 0) {
    text += String.fromCharCode(unicode);
  }
}

// Cleanup
pdfium.FPDFText_ClosePage(textPage);
pdfium.FPDF_ClosePage(page);
```

## Common Issues and Solutions

### Memory Management

**CRITICAL**: When loading a PDF with `FPDF_LoadMemDocument`, do NOT free the PDF data memory immediately after loading. PDFium keeps references to the original memory and will need it when loading pages. The memory should only be freed when:

1. The document is closed with `FPDF_CloseDocument`, or
2. A new PDF is being loaded

**Incorrect (causes page loading failures):**

```javascript
const dataPtr = pdfium.pdfium._malloc(pdfBuffer.length);
pdfium.pdfium.HEAPU8.set(pdfBuffer, dataPtr);
const document = pdfium.FPDF_LoadMemDocument(dataPtr, pdfBuffer.length, null);
pdfium.pdfium._free(dataPtr); // ❌ DON'T DO THIS - causes pages to fail loading
```

**Correct:**

```javascript
const dataPtr = pdfium.pdfium._malloc(pdfBuffer.length);
pdfium.pdfium.HEAPU8.set(pdfBuffer, dataPtr);
const document = pdfium.FPDF_LoadMemDocument(dataPtr, pdfBuffer.length, null);
// Keep dataPtr alive until document is closed
// ... use document and load pages ...
pdfium.FPDF_CloseDocument(document);
pdfium.pdfium._free(dataPtr); // ✅ Free after document is closed
```

### Node.js Issues

1. **Import Errors**: Ensure you're using ES modules (`"type": "module"` in package.json)
2. **File Paths**: Use absolute paths or ensure relative paths are correct
3. **Memory Management**: Call cleanup methods to prevent memory leaks

## Sample PDF Files

For testing, you can:

1. Create your own PDF files
2. Download sample PDFs from various sources
3. Use PDF generation libraries to create test documents

## Performance Notes

- **Memory Usage**: PDFium operations can be memory-intensive for large documents
- **Cleanup**: Always call cleanup methods to prevent memory leaks
- **Async Operations**: Use async/await for better performance in Node.js
- **Batch Processing**: Process pages in batches for large documents

## Contributing

Feel free to contribute additional examples or improvements to existing ones. Examples should be:

- Well-documented
- Error-handled
- Performance-conscious
- Educational

## License

These examples are provided under the same MIT license as the main `@embedpdf/pdfium` package.
