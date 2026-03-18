import { WrappedPdfiumModule } from '@embedpdf/pdfium';
import { MemoryManager } from './core/memory-manager';
export interface CacheConfig {
    /** Time-to-live for pages in milliseconds (default: 5000ms) */
    pageTtl?: number;
    /** Maximum number of pages to keep in cache per document (default: 50) */
    maxPagesPerDocument?: number;
    /**
     * When true, pages are loaded with normalized rotation:
     * - All coordinates (annotations, text, rendering) are in 0° space
     * - The original rotation is preserved for reference
     * @default false
     */
    normalizeRotation?: boolean;
}
export declare class PdfCache {
    private readonly pdfium;
    private readonly memoryManager;
    private readonly docs;
    private readonly config;
    constructor(pdfium: WrappedPdfiumModule, memoryManager: MemoryManager, config?: CacheConfig);
    /** Open (or re-use) a document */
    setDocument(id: string, filePtr: number, docPtr: number, normalizeRotation?: boolean): void;
    /** Retrieve the DocumentContext for a given PdfDocumentObject */
    getContext(docId: string): DocumentContext | undefined;
    /** Close & fully release a document and all its pages */
    closeDocument(docId: string): boolean;
    /** Close all documents */
    closeAllDocuments(): void;
    /** Update cache configuration for all existing documents */
    updateConfig(newConfig: CacheConfig): void;
    /** Get current cache statistics */
    getCacheStats(): {
        documents: number;
        totalPages: number;
        pagesByDocument: Record<string, number>;
    };
}
export declare class DocumentContext {
    readonly filePtr: number;
    readonly docPtr: number;
    private readonly memoryManager;
    private readonly pageCache;
    readonly normalizeRotation: boolean;
    constructor(filePtr: number, docPtr: number, pdfium: WrappedPdfiumModule, memoryManager: MemoryManager, config: Required<CacheConfig>);
    /** Main accessor for pages */
    acquirePage(pageIdx: number): PageContext;
    /** Scoped accessor for one-off / bulk operations */
    borrowPage<T>(pageIdx: number, fn: (ctx: PageContext) => T): T;
    /** Update cache configuration */
    updateConfig(config: Required<CacheConfig>): void;
    /** Get number of pages currently in cache */
    getCacheSize(): number;
    /** Tear down all pages + this document */
    dispose(): void;
}
export declare class PageCache {
    readonly pdf: WrappedPdfiumModule;
    private readonly docPtr;
    private readonly cache;
    private readonly accessOrder;
    private config;
    constructor(pdf: WrappedPdfiumModule, docPtr: number, config: Required<CacheConfig>);
    acquire(pageIdx: number): PageContext;
    /** Helper: run a function "scoped" to a page.
     *    – if the page was already cached  → .release() (keeps TTL logic)
     *    – if the page was loaded just now → .disposeImmediate() (free right away)
     */
    borrowPage<T>(pageIdx: number, fn: (ctx: PageContext) => T): T;
    forceReleaseAll(): void;
    /** Update cache configuration */
    updateConfig(config: Required<CacheConfig>): void;
    /** Get current cache size */
    size(): number;
    /** Evict least recently used pages if cache exceeds max size */
    private evictIfNeeded;
    /** Update the access order for LRU tracking */
    private updateAccessOrder;
    /** Remove a page from the access order array */
    private removeFromAccessOrder;
}
export declare class PageContext {
    private readonly pdf;
    readonly docPtr: number;
    readonly pageIdx: number;
    readonly pagePtr: number;
    private readonly onFinalDispose;
    private refCount;
    private expiryTimer?;
    private disposed;
    private ttl;
    private textPagePtr?;
    private formInfoPtr?;
    private formHandle?;
    constructor(pdf: WrappedPdfiumModule, docPtr: number, pageIdx: number, pagePtr: number, ttl: number, onFinalDispose: () => void);
    /** Called by PageCache.acquire() */
    bumpRefCount(): void;
    /** Get current reference count */
    getRefCount(): number;
    /** Called by PageCache.acquire() */
    clearExpiryTimer(): void;
    /** Update TTL configuration */
    updateTtl(newTtl: number): void;
    /** Called by PageCache.release() internally */
    release(): void;
    /** Tear down _all_ sub-pointers & the page. */
    disposeImmediate(): void;
    /** Always safe: opens (once) and returns the text-page ptr. */
    getTextPage(): number;
    /** Always safe: opens (once) and returns the form-fill handle. */
    getFormHandle(): number;
    /**
     * Safely execute `fn` with an annotation pointer.
     * Pointer is ALWAYS closed afterwards.
     */
    withAnnotation<T>(annotIdx: number, fn: (annotPtr: number) => T): T;
    private ensureAlive;
}
