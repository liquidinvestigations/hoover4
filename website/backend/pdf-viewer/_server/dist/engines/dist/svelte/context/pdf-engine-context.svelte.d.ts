import { PdfEngine } from '@embedpdf/models';
export interface PdfEngineContextState {
    engine: PdfEngine | null;
    isLoading: boolean;
    error: Error | null;
}
/**
 * Set the PDF engine context (used by PdfEngineProvider)
 */
export declare function setPdfEngineContext(value: PdfEngineContextState): void;
/**
 * Get the PDF engine context
 * @throws Error if used outside of PdfEngineProvider
 */
export declare function getPdfEngineContext(): PdfEngineContextState;
