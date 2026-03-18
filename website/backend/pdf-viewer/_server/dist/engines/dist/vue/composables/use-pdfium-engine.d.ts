import { Ref } from 'vue';
import { Logger, PdfEngine } from '@embedpdf/models';
import { FontFallbackConfig } from '../../lib/index.ts';
interface UsePdfiumEngineProps {
    wasmUrl?: string;
    worker?: boolean;
    logger?: Logger;
    /**
     * Font fallback configuration for handling missing fonts in PDFs.
     */
    fontFallback?: FontFallbackConfig;
}
interface UsePdfiumEngineResult {
    engine: Ref<PdfEngine | null>;
    isLoading: Ref<boolean>;
    error: Ref<Error | null>;
}
/**
 * Vue composable that loads a PdfiumEngine (worker or direct)
 * and keeps its lifetime tied to the component.
 */
export declare function usePdfiumEngine(props?: UsePdfiumEngineProps): UsePdfiumEngineResult;
export {};
