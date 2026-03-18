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
export const MEMORY_LIMITS = {
  /** Maximum total memory that can be allocated (2GB) */
  MAX_TOTAL_MEMORY: 2 * 1024 * 1024 * 1024,
} as const;

/**
 * All limits combined for easy access
 */
export const LIMITS = {
  MEMORY: MEMORY_LIMITS,
} as const;

export type Limits = typeof LIMITS;
