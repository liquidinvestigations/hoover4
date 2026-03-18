import { PdfEngine } from '@embedpdf/models';
export interface PdfEngineContextState {
    engine: PdfEngine | null;
    isLoading: boolean;
    error: Error | null;
}
export declare const PdfEngineContext: import('preact').Context<PdfEngineContextState | undefined>;
