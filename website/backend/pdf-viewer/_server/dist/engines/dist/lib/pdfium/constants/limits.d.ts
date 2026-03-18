/**
 * System limits and safety thresholds for PDFium engine operations
 *
 * These limits are designed to prevent:
 * - Memory exhaustion
 * - Browser crashes
 * - DoS attacks
 * - WASM heap overflow
 * - Unreasonable resource usage
 *
 * @module constants/limits
 */
/**
 * Memory allocation limits
 */
export declare const MEMORY_LIMITS: {
    /** Maximum total memory that can be allocated (2GB) */
    readonly MAX_TOTAL_MEMORY: number;
};
/**
 * All limits combined for easy access
 */
export declare const LIMITS: {
    readonly MEMORY: {
        /** Maximum total memory that can be allocated (2GB) */
        readonly MAX_TOTAL_MEMORY: number;
    };
};
export type Limits = typeof LIMITS;
