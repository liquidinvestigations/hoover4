import { Logger, PdfEngine } from '@embedpdf/models';
import { FontFallbackConfig } from '../../lib/index.ts';
interface UsePdfiumEngineProps {
    wasmUrl?: string;
    worker?: boolean;
    logger?: Logger;
    encoderPoolSize?: number;
    /**
     * Font fallback configuration for handling missing fonts in PDFs.
     */
    fontFallback?: FontFallbackConfig;
}
export declare function usePdfiumEngine(config?: UsePdfiumEngineProps): {
    engine: PdfEngine<Blob> | null;
    isLoading: boolean;
    error: Error | null;
};
export {};
