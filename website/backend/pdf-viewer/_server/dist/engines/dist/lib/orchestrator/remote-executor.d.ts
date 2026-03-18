import { BatchProgress, Logger, PdfDocumentObject, PdfPageObject, PdfTask, PdfFile, PdfOpenDocumentBufferOptions, PdfMetadataObject, PdfBookmarksObject, PdfBookmarkObject, PdfRenderPageOptions, PdfRenderThumbnailOptions, PdfRenderPageAnnotationOptions, PdfAnnotationObject, PdfTextRectObject, PdfAttachmentObject, PdfAddAttachmentParams, PdfWidgetAnnoObject, FormFieldValue, PdfFlattenPageOptions, PdfPageFlattenResult, PdfRedactTextOptions, Rect, PageTextSlice, PdfGlyphObject, PdfPageGeometry, PdfPageTextRuns, PdfPrintOptions, PdfSignatureObject, AnnotationCreateContext, SearchResult, IPdfiumExecutor, ImageDataLike, AnnotationAppearanceMap } from '@embedpdf/models';
import { FontFallbackConfig } from '../pdfium/font-fallback';
/**
 * Options for creating a RemoteExecutor
 */
export interface RemoteExecutorOptions {
    /**
     * URL to the pdfium.wasm file (required)
     */
    wasmUrl: string;
    /**
     * Logger instance for debugging
     */
    logger?: Logger;
    /**
     * Font fallback configuration for handling missing fonts
     */
    fontFallback?: FontFallbackConfig;
}
/**
 * RemoteExecutor - Proxy for worker communication
 *
 * This implements IPdfExecutor but forwards all calls to a Web Worker.
 * It handles:
 * - Serialization/deserialization of messages
 * - Promise/Task conversion
 * - Error handling
 * - Progress tracking
 */
export declare class RemoteExecutor implements IPdfiumExecutor {
    private worker;
    private static READY_TASK_ID;
    private pendingRequests;
    private requestCounter;
    private logger;
    private readyTask;
    constructor(worker: Worker, options: RemoteExecutorOptions);
    /**
     * Generate unique request ID
     */
    private generateId;
    /**
     * Send a message to the worker and return a Task
     * Waits for worker to be ready before sending
     */
    private send;
    /**
     * Handle messages from worker
     */
    private handleMessage;
    /**
     * Cleanup and terminate worker
     */
    destroy(): void;
    openDocumentBuffer(file: PdfFile, options?: PdfOpenDocumentBufferOptions): PdfTask<PdfDocumentObject>;
    getMetadata(doc: PdfDocumentObject): PdfTask<PdfMetadataObject>;
    setMetadata(doc: PdfDocumentObject, metadata: Partial<PdfMetadataObject>): PdfTask<boolean>;
    getDocPermissions(doc: PdfDocumentObject): PdfTask<number>;
    getDocUserPermissions(doc: PdfDocumentObject): PdfTask<number>;
    getSignatures(doc: PdfDocumentObject): PdfTask<PdfSignatureObject[]>;
    getBookmarks(doc: PdfDocumentObject): PdfTask<PdfBookmarksObject>;
    setBookmarks(doc: PdfDocumentObject, bookmarks: PdfBookmarkObject[]): PdfTask<boolean>;
    deleteBookmarks(doc: PdfDocumentObject): PdfTask<boolean>;
    renderPageRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageOptions): PdfTask<ImageDataLike>;
    renderPageRect(doc: PdfDocumentObject, page: PdfPageObject, rect: Rect, options?: PdfRenderPageOptions): PdfTask<ImageDataLike>;
    renderThumbnailRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderThumbnailOptions): PdfTask<ImageDataLike>;
    renderPageAnnotationRaw(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: PdfRenderPageAnnotationOptions): PdfTask<ImageDataLike>;
    renderPageAnnotationsRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageAnnotationOptions): PdfTask<AnnotationAppearanceMap>;
    getPageAnnotationsRaw(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfAnnotationObject[]>;
    getPageAnnotations(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfAnnotationObject[]>;
    createPageAnnotation<A extends PdfAnnotationObject>(doc: PdfDocumentObject, page: PdfPageObject, annotation: A, context?: AnnotationCreateContext<A>): PdfTask<string>;
    updatePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: {
        regenerateAppearance?: boolean;
    }): PdfTask<boolean>;
    removePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): PdfTask<boolean>;
    getPageTextRects(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfTextRectObject[]>;
    searchInPage(doc: PdfDocumentObject, page: PdfPageObject, keyword: string, flags: number): PdfTask<SearchResult[]>;
    getAnnotationsBatch(doc: PdfDocumentObject, pages: PdfPageObject[]): PdfTask<Record<number, PdfAnnotationObject[]>, BatchProgress<PdfAnnotationObject[]>>;
    searchBatch(doc: PdfDocumentObject, pages: PdfPageObject[], keyword: string, flags: number): PdfTask<Record<number, SearchResult[]>, BatchProgress<SearchResult[]>>;
    getAttachments(doc: PdfDocumentObject): PdfTask<PdfAttachmentObject[]>;
    addAttachment(doc: PdfDocumentObject, params: PdfAddAttachmentParams): PdfTask<boolean>;
    removeAttachment(doc: PdfDocumentObject, attachment: PdfAttachmentObject): PdfTask<boolean>;
    readAttachmentContent(doc: PdfDocumentObject, attachment: PdfAttachmentObject): PdfTask<ArrayBuffer>;
    setFormFieldValue(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfWidgetAnnoObject, value: FormFieldValue): PdfTask<boolean>;
    flattenPage(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfFlattenPageOptions): PdfTask<PdfPageFlattenResult>;
    extractPages(doc: PdfDocumentObject, pageIndexes: number[]): PdfTask<ArrayBuffer>;
    extractText(doc: PdfDocumentObject, pageIndexes: number[]): PdfTask<string>;
    redactTextInRects(doc: PdfDocumentObject, page: PdfPageObject, rects: Rect[], options?: PdfRedactTextOptions): PdfTask<boolean>;
    applyRedaction(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): PdfTask<boolean>;
    applyAllRedactions(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<boolean>;
    flattenAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): PdfTask<boolean>;
    getTextSlices(doc: PdfDocumentObject, slices: PageTextSlice[]): PdfTask<string[]>;
    getPageGlyphs(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfGlyphObject[]>;
    getPageGeometry(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfPageGeometry>;
    getPageTextRuns(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfPageTextRuns>;
    merge(files: PdfFile[]): PdfTask<PdfFile>;
    mergePages(mergeConfigs: Array<{
        docId: string;
        pageIndices: number[];
    }>): PdfTask<PdfFile>;
    preparePrintDocument(doc: PdfDocumentObject, options?: PdfPrintOptions): PdfTask<ArrayBuffer>;
    saveAsCopy(doc: PdfDocumentObject): PdfTask<ArrayBuffer>;
    closeDocument(doc: PdfDocumentObject): PdfTask<boolean>;
    closeAllDocuments(): PdfTask<boolean>;
    setDocumentEncryption(doc: PdfDocumentObject, userPassword: string, ownerPassword: string, allowedFlags: number): PdfTask<boolean>;
    removeEncryption(doc: PdfDocumentObject): PdfTask<boolean>;
    unlockOwnerPermissions(doc: PdfDocumentObject, ownerPassword: string): PdfTask<boolean>;
    isEncrypted(doc: PdfDocumentObject): PdfTask<boolean>;
    isOwnerUnlocked(doc: PdfDocumentObject): PdfTask<boolean>;
}
