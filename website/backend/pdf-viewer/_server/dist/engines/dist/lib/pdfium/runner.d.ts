import { PdfiumNativeRunner } from '../orchestrator/pdfium-native-runner';
import { Logger } from '@embedpdf/models';
import { FontFallbackConfig } from './font-fallback';
/**
 * EngineRunner for pdfium-based wasm engine
 */
export declare class PdfiumEngineRunner extends PdfiumNativeRunner {
    private wasmBinary;
    private fontFallback?;
    /**
     * Create an instance of PdfiumEngineRunner
     * @param wasmBinary - wasm binary that contains the pdfium wasm file
     * @param logger - optional logger instance
     * @param fontFallback - optional font fallback configuration
     */
    constructor(wasmBinary: ArrayBuffer, logger?: Logger, fontFallback?: FontFallbackConfig);
    /**
     * Initialize runner
     */
    prepare(): Promise<void>;
}
