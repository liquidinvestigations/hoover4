import { Logger, TaskError } from '@embedpdf/models';
import { PdfiumNative } from '../pdfium/engine';
/**
 * Request message from main thread
 */
export interface WorkerRequest {
    id: string;
    type: 'execute' | 'init';
    method?: string;
    args?: any[];
    wasmUrl?: string;
}
/**
 * Response message to main thread
 */
export interface WorkerResponse {
    id: string;
    type: 'result' | 'error' | 'progress' | 'ready';
    data?: any;
    error?: TaskError<any>;
    progress?: any;
}
/**
 * PdfiumNativeRunner - Worker runner for PdfiumNative
 *
 * This handles:
 * - Initialization of PdfiumNative in worker context
 * - Message handling from main thread
 * - Task execution and result forwarding
 * - Progress tracking
 */
export declare class PdfiumNativeRunner {
    native: PdfiumNative | null;
    logger: Logger;
    private activeTasks;
    constructor(logger?: Logger);
    /**
     * Initialize PDFium with WASM binary
     */
    prepare(wasmBinary: ArrayBuffer, logger?: Logger): Promise<void>;
    /**
     * Start listening for messages
     */
    listen(): void;
    /**
     * Handle incoming messages
     */
    handle(evt: MessageEvent<WorkerRequest>): void;
    /**
     * Handle initialization request
     */
    private handleInit;
    /**
     * Handle method execution request
     */
    private handleExecute;
    /**
     * Send response back to main thread
     */
    private respond;
    /**
     * Ready notification
     */
    ready(): void;
}
