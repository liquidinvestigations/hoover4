import { WasmPointer } from '../types/branded';
import { WrappedPdfiumModule } from '@embedpdf/pdfium';
import { Logger } from '@embedpdf/models';
interface Allocation {
    ptr: WasmPointer;
    size: number;
    timestamp: number;
    stack?: string;
}
export declare class MemoryManager {
    private pdfiumModule;
    private logger;
    private allocations;
    private totalAllocated;
    constructor(pdfiumModule: WrappedPdfiumModule, logger: Logger);
    /**
     * Allocate memory with tracking and validation
     */
    malloc(size: number): WasmPointer;
    /**
     * Free memory with validation
     */
    free(ptr: WasmPointer): void;
    /**
     * Get memory statistics
     */
    getStats(): {
        totalAllocated: number;
        allocationCount: number;
        allocations: Allocation[];
    };
    /**
     * Check for memory leaks
     */
    checkLeaks(): void;
}
export {};
