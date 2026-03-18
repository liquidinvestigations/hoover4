/**
 * Dedicated worker for image encoding operations
 * Offloads OffscreenCanvas.convertToBlob() from the main PDFium worker
 */
export interface EncodeImageRequest {
    id: string;
    type: 'encode';
    data: {
        imageData: {
            data: Uint8ClampedArray;
            width: number;
            height: number;
        };
        imageType: 'image/png' | 'image/jpeg' | 'image/webp';
        quality?: number;
    };
}
export interface EncodeImageResponse {
    id: string;
    type: 'result' | 'error';
    data: Blob | {
        message: string;
    };
}
