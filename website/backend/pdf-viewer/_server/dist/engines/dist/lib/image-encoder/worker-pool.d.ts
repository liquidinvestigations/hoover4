import { Logger } from '@embedpdf/models';
/**
 * Pool of image encoding workers to offload OffscreenCanvas operations
 * from the main PDFium worker thread
 */
export declare class ImageEncoderWorkerPool {
    private poolSize;
    private workerUrl;
    private workers;
    private pendingTasks;
    private nextWorkerId;
    private requestCounter;
    private logger;
    /**
     * Create a pool of image encoding workers
     * @param poolSize - Number of workers to create (default: 2)
     * @param workerUrl - URL to the worker script
     * @param logger - Logger instance
     */
    constructor(poolSize: number | undefined, workerUrl: string, logger?: Logger);
    /**
     * Initialize the worker pool
     */
    private initialize;
    /**
     * Handle messages from workers
     */
    private handleWorkerMessage;
    /**
     * Handle worker errors
     */
    private handleWorkerError;
    /**
     * Get the next available worker using round-robin
     */
    private getNextWorker;
    /**
     * Encode ImageData to Blob using a worker from the pool
     * @param imageData - Raw image data
     * @param imageType - Target image format
     * @param quality - Image quality (0-1) for lossy formats
     * @returns Promise that resolves to encoded Blob
     */
    encode(imageData: {
        data: Uint8ClampedArray;
        width: number;
        height: number;
    }, imageType?: 'image/png' | 'image/jpeg' | 'image/webp', quality?: number): Promise<Blob>;
    /**
     * Destroy all workers in the pool
     */
    destroy(): void;
    /**
     * Get the number of active workers in the pool
     */
    get activeWorkers(): number;
    /**
     * Get the number of pending encoding tasks
     */
    get pendingTasksCount(): number;
}
