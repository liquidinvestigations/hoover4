import { ImageDataConverter } from './types';
import { ImageEncoderWorkerPool } from '../image-encoder';
export declare class ImageConverterError extends Error {
    constructor(message: string);
}
/**
 * Main-thread Canvas-based image converter
 * Simple and works everywhere, but blocks the main thread during encoding
 *
 * Use this as a fallback when worker-based encoding isn't available
 */
export declare const browserImageDataToBlobConverter: ImageDataConverter<Blob>;
/**
 * Worker pool image converter using OffscreenCanvas in dedicated workers
 * Non-blocking - encoding happens off the main thread
 *
 * This is the preferred approach for performance
 *
 * @param workerPool - Instance of ImageEncoderWorkerPool
 * @returns ImageDataConverter function with destroy() for cleanup
 */
export declare function createWorkerPoolImageConverter(workerPool: ImageEncoderWorkerPool): ImageDataConverter<Blob>;
/**
 * Hybrid converter: Worker pool (OffscreenCanvas) → Main thread Canvas fallback
 *
 * Best of both worlds:
 * - Primary: Non-blocking worker-based encoding with OffscreenCanvas
 * - Fallback: Main-thread Canvas for older browsers without OffscreenCanvas in workers
 *
 * @param workerPool - Instance of ImageEncoderWorkerPool
 * @returns ImageDataConverter function with destroy() for cleanup
 */
export declare function createHybridImageConverter(workerPool: ImageEncoderWorkerPool): ImageDataConverter<Blob>;
