/**
 * Branded types for better type safety
 * @public
 */
declare const PointerBrand: unique symbol;
export type WasmPointer = number & {
    [PointerBrand]: never;
};
export declare const WasmPointer: (ptr: number) => WasmPointer;
export {};
