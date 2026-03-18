import { PdfImage, ImageConversionTypes } from '@embedpdf/models';
import { ImageDataConverter } from './types';
/**
 * Node.js implementation using Sharp
 * This requires the 'sharp' package to be installed
 *
 * @example
 * ```typescript
 * import sharp from 'sharp';
 * import { createNodeImageDataToBufferConverter } from '@embedpdf/engines';
 *
 * const imageDataConverter = createNodeImageDataToBufferConverter(sharp);
 * const engine = new PdfiumEngine(pdfiumModule, { logger, imageDataConverter });
 * ```
 */
export declare function createNodeImageDataToBufferConverter(sharp: any): ImageDataConverter<Buffer>;
/**
 * Alternative Node.js implementation using canvas (node-canvas)
 * This requires the 'canvas' package to be installed
 *
 * @example
 * ```typescript
 * import { createCanvas } from 'canvas';
 * import { createNodeCanvasImageDataToBlobConverter } from '@embedpdf/engines';
 *
 * const imageDataConverter = createNodeCanvasImageDataToBlobConverter(createCanvas);
 * const engine = new PdfiumEngine(pdfiumModule, { logger, imageDataConverter });
 * ```
 */
export declare function createNodeCanvasImageDataToBlobConverter(createCanvas: any): ImageDataConverter<Buffer>;
/**
 * Generic Node.js implementation that works with any image processing library
 * that can handle raw RGBA data
 *
 * @example
 * ```typescript
 * const converter = createCustomImageDataToBlobConverter(async (imageData) => {
 *   // Your custom image processing logic here
 *   // Return a Buffer that will be wrapped in a Blob
 *   return processImageWithYourLibrary(imageData);
 * });
 * ```
 */
export declare function createCustomImageDataToBlobConverter(processor: (imageData: PdfImage, imageType?: ImageConversionTypes, imageQuality?: number) => Promise<Buffer>): ImageDataConverter;
/**
 * Create a custom converter that returns a Buffer
 * @param processor - function to process the image data
 * @param imageType - image type
 * @returns ImageDataToBlobConverter<Buffer>
 */
export declare function createCustomImageDataToBufferConverter(processor: (imageData: PdfImage, imageType: ImageConversionTypes, imageQuality?: number) => Promise<Buffer>): ImageDataConverter<Buffer>;
