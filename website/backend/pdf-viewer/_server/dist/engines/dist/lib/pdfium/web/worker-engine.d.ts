import { Logger } from '@embedpdf/models';
import { PdfEngine } from '../../orchestrator/pdf-engine';
import { FontFallbackConfig } from '../font-fallback';
export type { FontFallbackConfig };
export interface CreatePdfiumEngineOptions {
    /**
     * Logger instance for debugging
     */
    logger?: Logger;
    /**
     * Number of workers in the image encoder pool (default: 0 - disabled)
     * Set to 2-4 for optimal performance with parallel encoding
     */
    encoderPoolSize?: number;
    /**
     * Font fallback configuration for handling missing fonts in PDFs.
     * When enabled, PDFium will request fallback fonts from configured URLs
     * when it encounters text that requires fonts not embedded in the PDF.
     */
    fontFallback?: FontFallbackConfig;
}
/**
 * Create a PDFium engine running in a Web Worker
 *
 * This is the "worker" mode where PDFium runs in a separate worker thread.
 * The PdfEngine orchestrator provides priority-based task scheduling and
 * parallel image encoding with a separate encoder pool.
 *
 * @param wasmUrl - URL to the pdfium.wasm file
 * @param options - Configuration options (can be Logger for backward compatibility)
 *
 * @example
 * // Legacy usage (backward compatible)
 * const engine = createPdfiumEngine('/wasm/pdfium.wasm', logger);
 *
 * @example
 * // With encoder pool (automatic - no URL needed!)
 * const engine = createPdfiumEngine('/wasm/pdfium.wasm', {
 *   logger,
 *   encoderPoolSize: 2
 * });
 *
 * @example
 * // With custom encoder worker URL
 * const engine = createPdfiumEngine('/wasm/pdfium.wasm', {
 *   logger,
 *   encoderPoolSize: 2,
 *   encoderWorkerUrl: '/custom/encoder-worker.js'
 * });
 */
export declare function createPdfiumEngine(wasmUrl: string, options?: Logger | CreatePdfiumEngineOptions): PdfEngine<Blob>;
