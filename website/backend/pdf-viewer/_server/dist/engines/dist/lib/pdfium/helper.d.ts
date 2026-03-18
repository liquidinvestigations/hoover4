import { Matrix, Rotation, Rect, Size } from '@embedpdf/models';
import { PdfiumRuntimeMethods, PdfiumModule } from '@embedpdf/pdfium';
/**
 * Read string from WASM heap
 * @param wasmModule - pdfium wasm module instance
 * @param readChars - function to read chars
 * @param parseChars - function to parse chars
 * @param defaultLength - default length of chars that needs to read
 * @returns string from the heap
 *
 * @public
 */
export declare function readString(wasmModule: PdfiumRuntimeMethods & PdfiumModule, readChars: (buffer: number, bufferLength: number) => number, parseChars: (buffer: number) => string, defaultLength?: number): string;
/**
 * Read arraybyffer from WASM heap
 * @param wasmModule - pdfium wasm module instance
 * @param readChars - function to read chars
 * @returns arraybuffer from the heap
 *
 * @public
 */
export declare function readArrayBuffer(wasmModule: PdfiumRuntimeMethods & PdfiumModule, readChars: (buffer: number, bufferLength: number) => number): ArrayBuffer;
export declare function isValidCustomKey(key: string): boolean;
interface FormDrawParams {
    startX: number;
    startY: number;
    formsWidth: number;
    formsHeight: number;
    scaleX: number;
    scaleY: number;
}
export declare function computeFormDrawParams(matrix: Matrix, rect: Rect, pageSize: Size, rotation: Rotation): FormDrawParams;
export {};
