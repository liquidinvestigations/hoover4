import { init } from '@embedpdf/pdfium';
import { readFile, writeFile } from 'fs/promises';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

class PDFiumNodeExample {
  constructor() {
    this.pdfiumInstance = null;
    this.pdfDocument = null;
    this.pdfDataPtr = null; // Store the pointer to free it later
  }

  async initialize() {
    if (this.pdfiumInstance) return this.pdfiumInstance;

    try {
      console.log('Initializing PDFium...');

      // Load the WASM binary
      const wasmPath = join(__dirname, '../../dist/pdfium.wasm');
      const wasmBinary = await readFile(wasmPath);

      // Initialize PDFium
      this.pdfiumInstance = await init({ wasmBinary });
      this.pdfiumInstance.PDFiumExt_Init();

      console.log('PDFium initialized successfully!');
      return this.pdfiumInstance;
    } catch (error) {
      console.error('Failed to initialize PDFium:', error.message);
      throw error;
    }
  }

  async loadPDF(pdfPath) {
    try {
      if (!this.pdfiumInstance) {
        await this.initialize();
      }

      console.log(`Loading PDF: ${pdfPath}`);

      // Clean up previous document if it exists
      if (this.pdfDocument) {
        this.pdfiumInstance.FPDF_CloseDocument(this.pdfDocument);
        this.pdfDocument = null;
      }

      // Free previous PDF data if it exists
      if (this.pdfDataPtr) {
        this.pdfiumInstance.pdfium._free(this.pdfDataPtr);
        this.pdfDataPtr = null;
      }

      // Read PDF file
      const pdfBuffer = await readFile(pdfPath);

      // Allocate memory for PDF data
      this.pdfDataPtr = this.pdfiumInstance.pdfium._malloc(pdfBuffer.length);
      this.pdfiumInstance.pdfium.HEAPU8.set(pdfBuffer, this.pdfDataPtr);

      // Load the PDF document
      this.pdfDocument = this.pdfiumInstance.FPDF_LoadMemDocument(
        this.pdfDataPtr,
        pdfBuffer.length,
        '',
      );

      if (!this.pdfDocument) {
        const error = this.pdfiumInstance.FPDF_GetLastError();
        // Free the allocated memory if document loading failed
        this.pdfiumInstance.pdfium._free(this.pdfDataPtr);
        this.pdfDataPtr = null;
        throw new Error(`Failed to load PDF document. Error code: ${error}`);
      }

      // DON'T free the allocated memory here - keep it until document is closed
      // this.pdfiumInstance.pdfium._free(this.pdfDataPtr);

      console.log('PDF loaded successfully!');
      return this.pdfDocument;
    } catch (error) {
      console.error('Error loading PDF:', error.message);
      throw error;
    }
  }

  getDocumentInfo() {
    if (!this.pdfDocument) {
      throw new Error('No PDF document loaded');
    }

    const pageCount = this.pdfiumInstance.FPDF_GetPageCount(this.pdfDocument);
    const permissions = this.pdfiumInstance.FPDF_GetDocPermissions(this.pdfDocument);

    console.log('\n=== Document Information ===');
    console.log(`Pages: ${pageCount}`);
    console.log(`Permission flags: ${permissions}`);

    return { pageCount, permissions };
  }

  async getPageInfo(pageIndex = 0) {
    if (!this.pdfDocument) {
      throw new Error('No PDF document loaded');
    }

    const totalPages = this.pdfiumInstance.FPDF_GetPageCount(this.pdfDocument);
    if (pageIndex >= totalPages) {
      throw new Error(`Page index ${pageIndex} is out of range (0-${totalPages - 1})`);
    }

    console.log(`\n=== Page ${pageIndex + 1} Information ===`);

    // Load the page with better error handling
    const page = this.pdfiumInstance.FPDF_LoadPage(this.pdfDocument, pageIndex);

    if (!page) {
      // Get the last error code for more detailed debugging
      const errorCode = this.pdfiumInstance.FPDF_GetLastError();
      const errorMessages = {
        0: 'FPDF_ERR_SUCCESS - No error',
        1: 'FPDF_ERR_UNKNOWN - Unknown error',
        2: 'FPDF_ERR_FILE - File not found or could not be opened',
        3: 'FPDF_ERR_FORMAT - File not in PDF format or corrupted',
        4: 'FPDF_ERR_PASSWORD - Password required or provided password is incorrect',
        5: 'FPDF_ERR_SECURITY - Unsupported security scheme',
        6: 'FPDF_ERR_PAGE - Page not found or content error',
      };

      const errorMessage = errorMessages[errorCode] || `Unknown error code: ${errorCode}`;
      console.error(`Failed to load page ${pageIndex}. PDFium error: ${errorMessage}`);

      // Try to continue with next page instead of throwing
      return { width: 0, height: 0, error: errorMessage };
    }

    // Get page dimensions
    const width = this.pdfiumInstance.FPDF_GetPageWidthF(page);
    const height = this.pdfiumInstance.FPDF_GetPageHeightF(page);

    console.log(`Dimensions: ${width.toFixed(2)} x ${height.toFixed(2)} points`);

    // Clean up
    this.pdfiumInstance.FPDF_ClosePage(page);

    return { width, height };
  }

  async extractText(pageIndex = 0) {
    if (!this.pdfDocument) {
      throw new Error('No PDF document loaded');
    }

    const totalPages = this.pdfiumInstance.FPDF_GetPageCount(this.pdfDocument);
    if (pageIndex >= totalPages) {
      throw new Error(`Page index ${pageIndex} is out of range (0-${totalPages - 1})`);
    }

    console.log(`\nExtracting text from page ${pageIndex + 1}...`);

    // Load the page
    const page = this.pdfiumInstance.FPDF_LoadPage(this.pdfDocument, pageIndex);
    if (!page) {
      throw new Error(`Failed to load page ${pageIndex}`);
    }

    // Load text page
    const textPage = this.pdfiumInstance.FPDFText_LoadPage(page);
    if (!textPage) {
      this.pdfiumInstance.FPDF_ClosePage(page);
      throw new Error(`Failed to load text page ${pageIndex}`);
    }

    // Get character count
    const charCount = this.pdfiumInstance.FPDFText_CountChars(textPage);
    console.log(`Character count: ${charCount}`);

    // Extract text (simplified - in real implementation you'd want to handle this more carefully)
    let extractedText = '';
    for (let i = 0; i < Math.min(charCount, 1000); i++) {
      // Limit to first 1000 chars for demo
      const unicode = this.pdfiumInstance.FPDFText_GetUnicode(textPage, i);
      if (unicode > 0 && unicode < 0x10000) {
        // Basic handling of Unicode
        extractedText += String.fromCharCode(unicode);
      }
    }

    console.log(`\n=== Extracted Text (first 500 chars) ===`);
    console.log(extractedText.substring(0, 500) + (extractedText.length > 500 ? '...' : ''));

    // Clean up
    this.pdfiumInstance.FPDFText_ClosePage(textPage);
    this.pdfiumInstance.FPDF_ClosePage(page);

    return extractedText;
  }

  async renderPageToBitmap(pageIndex = 0, outputPath = null) {
    if (!this.pdfDocument) {
      throw new Error('No PDF document loaded');
    }

    const totalPages = this.pdfiumInstance.FPDF_GetPageCount(this.pdfDocument);
    if (pageIndex >= totalPages) {
      throw new Error(`Page index ${pageIndex} is out of range (0-${totalPages - 1})`);
    }

    console.log(`\nRendering page ${pageIndex + 1} to bitmap...`);

    // Load the page
    const page = this.pdfiumInstance.FPDF_LoadPage(this.pdfDocument, pageIndex);
    if (!page) {
      throw new Error(`Failed to load page ${pageIndex}`);
    }

    // Get page dimensions
    const pageWidth = this.pdfiumInstance.FPDF_GetPageWidthF(page);
    const pageHeight = this.pdfiumInstance.FPDF_GetPageHeightF(page);

    // Set up bitmap dimensions (scale for higher quality)
    const scale = 2;
    const bitmapWidth = Math.floor(pageWidth * scale);
    const bitmapHeight = Math.floor(pageHeight * scale);

    console.log(`Bitmap dimensions: ${bitmapWidth} x ${bitmapHeight}`);

    // Create bitmap
    const bitmap = this.pdfiumInstance.FPDFBitmap_Create(bitmapWidth, bitmapHeight, 0);
    if (!bitmap) {
      this.pdfiumInstance.FPDF_ClosePage(page);
      throw new Error('Failed to create bitmap');
    }

    // Fill with white background
    this.pdfiumInstance.FPDFBitmap_FillRect(bitmap, 0, 0, bitmapWidth, bitmapHeight, 0xffffffff);

    // Render page to bitmap
    this.pdfiumInstance.FPDF_RenderPageBitmap(bitmap, page, 0, 0, bitmapWidth, bitmapHeight, 0, 0);

    // Get bitmap data
    const bufferPtr = this.pdfiumInstance.FPDFBitmap_GetBuffer(bitmap);
    const bufferSize = bitmapWidth * bitmapHeight * 4; // BGRA format
    const imageData = new Uint8Array(
      this.pdfiumInstance.pdfium.HEAPU8.buffer,
      bufferPtr,
      bufferSize,
    );

    console.log(`Rendered bitmap size: ${imageData.length} bytes`);

    // Save to file if output path is provided
    if (outputPath) {
      // Convert BGRA to RGBA for standard image formats
      const rgbaData = new Uint8Array(imageData.length);
      for (let i = 0; i < imageData.length; i += 4) {
        rgbaData[i] = imageData[i + 2]; // R
        rgbaData[i + 1] = imageData[i + 1]; // G
        rgbaData[i + 2] = imageData[i]; // B
        rgbaData[i + 3] = imageData[i + 3]; // A
      }

      // Create a simple PPM file (for demonstration)
      const ppmHeader = `P6\n${bitmapWidth} ${bitmapHeight}\n255\n`;
      const ppmData = new Uint8Array(ppmHeader.length + bitmapWidth * bitmapHeight * 3);

      // Write header
      for (let i = 0; i < ppmHeader.length; i++) {
        ppmData[i] = ppmHeader.charCodeAt(i);
      }

      // Write RGB data (skip alpha channel)
      let ppmOffset = ppmHeader.length;
      for (let i = 0; i < rgbaData.length; i += 4) {
        ppmData[ppmOffset++] = rgbaData[i]; // R
        ppmData[ppmOffset++] = rgbaData[i + 1]; // G
        ppmData[ppmOffset++] = rgbaData[i + 2]; // B
      }

      await writeFile(outputPath, ppmData);
      console.log(`Bitmap saved to: ${outputPath}`);
    }

    // Clean up
    this.pdfiumInstance.FPDFBitmap_Destroy(bitmap);
    this.pdfiumInstance.FPDF_ClosePage(page);

    return imageData;
  }

  async getMetadata() {
    if (!this.pdfDocument) {
      throw new Error('No PDF document loaded');
    }

    console.log('\n=== PDF Metadata ===');

    const metadataKeys = ['Title', 'Author', 'Subject', 'Keywords', 'Creator', 'Producer'];
    const metadata = {};

    for (const key of metadataKeys) {
      // Get the length of the metadata value
      const length = this.pdfiumInstance.FPDF_GetMetaText(this.pdfDocument, key, null, 0);

      if (length > 0) {
        // Allocate buffer for the metadata value
        const buffer = this.pdfiumInstance.pdfium._malloc(length * 2); // UTF-16 requires 2 bytes per char
        const actualLength = this.pdfiumInstance.FPDF_GetMetaText(
          this.pdfDocument,
          key,
          buffer,
          length,
        );

        if (actualLength > 0) {
          // Read the UTF-16 string
          const utf16Array = new Uint16Array(
            this.pdfiumInstance.pdfium.HEAPU8.buffer,
            buffer,
            actualLength - 1, // Exclude null terminator
          );
          const value = String.fromCharCode(...utf16Array);
          metadata[key] = value;
          console.log(`${key}: ${value}`);
        }

        this.pdfiumInstance.pdfium._free(buffer);
      }
    }

    return metadata;
  }

  cleanup() {
    if (this.pdfDocument) {
      this.pdfiumInstance.FPDF_CloseDocument(this.pdfDocument);
      this.pdfDocument = null;
    }

    // Free the PDF data memory only after closing the document
    if (this.pdfDataPtr) {
      this.pdfiumInstance.pdfium._free(this.pdfDataPtr);
      this.pdfDataPtr = null;
      console.log('PDF data memory freed');
    }

    if (this.pdfiumInstance) {
      // Note: In a real application, you might want to call FPDF_DestroyLibrary()
      // but be careful as it affects all PDFium usage globally
      console.log('PDF document closed');
    }
  }
}

// Example usage
async function runExample() {
  const example = new PDFiumNodeExample();

  try {
    // You can provide a PDF file path as command line argument
    const pdfPath = process.argv[2] || join(__dirname, 'sample.pdf');

    console.log('PDFium Node.js Example');
    console.log('=======================');

    // Initialize PDFium
    await example.initialize();

    // Load PDF (you'll need to provide a sample PDF file)
    try {
      await example.loadPDF(pdfPath);
    } catch (error) {
      console.error('\nError: Could not load PDF file.');
      console.log('Please provide a valid PDF file path as an argument:');
      console.log('node basic-example.js /path/to/your/file.pdf');
      console.log('\nOr place a file named "sample.pdf" in the examples/node/ directory.');
      return;
    }

    // Get document information
    const docInfo = example.getDocumentInfo();

    // Get information about the first few pages
    const maxPages = Math.min(docInfo.pageCount, 4);
    console.log(`\nAnalyzing first ${maxPages} pages...`);

    for (let i = 0; i < maxPages; i++) {
      try {
        const pageInfo = await example.getPageInfo(i);
        if (pageInfo.error) {
          console.warn(`Skipping page ${i + 1} due to error: ${pageInfo.error}`);
        } else {
          console.log(
            `Page ${i + 1} processed successfully: ${pageInfo.width.toFixed(2)} x ${pageInfo.height.toFixed(2)} points`,
          );
        }
      } catch (error) {
        console.error(`Error processing page ${i + 1}:`, error.message);
        // Continue with next page
      }
    }

    // Extract text from first page
    await example.extractText(0);

    // Get metadata
    await example.getMetadata();

    // Render first page to bitmap (save as PPM file)
    const outputPath = join(__dirname, 'output-page-1.ppm');
    await example.renderPageToBitmap(0, outputPath);

    console.log('\n=== Example completed successfully! ===');
  } catch (error) {
    console.error('Example failed:', error.message);
    console.error(error.stack);
  } finally {
    // Clean up
    example.cleanup();
  }
}

// Run the example if this file is executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runExample().catch(console.error);
}

export { PDFiumNodeExample };
