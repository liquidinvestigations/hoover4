import { FormFieldValue, PdfAttachmentObject, PdfFile, PdfMetadataObject, PdfSignatureObject, PdfTextRectObject, PdfWidgetAnnoObject, Task, Logger, PdfAnnotationObject, PdfBookmarksObject, PdfDocumentObject, PdfEngine, PdfPageObject, Rect, PdfErrorReason, PdfPageFlattenResult, SearchAllPagesResult, PdfFileUrl, PdfGlyphObject, PdfPageGeometry, PdfPageTextRuns, PageTextSlice, AnnotationCreateContext, PdfPageSearchProgress, PdfRenderThumbnailOptions, PdfSearchAllPagesOptions, PdfFlattenPageOptions, PdfRedactTextOptions, PdfRenderPageAnnotationOptions, PdfRenderPageOptions, PdfOpenDocumentUrlOptions, PdfOpenDocumentBufferOptions, PdfAnnotationsProgress, PdfPrintOptions, PdfBookmarkObject, PdfAddAttachmentParams, AnnotationAppearanceMap, ImageDataLike } from '@embedpdf/models';
import { ExecuteRequest } from './runner';
/**
 * Task that executed by webworker
 */
export declare class WorkerTask<R, P = unknown> extends Task<R, PdfErrorReason, P> {
    worker: Worker;
    private messageId;
    /**
     * Create a task that bind to web worker with specified message id
     * @param worker - web worker instance
     * @param messageId - id of message
     *
     * @public
     */
    constructor(worker: Worker, messageId: string);
    /**
     * {@inheritDoc @embedpdf/models!Task.abort}
     *
     * @override
     */
    abort(e: PdfErrorReason): void;
    /**
     * {@inheritDoc @embedpdf/models!Task.progress}
     *
     * @override
     */
    progress(p: P): void;
}
/**
 * PDF engine that runs within webworker
 */
export declare class WebWorkerEngine implements PdfEngine {
    private worker;
    private logger;
    static readyTaskId: string;
    /**
     * Task that represent the state of preparation
     */
    readyTask: WorkerTask<boolean>;
    /**
     * All the tasks that is executing
     */
    tasks: Map<string, WorkerTask<any>>;
    /**
     * Create an instance of WebWorkerEngine, it will create a worker with
     * specified url.
     * @param worker - webworker instance, this worker needs to contains the running instance of {@link EngineRunner}
     * @param logger - logger instance
     *
     * @public
     */
    constructor(worker: Worker, logger?: Logger);
    /**
     * Handle event from web worker. There are 2 kinds of event
     * 1. ReadyResponse: web worker is ready
     * 2. ExecuteResponse: result of execution
     * @param evt - message event from web worker
     * @returns
     *
     * @private
     */
    handle: (evt: MessageEvent<any>) => void;
    /**
     * Generate a unique message id
     * @returns message id
     *
     * @private
     */
    generateRequestId(id: string): string;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.destroy}
     *
     * @public
     */
    destroy(): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.openDocumentUrl}
     *
     * @public
     */
    openDocumentUrl(file: PdfFileUrl, options?: PdfOpenDocumentUrlOptions): WorkerTask<PdfDocumentObject, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.openDocument}
     *
     * @public
     */
    openDocumentBuffer(file: PdfFile, options?: PdfOpenDocumentBufferOptions): WorkerTask<PdfDocumentObject, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getMetadata}
     *
     * @public
     */
    getMetadata(doc: PdfDocumentObject): WorkerTask<PdfMetadataObject, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setMetadata}
     *
     * @public
     */
    setMetadata(doc: PdfDocumentObject, metadata: Partial<PdfMetadataObject>): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getDocPermissions}
     *
     * @public
     */
    getDocPermissions(doc: PdfDocumentObject): WorkerTask<number, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getDocUserPermissions}
     *
     * @public
     */
    getDocUserPermissions(doc: PdfDocumentObject): WorkerTask<number, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getBookmarks}
     *
     * @public
     */
    getBookmarks(doc: PdfDocumentObject): WorkerTask<PdfBookmarksObject, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setBookmarks}
     *
     * @public
     */
    setBookmarks(doc: PdfDocumentObject, payload: PdfBookmarkObject[]): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.deleteBookmarks}
     *
     * @public
     */
    deleteBookmarks(doc: PdfDocumentObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getSignatures}
     *
     * @public
     */
    getSignatures(doc: PdfDocumentObject): WorkerTask<PdfSignatureObject[], unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderPage}
     *
     * @public
     */
    renderPage(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageOptions): WorkerTask<Blob, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRect}
     *
     * @public
     */
    renderPageRect(doc: PdfDocumentObject, page: PdfPageObject, rect: Rect, options?: PdfRenderPageOptions): WorkerTask<Blob, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRaw}
     *
     * @public
     */
    renderPageRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageOptions): WorkerTask<ImageDataLike, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRectRaw}
     *
     * @public
     */
    renderPageRectRaw(doc: PdfDocumentObject, page: PdfPageObject, rect: Rect, options?: PdfRenderPageOptions): WorkerTask<ImageDataLike, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderAnnotation}
     *
     * @public
     */
    renderPageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: PdfRenderPageAnnotationOptions): WorkerTask<Blob, unknown>;
    renderPageAnnotations(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageAnnotationOptions): WorkerTask<AnnotationAppearanceMap<Blob>, unknown>;
    renderPageAnnotationsRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageAnnotationOptions): WorkerTask<AnnotationAppearanceMap<ImageDataLike>, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getAllAnnotations}
     *
     * @public
     */
    getAllAnnotations(doc: PdfDocumentObject): WorkerTask<Record<number, PdfAnnotationObject[]>, PdfAnnotationsProgress>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getPageAnnotations}
     *
     * @public
     */
    getPageAnnotations(doc: PdfDocumentObject, page: PdfPageObject): WorkerTask<PdfAnnotationObject[], unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.createPageAnnotation}
     *
     * @public
     */
    createPageAnnotation<A extends PdfAnnotationObject>(doc: PdfDocumentObject, page: PdfPageObject, annotation: A, context?: AnnotationCreateContext<A>): WorkerTask<string, unknown>;
    updatePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: {
        regenerateAppearance?: boolean;
    }): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.removePageAnnotation}
     *
     * @public
     */
    removePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getPageTextRects}
     *
     * @public
     */
    getPageTextRects(doc: PdfDocumentObject, page: PdfPageObject): WorkerTask<PdfTextRectObject[], unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderThumbnail}
     *
     * @public
     */
    renderThumbnail(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderThumbnailOptions): WorkerTask<Blob, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.searchAllPages}
     *
     * @public
     */
    searchAllPages(doc: PdfDocumentObject, keyword: string, options?: PdfSearchAllPagesOptions): WorkerTask<SearchAllPagesResult, PdfPageSearchProgress>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.saveAsCopy}
     *
     * @public
     */
    saveAsCopy(doc: PdfDocumentObject): WorkerTask<ArrayBuffer, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getAttachments}
     *
     * @public
     */
    getAttachments(doc: PdfDocumentObject): WorkerTask<PdfAttachmentObject[], unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.addAttachment}
     *
     * @public
     */
    addAttachment(doc: PdfDocumentObject, params: PdfAddAttachmentParams): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.removeAttachment}
     *
     * @public
     */
    removeAttachment(doc: PdfDocumentObject, attachment: PdfAttachmentObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.readAttachmentContent}
     *
     * @public
     */
    readAttachmentContent(doc: PdfDocumentObject, attachment: PdfAttachmentObject): WorkerTask<ArrayBuffer, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setFormFieldValue}
     *
     * @public
     */
    setFormFieldValue(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfWidgetAnnoObject, value: FormFieldValue): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.flattenPage}
     *
     * @public
     */
    flattenPage(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfFlattenPageOptions): WorkerTask<PdfPageFlattenResult, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.extractPages}
     *
     * @public
     */
    extractPages(doc: PdfDocumentObject, pageIndexes: number[]): WorkerTask<ArrayBuffer, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.redactTextInQuads}
     *
     * @public
     */
    redactTextInRects(doc: PdfDocumentObject, page: PdfPageObject, rects: Rect[], options?: PdfRedactTextOptions): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.applyRedaction}
     *
     * @public
     */
    applyRedaction(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.applyAllRedactions}
     *
     * @public
     */
    applyAllRedactions(doc: PdfDocumentObject, page: PdfPageObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.flattenAnnotation}
     *
     * @public
     */
    flattenAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.extractText}
     *
     * @public
     */
    extractText(doc: PdfDocumentObject, pageIndexes: number[]): WorkerTask<string, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getTextSlices}
     *
     * @public
     */
    getTextSlices(doc: PdfDocumentObject, slices: PageTextSlice[]): WorkerTask<string[], unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getPageGlyphs}
     *
     * @public
     */
    getPageGlyphs(doc: PdfDocumentObject, page: PdfPageObject): WorkerTask<PdfGlyphObject[], unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getPageGeometry}
     *
     * @public
     */
    getPageGeometry(doc: PdfDocumentObject, page: PdfPageObject): WorkerTask<PdfPageGeometry, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getPageTextRuns}
     *
     * @public
     */
    getPageTextRuns(doc: PdfDocumentObject, page: PdfPageObject): WorkerTask<PdfPageTextRuns, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.merge}
     *
     * @public
     */
    merge(files: PdfFile[]): WorkerTask<PdfFile, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.mergePages}
     *
     * @public
     */
    mergePages(mergeConfigs: Array<{
        docId: string;
        pageIndices: number[];
    }>): WorkerTask<PdfFile, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.preparePrintDocument}
     *
     * @public
     */
    preparePrintDocument(doc: PdfDocumentObject, options?: PdfPrintOptions): WorkerTask<ArrayBuffer, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.closeDocument}
     *
     * @public
     */
    closeDocument(doc: PdfDocumentObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.closeAllDocuments}
     *
     * @public
     */
    closeAllDocuments(): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setDocumentEncryption}
     *
     * @public
     */
    setDocumentEncryption(doc: PdfDocumentObject, userPassword: string, ownerPassword: string, allowedFlags: number): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.removeEncryption}
     *
     * @public
     */
    removeEncryption(doc: PdfDocumentObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.unlockOwnerPermissions}
     *
     * @public
     */
    unlockOwnerPermissions(doc: PdfDocumentObject, ownerPassword: string): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.isEncrypted}
     *
     * @public
     */
    isEncrypted(doc: PdfDocumentObject): WorkerTask<boolean, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.isOwnerUnlocked}
     *
     * @public
     */
    isOwnerUnlocked(doc: PdfDocumentObject): WorkerTask<boolean, unknown>;
    /**
     * Send the request to webworker inside and register the task
     * @param task - task that waiting for the response
     * @param request - request that needs send to web worker
     * @param transferables - transferables that need to transfer to webworker
     * @returns
     *
     * @internal
     */
    proxy<R>(task: WorkerTask<R>, request: ExecuteRequest, transferables?: any[]): void;
}
