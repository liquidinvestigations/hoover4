import { Logger, PdfEngine as IPdfEngine, PdfDocumentObject, PdfPageObject, PdfTask, PdfErrorReason, PdfFileUrl, PdfFile, PdfOpenDocumentUrlOptions, PdfOpenDocumentBufferOptions, PdfMetadataObject, PdfBookmarksObject, PdfBookmarkObject, PdfRenderPageOptions, PdfRenderThumbnailOptions, PdfRenderPageAnnotationOptions, PdfAnnotationObject, PdfTextRectObject, PdfSearchAllPagesOptions, SearchAllPagesResult, PdfPageSearchProgress, PdfAnnotationsProgress, PdfAttachmentObject, PdfAddAttachmentParams, PdfWidgetAnnoObject, FormFieldValue, PdfFlattenPageOptions, PdfPageFlattenResult, PdfRedactTextOptions, Rect, PageTextSlice, PdfGlyphObject, PdfPageGeometry, PdfPageTextRuns, PdfPrintOptions, PdfEngineFeature, PdfEngineOperation, PdfSignatureObject, AnnotationCreateContext, CompoundTask, ImageDataLike, IPdfiumExecutor, AnnotationAppearanceMap } from '@embedpdf/models';
import { ImageDataConverter } from '../converters/types';
export type { ImageDataConverter } from '../converters/types';
export type { ImageDataLike, IPdfiumExecutor, BatchProgress } from '@embedpdf/models';
export interface PdfEngineOptions<T> {
    /**
     * Image data converter (for encoding raw image data to Blob/other format)
     */
    imageConverter: ImageDataConverter<T>;
    /**
     * Fetch function for fetching remote URLs
     */
    fetcher?: typeof fetch;
    /**
     * Logger instance
     */
    logger?: Logger;
}
/**
 * PdfEngine orchestrator
 *
 * This is the "smart" layer that:
 * - Implements the PdfEngine interface
 * - Uses WorkerTaskQueue for priority-based task scheduling
 * - Orchestrates complex multi-page operations
 * - Handles image encoding with separate encoder pool
 * - Manages visibility-based task ranking
 */
export declare class PdfEngine<T = Blob> implements IPdfEngine<T> {
    private executor;
    private workerQueue;
    private logger;
    private options;
    constructor(executor: IPdfiumExecutor, options: PdfEngineOptions<T>);
    /**
     * Split an array into chunks of a given size
     */
    private chunkArray;
    isSupport(feature: PdfEngineFeature): PdfTask<PdfEngineOperation[]>;
    destroy(): PdfTask<boolean>;
    openDocumentUrl(file: PdfFileUrl, options?: PdfOpenDocumentUrlOptions): PdfTask<PdfDocumentObject>;
    openDocumentBuffer(file: PdfFile, options?: PdfOpenDocumentBufferOptions): PdfTask<PdfDocumentObject>;
    getMetadata(doc: PdfDocumentObject): PdfTask<PdfMetadataObject>;
    setMetadata(doc: PdfDocumentObject, metadata: Partial<PdfMetadataObject>): PdfTask<boolean>;
    getDocPermissions(doc: PdfDocumentObject): PdfTask<number>;
    getDocUserPermissions(doc: PdfDocumentObject): PdfTask<number>;
    getSignatures(doc: PdfDocumentObject): PdfTask<PdfSignatureObject[]>;
    getBookmarks(doc: PdfDocumentObject): PdfTask<PdfBookmarksObject>;
    setBookmarks(doc: PdfDocumentObject, bookmarks: PdfBookmarkObject[]): PdfTask<boolean>;
    deleteBookmarks(doc: PdfDocumentObject): PdfTask<boolean>;
    renderPage(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageOptions): PdfTask<T>;
    renderPageRect(doc: PdfDocumentObject, page: PdfPageObject, rect: Rect, options?: PdfRenderPageOptions): PdfTask<T>;
    renderPageRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageOptions): PdfTask<ImageDataLike>;
    renderPageRectRaw(doc: PdfDocumentObject, page: PdfPageObject, rect: Rect, options?: PdfRenderPageOptions): PdfTask<ImageDataLike>;
    renderThumbnail(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderThumbnailOptions): PdfTask<T>;
    renderPageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: PdfRenderPageAnnotationOptions): PdfTask<T>;
    renderPageAnnotations(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageAnnotationOptions): PdfTask<AnnotationAppearanceMap<T>>;
    renderPageAnnotationsRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageAnnotationOptions): PdfTask<AnnotationAppearanceMap<ImageDataLike>>;
    /**
     * Helper to render and encode in two stages with priority queue
     */
    private renderWithEncoding;
    /**
     * Encode image using encoder pool or inline
     */
    private encodeImage;
    /**
     * Encode a full annotation appearance map to the output type T.
     */
    private encodeAppearanceMap;
    getPageAnnotations(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfAnnotationObject[]>;
    createPageAnnotation<A extends PdfAnnotationObject>(doc: PdfDocumentObject, page: PdfPageObject, annotation: A, context?: AnnotationCreateContext<A>): PdfTask<string>;
    updatePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: {
        regenerateAppearance?: boolean;
    }): PdfTask<boolean>;
    removePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): PdfTask<boolean>;
    /**
     * Get all annotations across all pages
     * Uses batched operations to reduce queue overhead
     */
    getAllAnnotations(doc: PdfDocumentObject): CompoundTask<Record<number, PdfAnnotationObject[]>, PdfErrorReason, PdfAnnotationsProgress>;
    getPageTextRects(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfTextRectObject[]>;
    /**
     * Search across all pages
     * Uses batched operations to reduce queue overhead
     */
    searchAllPages(doc: PdfDocumentObject, keyword: string, options?: PdfSearchAllPagesOptions): PdfTask<SearchAllPagesResult, PdfPageSearchProgress>;
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
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setDocumentEncryption}
     */
    setDocumentEncryption(doc: PdfDocumentObject, userPassword: string, ownerPassword: string, allowedFlags: number): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.removeEncryption}
     */
    removeEncryption(doc: PdfDocumentObject): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.unlockOwnerPermissions}
     */
    unlockOwnerPermissions(doc: PdfDocumentObject, ownerPassword: string): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.isEncrypted}
     */
    isEncrypted(doc: PdfDocumentObject): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.isOwnerUnlocked}
     */
    isOwnerUnlocked(doc: PdfDocumentObject): PdfTask<boolean>;
}
