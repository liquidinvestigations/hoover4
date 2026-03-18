/**
 * Branded types for better type safety
 * @public
 */

declare const PointerBrand: unique symbol;

export type WasmPointer = number & { [PointerBrand]: never };

// Helper functions to create branded types
export const WasmPointer = (ptr: number): WasmPointer => ptr as WasmPointer;
