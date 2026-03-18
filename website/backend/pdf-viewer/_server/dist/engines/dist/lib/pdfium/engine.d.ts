import { BatchProgress, ImageDataLike, IPdfiumExecutor, PdfAnnotationObject, PdfTextRectObject, PdfWidgetAnnoObject, Logger, SearchResult, PdfBookmarkObject, PdfDocumentObject, PdfPageObject, Rect, PdfAttachmentObject, PdfSignatureObject, PdfStampAnnoObject, PdfCircleAnnoObject, PdfSquareAnnoObject, PdfSquigglyAnnoObject, PdfStrikeOutAnnoObject, PdfUnderlineAnnoObject, PdfFile, PdfHighlightAnnoObject, FormFieldValue, PdfPageFlattenResult, PdfTask, PdfOpenDocumentBufferOptions, Task, PdfErrorReason, PdfGlyphObject, PdfPageGeometry, PageTextSlice, AnnotationCreateContext, PdfRenderPageAnnotationOptions, PdfRedactTextOptions, PdfFlattenPageOptions, PdfRenderThumbnailOptions, PdfRenderPageOptions, PdfMetadataObject, PdfPrintOptions, PdfAddAttachmentParams, AnnotationAppearanceMap, PdfPageTextRuns } from '@embedpdf/models';
import { WrappedPdfiumModule } from '@embedpdf/pdfium';
import { FontFallbackManager, FontFallbackConfig } from './font-fallback';
/**
 * Format of bitmap
 */
export declare enum BitmapFormat {
    Bitmap_Gray = 1,
    Bitmap_BGR = 2,
    Bitmap_BGRx = 3,
    Bitmap_BGRA = 4
}
/**
 * Pdf rendering flag
 */
export declare enum RenderFlag {
    ANNOT = 1,// Set if annotations are to be rendered.
    LCD_TEXT = 2,// Set if using text rendering optimized for LCD display.
    NO_NATIVETEXT = 4,// Don't use the native text output available on some platforms
    GRAYSCALE = 8,// Grayscale output.
    DEBUG_INFO = 128,// Set if you want to get some debug info. Please discuss with Foxit first if you need to collect debug info.
    NO_CATCH = 256,// Set if you don't want to catch exception.
    RENDER_LIMITEDIMAGECACHE = 512,// Limit image cache size.
    RENDER_FORCEHALFTONE = 1024,// Always use halftone for image stretching.
    PRINTING = 2048,// Render for printing.
    REVERSE_BYTE_ORDER = 16
}
/**
 * Error code of pdfium library
 */
export declare enum PdfiumErrorCode {
    Success = 0,
    Unknown = 1,
    File = 2,
    Format = 3,
    Password = 4,
    Security = 5,
    Page = 6,
    XFALoad = 7,
    XFALayout = 8
}
export interface PdfiumEngineOptions {
    logger?: Logger;
    /**
     * Font fallback configuration for handling missing fonts in PDFs.
     * When enabled, PDFium will request fallback fonts from configured URLs
     * when it encounters text that requires fonts not embedded in the PDF.
     */
    fontFallback?: FontFallbackConfig;
}
/**
 * Pdf engine that based on pdfium wasm
 */
export declare class PdfiumNative implements IPdfiumExecutor {
    private pdfiumModule;
    /**
     * pdf documents that opened
     */
    private readonly cache;
    /**
     * memory manager instance
     */
    private readonly memoryManager;
    /**
     * interval to check memory leaks
     */
    private memoryLeakCheckInterval;
    /**
     * logger instance
     */
    private logger;
    /**
     * font fallback manager instance
     */
    private fontFallbackManager;
    /**
     * Create an instance of PdfiumNative and initialize PDFium
     * @param wasmModule - pdfium wasm module
     * @param options - configuration options
     */
    constructor(pdfiumModule: WrappedPdfiumModule, options?: PdfiumEngineOptions);
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.destroy}
     *
     * @public
     */
    destroy(): Task<boolean, PdfErrorReason, unknown>;
    /**
     * Get the font fallback manager instance
     * Useful for pre-loading fonts or checking stats
     */
    getFontFallbackManager(): FontFallbackManager | null;
    /** Write a UTF-16LE (WIDESTRING) to wasm, call `fn(ptr)`, then free. */
    private withWString;
    /** Write a float[] to wasm, call `fn(ptr, count)`, then free. */
    private withFloatArray;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.openDocument}
     *
     * @public
     */
    openDocumentBuffer(file: PdfFile, options?: PdfOpenDocumentBufferOptions): Task<PdfDocumentObject, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getMetadata}
     *
     * @public
     */
    getMetadata(doc: PdfDocumentObject): PdfTask<PdfMetadataObject>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setMetadata}
     *
     * @public
     */
    setMetadata(doc: PdfDocumentObject, meta: Partial<PdfMetadataObject>): Task<any, PdfErrorReason, unknown> | Task<boolean, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getDocPermissions}
     *
     * @public
     */
    getDocPermissions(doc: PdfDocumentObject): Task<any, PdfErrorReason, unknown> | Task<number, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getDocUserPermissions}
     *
     * @public
     */
    getDocUserPermissions(doc: PdfDocumentObject): Task<any, PdfErrorReason, unknown> | Task<number, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getSignatures}
     *
     * @public
     */
    getSignatures(doc: PdfDocumentObject): Task<any, PdfErrorReason, unknown> | Task<PdfSignatureObject[], PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getBookmarks}
     *
     * @public
     */
    getBookmarks(doc: PdfDocumentObject): Task<any, PdfErrorReason, unknown> | Task<{
        bookmarks: PdfBookmarkObject[];
    }, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setBookmarks}
     *
     * @public
     */
    setBookmarks(doc: PdfDocumentObject, list: PdfBookmarkObject[]): Task<any, PdfErrorReason, unknown> | Task<boolean, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.deleteBookmarks}
     *
     * @public
     */
    deleteBookmarks(doc: PdfDocumentObject): Task<any, PdfErrorReason, unknown> | Task<boolean, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderPage}
     *
     * @public
     */
    renderPageRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageOptions): PdfTask<ImageDataLike>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRect}
     *
     * @public
     */
    renderPageRect(doc: PdfDocumentObject, page: PdfPageObject, rect: Rect, options?: PdfRenderPageOptions): PdfTask<ImageDataLike>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getPageAnnotations}
     *
     * @public
     */
    getPageAnnotations(doc: PdfDocumentObject, page: PdfPageObject): Task<any, PdfErrorReason, unknown> | Task<PdfAnnotationObject[], PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.createPageAnnotation}
     *
     * @public
     */
    createPageAnnotation<A extends PdfAnnotationObject>(doc: PdfDocumentObject, page: PdfPageObject, annotation: A, context?: AnnotationCreateContext<A>): PdfTask<string>;
    /**
     * Update an existing page annotation in-place
     *
     *  • Locates the annot by page-local index (`annotation.id`)
     *  • Re-writes its /Rect and type-specific payload
     *  • Calls FPDFPage_GenerateContent so the new appearance is rendered
     *
     * @returns PdfTask<boolean>  –  true on success
     */
    updatePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: {
        regenerateAppearance?: boolean;
    }): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.removePageAnnotation}
     *
     * @public
     */
    removePageAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): Task<any, PdfErrorReason, unknown> | Task<boolean, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getPageTextRects}
     *
     * @public
     */
    getPageTextRects(doc: PdfDocumentObject, page: PdfPageObject): Task<any, PdfErrorReason, unknown> | Task<PdfTextRectObject[], PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderThumbnail}
     *
     * @public
     */
    renderThumbnailRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderThumbnailOptions): PdfTask<ImageDataLike>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getAttachments}
     *
     * @public
     */
    getAttachments(doc: PdfDocumentObject): Task<any, PdfErrorReason, unknown> | Task<PdfAttachmentObject[], PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.addAttachment}
     *
     * @public
     */
    addAttachment(doc: PdfDocumentObject, params: PdfAddAttachmentParams): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.removeAttachment}
     *
     * @public
     */
    removeAttachment(doc: PdfDocumentObject, attachment: PdfAttachmentObject): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.readAttachmentContent}
     *
     * @public
     */
    readAttachmentContent(doc: PdfDocumentObject, attachment: PdfAttachmentObject): Task<any, PdfErrorReason, unknown> | Task<ArrayBuffer, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.setFormFieldValue}
     *
     * @public
     */
    setFormFieldValue(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfWidgetAnnoObject, value: FormFieldValue): Task<any, PdfErrorReason, unknown> | Task<boolean, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.flattenPage}
     *
     * @public
     */
    flattenPage(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfFlattenPageOptions): PdfTask<PdfPageFlattenResult>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.extractPages}
     *
     * @public
     */
    extractPages(doc: PdfDocumentObject, pageIndexes: number[]): Task<any, PdfErrorReason, unknown> | Task<ArrayBuffer, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.extractText}
     *
     * @public
     */
    extractText(doc: PdfDocumentObject, pageIndexes: number[]): Task<any, PdfErrorReason, unknown> | Task<string, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.getTextSlices}
     *
     * @public
     */
    getTextSlices(doc: PdfDocumentObject, slices: PageTextSlice[]): PdfTask<string[]>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.merge}
     *
     * @public
     */
    merge(files: PdfFile[]): Task<any, PdfErrorReason, unknown> | Task<PdfFile, PdfErrorReason, unknown>;
    /**
     * Merges specific pages from multiple PDF documents in a custom order
     *
     * @param mergeConfigs Array of configurations specifying which pages to merge from which documents
     * @returns A PdfTask that resolves with the merged PDF file
     * @public
     */
    mergePages(mergeConfigs: Array<{
        docId: string;
        pageIndices: number[];
    }>): Task<any, PdfErrorReason, unknown> | Task<PdfFile, PdfErrorReason, unknown>;
    /**
     * Sets AES-256 encryption on a document.
     * Must be called before saveAsCopy() for encryption to take effect.
     *
     * @param doc - Document to encrypt
     * @param userPassword - Password to open document (empty = no open password)
     * @param ownerPassword - Password to change permissions (required)
     * @param allowedFlags - OR'd PdfPermissionFlag values indicating allowed actions
     * @returns true on success, false if already encrypted or invalid params
     *
     * @public
     */
    setDocumentEncryption(doc: PdfDocumentObject, userPassword: string, ownerPassword: string, allowedFlags: number): PdfTask<boolean>;
    /**
     * Marks document for encryption removal on save.
     * When saveAsCopy is called, the document will be saved without encryption.
     *
     * @param doc - Document to remove encryption from
     * @returns true on success
     *
     * @public
     */
    removeEncryption(doc: PdfDocumentObject): PdfTask<boolean>;
    /**
     * Attempts to unlock owner permissions for an already-opened encrypted document.
     *
     * @param doc - Document to unlock
     * @param ownerPassword - The owner password
     * @returns true on success, false on failure
     *
     * @public
     */
    unlockOwnerPermissions(doc: PdfDocumentObject, ownerPassword: string): PdfTask<boolean>;
    /**
     * Check if a document is encrypted.
     *
     * @param doc - Document to check
     * @returns true if the document is encrypted
     *
     * @public
     */
    isEncrypted(doc: PdfDocumentObject): PdfTask<boolean>;
    /**
     * Check if owner permissions are currently unlocked.
     *
     * @param doc - Document to check
     * @returns true if owner permissions are unlocked
     *
     * @public
     */
    isOwnerUnlocked(doc: PdfDocumentObject): PdfTask<boolean>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.saveAsCopy}
     *
     * @public
     */
    saveAsCopy(doc: PdfDocumentObject): Task<any, PdfErrorReason, unknown> | Task<ArrayBuffer, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.closeDocument}
     *
     * @public
     */
    closeDocument(doc: PdfDocumentObject): Task<boolean, PdfErrorReason, unknown>;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.closeAllDocuments}
     *
     * @public
     */
    closeAllDocuments(): Task<boolean, PdfErrorReason, unknown>;
    /**
     * Add text content to annotation
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to text annotation
     * @param annotation - text annotation
     * @returns whether text content is added to annotation
     *
     * @private
     */
    private addTextContent;
    /**
     * Add caret content to annotation
     * @param doc - document object
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to caret annotation
     * @param annotation - caret annotation
     * @returns whether caret content is added to annotation
     *
     * @private
     */
    private addCaretContent;
    /**
     * Add free text content to annotation
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to free text annotation
     * @param annotation - free text annotation
     * @returns whether free text content is added to annotation
     *
     * @private
     */
    private addFreeTextContent;
    /**
     * Set the rect of specified annotation
     * @param page - page info that the annotation is belonged to
     * @param pagePtr - pointer of page object
     * @param annotationPtr - pointer to annotation object
     * @param inkList - ink lists that added to the annotation
     * @returns whether the ink lists is setted
     *
     * @private
     */
    private addInkStroke;
    /**
     * Add line content to annotation
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to line annotation
     * @param annotation - line annotation
     * @returns whether line content is added to annotation
     *
     * @private
     */
    private addLineContent;
    /**
     * Add polygon or polyline content to annotation
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to polygon or polyline annotation
     * @param annotation - polygon or polyline annotation
     * @returns whether polygon or polyline content is added to annotation
     *
     * @private
     */
    private addPolyContent;
    /**
     * Add link content (action or destination) to a link annotation
     * @param docPtr - pointer to pdf document
     * @param pagePtr - pointer to the page
     * @param annotationPtr - pointer to pdf annotation
     * @param annotation - the link annotation object
     * @returns true if successful
     *
     * @private
     */
    private addLinkContent;
    /**
     * Add shape content to annotation
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to shape annotation
     * @param annotation - shape annotation
     * @returns whether shape content is added to annotation
     *
     * @private
     */
    addShapeContent(doc: PdfDocumentObject, page: PdfPageObject, pagePtr: number, annotationPtr: number, annotation: PdfCircleAnnoObject | PdfSquareAnnoObject): boolean;
    /**
     * Add highlight content to annotation
     * @param page - page info
     * @param annotationPtr - pointer to highlight annotation
     * @param annotation - highlight annotation
     * @returns whether highlight content is added to annotation
     *
     * @private
     */
    addTextMarkupContent(doc: PdfDocumentObject, page: PdfPageObject, pagePtr: number, annotationPtr: number, annotation: PdfHighlightAnnoObject | PdfUnderlineAnnoObject | PdfStrikeOutAnnoObject | PdfSquigglyAnnoObject): boolean;
    /**
     * Add content to redact annotation
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to redact annotation
     * @param annotation - redact annotation
     * @returns whether redact content is added to annotation
     *
     * @private
     */
    private addRedactContent;
    /**
     * Add contents to stamp annotation
     * @param doc - pdf document object
     * @param docPtr - pointer to pdf document object
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to stamp annotation
     * @param rect - rect of stamp annotation
     * @param contents - contents of stamp annotation
     * @returns whether contents is added to annotation
     *
     * @private
     */
    addStampContent(doc: PdfDocumentObject, docPtr: number, page: PdfPageObject, pagePtr: number, annotationPtr: number, annotation: PdfStampAnnoObject, imageData?: ImageData): boolean;
    /**
     * Add image object to annotation
     * @param doc - pdf document object
     * @param docPtr - pointer to pdf document object
     * @param page - page info
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to stamp annotation
     * @param position - position of image
     * @param imageData - data of image
     * @returns whether image is added to annotation
     *
     * @private
     */
    addImageObject(doc: PdfDocumentObject, docPtr: number, page: PdfPageObject, pagePtr: number, annotationPtr: number, rect: Rect, imageData: ImageData): boolean;
    /**
     * Save document to array buffer
     * @param docPtr - pointer to pdf document
     * @returns array buffer contains the pdf content
     *
     * @private
     */
    saveDocument(docPtr: number): ArrayBuffer;
    /**
     * Read Catalog /Lang via EPDFCatalog_GetLanguage (UTF-16LE → JS string).
     * Returns:
     *   null  -> /Lang not present (getter returned 0) OR doc not open,
     *   ''    -> /Lang exists but is explicitly empty,
     *   'en', 'en-US', ... -> normal tag.
     *
     * Note: EPDFCatalog_GetLanguage lengths are BYTES (incl. trailing NUL).
     *
     * @private
     */
    private readCatalogLanguage;
    /**
     * Read metadata from pdf document
     * @param docPtr - pointer to pdf document
     * @param key - key of metadata field
     * @returns metadata value
     *
     * @private
     */
    private readMetaText;
    /**
     * Write metadata into the PDF's Info dictionary.
     * If `value` is null or empty string, the key is removed.
     * @param docPtr - pointer to pdf document
     * @param key - key of metadata field
     * @param value - value of metadata field
     * @returns whether metadata is written to the pdf document
     *
     * @private
     */
    private setMetaText;
    /**
     * Read the document's trapped status via PDFium.
     * Falls back to `Unknown` on unexpected values.
     *
     * @private
     */
    private getMetaTrapped;
    /**
     * Write (or clear) the document's trapped status via PDFium.
     * Pass `null`/`undefined` to remove the `/Trapped` key.
     *
     * @private
     */
    private setMetaTrapped;
    /**
     * Get the number of keys in the document's Info dictionary.
     * @param docPtr - pointer to pdf document
     * @param customOnly - if true, only count non-reserved (custom) keys; if false, count all keys.
     * @returns the number of keys (possibly 0). On error, returns 0.
     *
     * @private
     */
    private getMetaKeyCount;
    /**
     * Get the name of the Info dictionary key at |index|.
     * @param docPtr - pointer to pdf document
     * @param index - 0-based key index in the order returned by PDFium.
     * @param customOnly - if true, indexes only over non-reserved (custom) keys; if false, indexes over all keys.
     * @returns the name of the key, or null if the key is not found.
     *
     * @private
     */
    private getMetaKeyName;
    /**
     * Read all metadata from the document's Info dictionary.
     * @param docPtr - pointer to pdf document
     * @param customOnly - if true, only read non-reserved (custom) keys; if false, read all keys.
     * @returns all metadata
     *
     * @private
     */
    private readAllMeta;
    /**
     * Read bookmarks in the pdf document
     * @param docPtr - pointer to pdf document
     * @param rootBookmarkPtr - pointer to root bookmark
     * @returns bookmarks in the pdf document
     *
     * @private
     */
    readPdfBookmarks(docPtr: number, rootBookmarkPtr?: number): PdfBookmarkObject[];
    /**
     * Read bookmark in the pdf document
     * @param docPtr - pointer to pdf document
     * @param bookmarkPtr - pointer to bookmark object
     * @returns pdf bookmark object
     *
     * @private
     */
    private readPdfBookmark;
    /**
     * Read text rects in pdf page
     * @param page - pdf page info
     * @param docPtr - pointer to pdf document
     * @param pagePtr - pointer to pdf page
     * @param textPagePtr - pointer to pdf text page
     * @returns text rects in the pdf page
     *
     * @public
     */
    private readPageTextRects;
    /**
     * Return geometric + logical text layout for one page
     * (glyph-only implementation, no FPDFText_GetRect).
     *
     * @public
     */
    getPageGeometry(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfPageGeometry>;
    /**
     * Group consecutive glyphs that belong to the same CPDF_TextObject
     * using FPDFText_GetTextObject(), and calculate rotation from glyph positions.
     */
    private buildRunsFromGlyphs;
    /**
     * Rich text runs: groups consecutive characters sharing the same
     * text object, font, size, and fill color into structured segments
     * with full font metadata and bounding boxes in PDF page coordinates.
     *
     * @public
     */
    getPageTextRuns(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfPageTextRuns>;
    /**
     * Read font metadata from a text object handle via FPDFFont_* APIs.
     */
    private readFontInfoFromTextObject;
    /**
     * Extract glyph geometry + metadata for `charIndex`
     *
     * Returns device–space coordinates:
     *   x,y  → **top-left** corner (integer-pixels)
     *   w,h  → width / height (integer-pixels, ≥ 1)
     *
     * And two flags:
     *   isSpace → true if the glyph's Unicode code-point is U+0020
     */
    private readGlyphInfo;
    /**
     * Geometry-only text extraction
     * ------------------------------------------
     * Returns every glyph on the requested page
     * in the logical order delivered by PDFium.
     *
     * The promise resolves to an array of objects:
     *   {
     *     idx:     number;            // glyph index on the page (0…n-1)
     *     origin:  { x: number; y: number };
     *     size:    { width: number;  height: number };
     *     angle:   number;            // degrees, counter-clock-wise
     *     isSpace: boolean;           // true  → U+0020
     *   }
     *
     * No Unicode is included; front-end decides whether to hydrate it.
     */
    getPageGlyphs(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfGlyphObject[]>;
    private readCharBox;
    /**
     * Read page annotations
     *
     * @param doc - pdf document object
     * @param ctx - document context
     * @param page - page info
     * @returns annotations on the pdf page
     *
     * @private
     */
    private readPageAnnotations;
    /**
     * Read page annotations without loading the page (raw approach)
     *
     * @param doc - pdf document object
     * @param ctx - document context
     * @param page - page info
     * @returns annotations on the pdf page
     *
     * @private
     */
    private readPageAnnotationsRaw;
    /**
     * Get page annotations (public API, returns Task)
     *
     * @param doc - pdf document
     * @param page - page info
     * @returns task with annotations on the pdf page
     *
     * @public
     */
    getPageAnnotationsRaw(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<PdfAnnotationObject[]>;
    /**
     * Read pdf annotation from pdf document
     *
     * @param doc - pdf document object
     * @param docPtr - pointer to pdf document
     * @param page - page info
     * @param annotationPtr - pointer to pdf annotation
     * @param pageCtx - page context
     * @returns pdf annotation
     *
     * @private
     */
    private readPageAnnotation;
    /**
     * On load, if a vertex-type annotation has rotation metadata in EPDFCustom,
     * reverse-rotate the PDF's physically rotated vertices by -rotation to recover
     * the unrotated vertices for runtime editing.
     */
    private reverseRotateAnnotationOnLoad;
    /**
     * Return the colour stored directly in the annotation dictionary's `/C` entry.
     *
     * Most PDFs created by Acrobat, Microsoft Office, LaTeX, etc. include this entry.
     * When the key is absent (common in macOS Preview, Chrome, Drawboard) the call
     * fails and the function returns `undefined`.
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @returns An RGBA tuple (0-255 channels) or `undefined` if no `/C` entry exists
     *
     * @private
     */
    private readAnnotationColor;
    /**
     * Get the fill/stroke colour annotation.
     *
     * @param annotationPtr - pointer to the annotation whose colour is being set
     * @param colorType - which colour to get (0 = fill, 1 = stroke)
     * @returns WebColor with hex color
     *
     * @private
     */
    private getAnnotationColor;
    /**
     * Set the fill/stroke colour for a **Highlight / Underline / StrikeOut / Squiggly** markup annotation.
     *
     * @param annotationPtr - pointer to the annotation whose colour is being set
     * @param webAlphaColor - WebAlphaColor with hex color and opacity (0-1)
     * @param shouldClearAP - whether to clear the /AP entry
     * @param which - which colour to set (0 = fill, 1 = stroke)
     * @returns `true` if the operation was successful
     *
     * @private
     */
    private setAnnotationColor;
    /**
     * Get the opacity of the annotation.
     *
     * @param annotationPtr - pointer to the annotation whose opacity is being set
     * @returns opacity (0-1)
     *
     * @private
     */
    private getAnnotationOpacity;
    /**
     * Set the opacity of the annotation.
     *
     * @param annotationPtr - pointer to the annotation whose opacity is being set
     * @param opacity - opacity (0-1)
     * @returns true on success
     *
     * @private
     */
    private setAnnotationOpacity;
    /**
     * Get the rotation angle (in degrees) from the annotation's /Rotate entry.
     * Returns 0 if no rotation is set or on error.
     *
     * @param annotationPtr - pointer to the annotation
     * @returns rotation in degrees (0 if not set)
     */
    private getAnnotationRotation;
    /**
     * Set the rotation angle (in degrees) on the annotation's /Rotate entry.
     * A value of 0 removes the /Rotate key.
     *
     * @param annotationPtr - pointer to the annotation
     * @param rotation - rotation in degrees (clockwise)
     * @returns true on success
     */
    private setAnnotationRotation;
    /**
     * Get the EmbedPDF extended rotation (in degrees) from the annotation's
     * /EPDFRotate entry. Returns 0 if not set or on error.
     *
     * @param annotationPtr - pointer to the annotation
     * @returns rotation in degrees (0 if not set)
     */
    private getAnnotExtendedRotation;
    /**
     * Set the EmbedPDF extended rotation (in degrees) on the annotation's
     * /EPDFRotate entry. A value of 0 removes the key.
     *
     * @param annotationPtr - pointer to the annotation
     * @param rotation - rotation in degrees
     * @returns true on success
     */
    private setAnnotExtendedRotation;
    /**
     * Read the EmbedPDF unrotated rect from the annotation's /EPDFUnrotatedRect
     * entry. Returns the raw page-space rect (same format as `readPageAnnoRect`)
     * or null if not set.
     *
     * @param annotationPtr - pointer to the annotation
     * @returns raw `{ left, top, right, bottom }` in page coords, or null
     */
    private readAnnotUnrotatedRect;
    /**
     * Write the EmbedPDF unrotated rect (/EPDFUnrotatedRect) for an annotation.
     * Accepts a device-space `Rect` and converts to page coordinates internally,
     * following the same pattern as `setPageAnnoRect`.
     *
     * @param doc  - pdf document object
     * @param page - pdf page object
     * @param annotPtr - pointer to the annotation
     * @param rect - device-space rect to store as the unrotated rect
     * @returns true on success
     */
    private setAnnotUnrotatedRect;
    /**
     * Fetch the `/Q` text-alignment value from a **FreeText** annotation.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @returns `PdfTextAlignment`
     */
    private getAnnotationTextAlignment;
    /**
     * Write the `/Q` text-alignment value into a **FreeText** annotation
     * and clear the existing appearance stream so it can be regenerated.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @param alignment     `PdfTextAlignment`
     * @returns `true` on success
     */
    private setAnnotationTextAlignment;
    /**
     * Fetch the `/EPDF:VerticalAlignment` vertical-alignment value from a **FreeText** annotation.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @returns `PdfVerticalAlignment`
     */
    private getAnnotationVerticalAlignment;
    /**
     * Write the `/EPDF:VerticalAlignment` vertical-alignment value into a **FreeText** annotation
     * and clear the existing appearance stream so it can be regenerated.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @param alignment     `PdfVerticalAlignment`
     * @returns `true` on success
     */
    private setAnnotationVerticalAlignment;
    /**
     * Get the overlay text from a Redact annotation.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @returns overlay text string or `undefined` if not set
     *
     * @private
     */
    private getOverlayText;
    /**
     * Set the overlay text on a Redact annotation.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @param text overlay text to set, or undefined/empty to clear
     * @returns `true` on success
     *
     * @private
     */
    private setOverlayText;
    /**
     * Get whether overlay text repeats in a Redact annotation.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @returns `true` if overlay text repeats
     *
     * @private
     */
    private getOverlayTextRepeat;
    /**
     * Set whether overlay text repeats in a Redact annotation.
     *
     * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
     * @param repeat whether overlay text should repeat
     * @returns `true` on success
     *
     * @private
     */
    private setOverlayTextRepeat;
    /**
     * Return the **default appearance** (font, size, colour) declared in the
     * `/DA` string of a **FreeText** annotation.
     *
     * @param annotationPtr  pointer to `FPDF_ANNOTATION`
     * @returns `{ font, fontSize, color }` or `undefined` when PDFium returns false
     *
     * NOTE – `font` is the raw `FPDF_STANDARD_FONT` enum value that PDFium uses
     *        (same range as the C API: 0 = Courier, 12 = ZapfDingbats, …).
     */
    private getAnnotationDefaultAppearance;
    /**
     * Write a **default appearance** (`/DA`) into a FreeText annotation.
     *
     * @param annotationPtr pointer to `FPDF_ANNOTATION`
     * @param font          `FPDF_STANDARD_FONT` enum value
     * @param fontSize      size in points (≥ 0)
     * @param color         CSS-style `#rrggbb` string (alpha ignored)
     * @returns `true` on success
     */
    private setAnnotationDefaultAppearance;
    /**
     * Border‐style + width helper
     *
     * Tries the new PDFium helper `EPDFAnnot_GetBorderStyle()` (patch series
     * 9 July 2025).
     *
     * @param  annotationPtr  pointer to an `FPDF_ANNOTATION`
     * @returns `{ ok, style, width }`
     *          • `ok`     – `true` when the call succeeded
     *          • `style`  – `PdfAnnotationBorderStyle` enum
     *          • `width`  – stroke-width in points (defaults to 0 pt)
     */
    private getBorderStyle;
    private setBorderStyle;
    /**
     * Get the icon of the annotation
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @returns `PdfAnnotationIcon`
     */
    private getAnnotationIcon;
    /**
     * Set the icon of the annotation
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @param icon - `PdfAnnotationIcon`
     * @returns `true` on success
     */
    private setAnnotationIcon;
    /**
     * Get the reply type of the annotation (RT property per ISO 32000-2)
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @returns `PdfAnnotationReplyType`
     */
    private getReplyType;
    /**
     * Set the reply type of the annotation (RT property per ISO 32000-2)
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @param replyType - `PdfAnnotationReplyType`
     * @returns `true` on success
     */
    private setReplyType;
    /**
     * Border-effect (“cloudy”) helper
     *
     * Calls the new PDFium function `EPDFAnnot_GetBorderEffect()` (July 2025).
     *
     * @param  annotationPtr  pointer to an `FPDF_ANNOTATION`
     * @returns `{ ok, intensity }`
     *          • `ok`        – `true` when the annotation *does* have a
     *                          valid cloudy-border effect
     *          • `intensity` – radius/intensity value (0 when `ok` is false)
     */
    private getBorderEffect;
    /**
     * Rectangle-differences helper ( /RD array on Square / Circle annots )
     *
     * Calls `EPDFAnnot_GetRectangleDifferences()` introduced in July 2025.
     *
     * @param  annotationPtr  pointer to an `FPDF_ANNOTATION`
     * @returns `{ ok, left, top, right, bottom }`
     *          • `ok`     – `true` when the annotation *has* an /RD entry
     *          • the four floats are 0 when `ok` is false
     */
    private getRectangleDifferences;
    /**
     * Sets the /RD array on an annotation.
     *
     * @param annotationPtr  pointer to an `FPDF_ANNOTATION`
     * @param rd  the four inset values, or `undefined` to clear
     * @returns `true` on success
     */
    private setRectangleDifferences;
    /**
     * Sets or clears the /BE (border effect) dictionary on an annotation.
     *
     * @param annotationPtr  pointer to an `FPDF_ANNOTATION`
     * @param intensity  cloudy border intensity, or `undefined` to clear
     * @returns `true` on success
     */
    private setBorderEffect;
    /**
     * Get the date of the annotation
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @param key - 'M' for modified date, 'CreationDate' for creation date
     * @returns `Date` or `undefined` when PDFium can't read the date
     */
    private getAnnotationDate;
    /**
     * Set the date of the annotation
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @param key - 'M' for modified date, 'CreationDate' for creation date
     * @param date - `Date` to set
     * @returns `true` on success
     */
    private setAnnotationDate;
    /**
     * Get the date of the attachment
     *
     * @param attachmentPtr - pointer to an `FPDF_ATTACHMENT`
     * @param key - 'ModDate' for modified date, 'CreationDate' for creation date
     * @returns `Date` or `undefined` when PDFium can't read the date
     */
    private getAttachmentDate;
    /**
     * Set the date of the attachment
     *
     * @param attachmentPtr - pointer to an `FPDF_ATTACHMENT`
     * @param key - 'ModDate' for modified date, 'CreationDate' for creation date
     * @param date - `Date` to set
     * @returns `true` on success
     */
    private setAttachmentDate;
    /**
     * Dash-pattern helper ( /BS → /D array, dashed borders only )
     *
     * Uses the two new PDFium helpers:
     *   • `EPDFAnnot_GetBorderDashPatternCount`
     *   • `EPDFAnnot_GetBorderDashPattern`
     *
     * @param  annotationPtr  pointer to an `FPDF_ANNOTATION`
     * @returns `{ ok, pattern }`
     *          • `ok`       – `true` when the annot is dashed *and* the array
     *                          was retrieved successfully
     *          • `pattern`  – numeric array of dash/space lengths (empty when `ok` is false)
     */
    private getBorderDashPattern;
    /**
     * Write the /BS /D dash pattern array for an annotation border.
     *
     * @param annotationPtr Pointer to FPDF_ANNOTATION
     * @param pattern       Array of dash/space lengths in *points* (e.g. [3, 2])
     *                      Empty array clears the pattern (solid line).
     * @returns true on success
     *
     * @private
     */
    private setBorderDashPattern;
    /**
     * Return the `/LE` array (start/end line-ending styles) for a LINE / POLYLINE annot.
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @returns `{ start, end }` or `undefined` when PDFium can't read them
     *
     * @private
     */
    private getLineEndings;
    /**
     * Write the `/LE` array (start/end line-ending styles) for a LINE / POLYLINE annot.
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @param start - start line ending style
     * @param end - end line ending style
     * @returns `true` on success
     */
    private setLineEndings;
    /**
     * Get the start and end points of a LINE / POLYLINE annot.
     * @param doc - pdf document object
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @param page - logical page info object (`PdfPageObject`)
     * @returns `{ start, end }` or `undefined` when PDFium can't read them
     */
    private getLinePoints;
    /**
     * Set the two end‑points of a **Line** annotation
     * by writing a new /L array `[ x1 y1 x2 y2 ]`.
     * @param doc - pdf document object
     * @param page - logical page info object (`PdfPageObject`)
     * @param annotPtr - pointer to the annotation whose line points are needed
     * @param start - start point
     * @param end - end point
     * @returns true on success
     */
    private setLinePoints;
    /**
     * Read `/QuadPoints` from any annotation and convert each quadrilateral to
     * device-space coordinates.
     *
     * The four points are returned in natural reading order:
     *   `p1 → p2` (top edge) and `p4 → p3` (bottom edge).
     * This preserves the true shape for rotated / skewed text, whereas callers
     * that only need axis-aligned boxes can collapse each quad themselves.
     *
     * @param doc           - pdf document object
     * @param page          - logical page info object (`PdfPageObject`)
     * @param annotationPtr - pointer to the annotation whose quads are needed
     * @returns Array of `Rect` objects (`[]` if the annotation has no quads)
     *
     * @private
     */
    private getQuadPointsAnno;
    /**
     * Set the quadrilaterals for a **Highlight / Underline / StrikeOut / Squiggly** markup annotation.
     *
     * @param doc           - pdf document object
     * @param page          - logical page info object (`PdfPageObject`)
     * @param annotationPtr - pointer to the annotation whose quads are needed
     * @param rects         - array of `Rect` objects (`[]` if the annotation has no quads)
     * @returns `true` if the operation was successful
     *
     * @private
     */
    private syncQuadPointsAnno;
    /**
     * Redact text that intersects ANY of the provided **quads** (device-space).
     * Returns `true` if the page changed. Always regenerates the page stream.
     */
    redactTextInRects(doc: PdfDocumentObject, page: PdfPageObject, rects: Rect[], options?: PdfRedactTextOptions): Task<boolean, PdfErrorReason>;
    /**
     * Apply a single redaction annotation, permanently removing content underneath
     * and flattening the RO (Redact Overlay) appearance stream if present.
     * The annotation is removed after successful application.
     *
     * @param doc - document object
     * @param page - page object
     * @param annotation - the redact annotation to apply
     * @returns true if successful
     */
    applyRedaction(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): PdfTask<boolean>;
    /**
     * Apply all redaction annotations on a page, permanently removing content
     * underneath each one and flattening RO streams if present.
     * All redact annotations are removed after successful application.
     *
     * @param doc - document object
     * @param page - page object
     * @returns true if any redactions were applied
     */
    applyAllRedactions(doc: PdfDocumentObject, page: PdfPageObject): PdfTask<boolean>;
    /**
     * Flatten an annotation's appearance (AP/N) to page content.
     * The annotation's visual appearance becomes part of the page itself.
     * The annotation is automatically removed after flattening.
     *
     * @param doc - document object
     * @param page - page object
     * @param annotation - the annotation to flatten
     * @returns true if successful
     */
    flattenAnnotation(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject): PdfTask<boolean>;
    /** Pack device-space Rects into an FS_QUADPOINTSF[] buffer (page space). */
    private allocFSQuadsBufferFromRects;
    /**
     * Read ink list from annotation
     * @param doc - pdf document object
     * @param page  - logical page info object (`PdfPageObject`)
     * @param pagePtr - pointer to the page
     * @param annotationPtr - pointer to the annotation whose ink list is needed
     * @returns ink list
     */
    private getInkList;
    /**
     * Add ink list to annotation
     * @param doc - pdf document object
     * @param page  - logical page info object (`PdfPageObject`)
     * @param pagePtr - pointer to the page
     * @param annotationPtr - pointer to the annotation whose ink list is needed
     * @param inkList - ink list array of `PdfInkListObject`
     * @returns `true` if the operation was successful
     */
    private setInkList;
    /**
     * Read pdf text annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf text annotation
     *
     * @private
     */
    private readPdfTextAnno;
    /**
     * Read pdf freetext annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf freetext annotation
     *
     * @private
     */
    private readPdfFreeTextAnno;
    /**
     * Read pdf link annotation from pdf document
     * @param page  - pdf page infor
     * @param docPtr - pointer to pdf document object
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf link annotation
     *
     * @private
     */
    private readPdfLinkAnno;
    /**
     * Read pdf widget annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param formHandle - form handle
     * @param index  - index of annotation in the pdf page
     * @returns pdf widget annotation
     *
     * @private
     */
    private readPdfWidgetAnno;
    /**
     * Read pdf file attachment annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf file attachment annotation
     *
     * @private
     */
    private readPdfFileAttachmentAnno;
    /**
     * Read pdf ink annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf ink annotation
     *
     * @private
     */
    private readPdfInkAnno;
    /**
     * Read pdf polygon annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf polygon annotation
     *
     * @private
     */
    private readPdfPolygonAnno;
    /**
     * Read pdf polyline annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf polyline annotation
     *
     * @private
     */
    private readPdfPolylineAnno;
    /**
     * Read pdf line annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf line annotation
     *
     * @private
     */
    private readPdfLineAnno;
    /**
     * Read pdf highlight annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf highlight annotation
     *
     * @private
     */
    private readPdfHighlightAnno;
    /**
     * Read pdf underline annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf underline annotation
     *
     * @private
     */
    private readPdfUnderlineAnno;
    /**
     * Read strikeout annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf strikeout annotation
     *
     * @private
     */
    private readPdfStrikeOutAnno;
    /**
     * Read pdf squiggly annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf squiggly annotation
     *
     * @private
     */
    private readPdfSquigglyAnno;
    /**
     * Read pdf caret annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf caret annotation
     *
     * @private
     */
    private readPdfCaretAnno;
    /**
     * Read pdf redact annotation
     * @param page  - pdf page info
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf redact annotation
     *
     * @private
     */
    private readPdfRedactAnno;
    /**
     * Read pdf stamp annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf stamp annotation
     *
     * @private
     */
    private readPdfStampAnno;
    /**
     * Read pdf object in pdf page
     * @param pageObjectPtr  - pointer to pdf object in page
     * @returns pdf object in page
     *
     * @private
     */
    private readPdfPageObject;
    /**
     * Read pdf path object
     * @param pathObjectPtr  - pointer to pdf path object in page
     * @returns pdf path object
     *
     * @private
     */
    private readPathObject;
    /**
     * Read segment of pdf path object
     * @param annotationObjectPtr - pointer to pdf path object
     * @param segmentIndex - index of segment
     * @returns pdf segment in pdf path
     *
     * @private
     */
    private readPdfSegment;
    /**
     * Read pdf image object from pdf document
     * @param pageObjectPtr  - pointer to pdf image object in page
     * @returns pdf image object
     *
     * @private
     */
    private readImageObject;
    /**
     * Read form object from pdf document
     * @param formObjectPtr  - pointer to pdf form object in page
     * @returns pdf form object
     *
     * @private
     */
    private readFormObject;
    /**
     * Read pdf object in pdf page
     * @param pageObjectPtr  - pointer to pdf object in page
     * @returns pdf object in page
     *
     * @private
     */
    private readPdfPageObjectTransformMatrix;
    /**
     * Read contents of a stamp annotation
     * @param annotationPtr - pointer to pdf annotation
     * @returns contents of the stamp annotation
     *
     * @private
     */
    private readStampAnnotationContents;
    /**
     * Return the stroke-width declared in the annotation’s /Border or /BS entry.
     * Falls back to 1 pt when nothing is defined.
     *
     * @param annotationPtr - pointer to pdf annotation
     * @returns stroke-width
     *
     * @private
     */
    private getStrokeWidth;
    /**
     * Fetches the `/F` flag bit-field from an annotation.
     *
     * @param annotationPtr pointer to an `FPDF_ANNOTATION`
     * @returns `{ raw, flags }`
     *          • `raw`   – the 32-bit integer returned by PDFium
     *          • `flags` – object with individual booleans
     */
    private getAnnotationFlags;
    private setAnnotationFlags;
    /**
     * Read circle annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf circle annotation
     *
     * @private
     */
    private readPdfCircleAnno;
    /**
     * Read square annotation
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf square annotation
     *
     * @private
     */
    private readPdfSquareAnno;
    /**
     * Read basic info of unsupported pdf annotation
     * @param page  - pdf page infor
     * @param type - type of annotation
     * @param annotationPtr - pointer to pdf annotation
     * @param index  - index of annotation in the pdf page
     * @returns pdf annotation
     *
     * @private
     */
    private readPdfAnno;
    /**
     * Resolve `/IRT` → parent-annotation index on the same page.
     *
     * @param pagePtr        - pointer to FPDF_PAGE
     * @param annotationPtr  - pointer to FPDF_ANNOTATION
     * @returns index (`0…count-1`) or `undefined` when the annotation is *not* a reply
     *
     * @private
     */
    private getInReplyToId;
    /**
     * Set the in reply to id of the annotation
     *
     * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
     * @param id - the id of the parent annotation
     * @returns `true` on success
     */
    private setInReplyToId;
    /**
     * Rotate a point around a center by the given angle in degrees.
     * Used to rotate vertices for PDF storage.
     */
    private rotatePointForSave;
    /**
     * Prepare an annotation for saving to PDF.
     * For vertex types (ink, line, polygon, polyline) with rotation,
     * physically rotates the vertices by +rotation so that other PDF viewers
     * see the correct visual result. Our viewer reverse-rotates on load.
     */
    private prepareAnnotationForSave;
    /**
     * Apply all base annotation properties from PdfAnnotationObjectBase.
     * The setInReplyToId and setReplyType functions handle clearing when undefined.
     *
     * @param pagePtr - pointer to page object
     * @param annotationPtr - pointer to annotation object
     * @param annotation - the annotation object containing properties to apply
     * @returns `true` on success
     */
    private applyBaseAnnotationProperties;
    /**
     * Read all base annotation properties from PdfAnnotationObjectBase.
     * Returns an object that can be spread into the annotation return value.
     *
     * @param doc - pdf document object
     * @param page - pdf page object
     * @param annotationPtr - pointer to annotation object
     * @returns object with base annotation properties
     */
    private readBaseAnnotationProperties;
    /**
     * Fetch a string value (`/T`, `/M`, `/State`, …) from an annotation.
     *
     * @returns decoded UTF-8 string or `undefined` when the key is absent
     *
     * @private
     */
    private getAnnotString;
    /**
     * Get a string value (`/T`, `/M`, `/State`, …) from an attachment.
     *
     * @returns decoded UTF-8 string or `undefined` when the key is absent
     *
     * @private
     */
    private getAttachmentString;
    /**
     * Get a number value (`/Size`) from an attachment.
     *
     * @returns number or `null` when the key is absent
     *
     * @private
     */
    private getAttachmentNumber;
    /**
     * Get custom data of the annotation
     * @param annotationPtr - pointer to pdf annotation
     * @returns custom data of the annotation
     *
     * @private
     */
    private getAnnotCustom;
    /**
     * Sets custom data for an annotation by safely stringifying and storing JSON
     * @private
     */
    private setAnnotCustom;
    /**
     * Fetches the /IT (Intent) name from an annotation as a UTF-8 JS string.
     *
     * Mirrors getAnnotString(): calls EPDFAnnot_GetIntent twice (length probe + copy).
     * Returns `undefined` if no intent present.
     */
    private getAnnotIntent;
    /**
     * Write the `/IT` (Intent) name into an annotation dictionary.
     *
     * Mirrors EPDFAnnot_SetIntent in PDFium (expects a UTF‑8 FPDF_BYTESTRING).
     *
     * @param annotationPtr Pointer returned by FPDFPage_GetAnnot
     * @param intent        Name without leading slash, e.g. `"PolygonCloud"`
     *                      A leading “/” will be stripped for convenience.
     * @returns             true on success, false otherwise
     */
    private setAnnotIntent;
    /**
     * Returns the rich‑content string stored in the annotation’s `/RC` entry.
     *
     * Works like `getAnnotIntent()`: first probe for length, then copy.
     * `undefined` when the annotation has no rich content.
     */
    private getAnnotRichContent;
    /**
     * Get annotation by name
     * @param pagePtr - pointer to pdf page object
     * @param name - name of annotation
     * @returns pointer to pdf annotation
     *
     * @private
     */
    private getAnnotationByName;
    /**
     * Remove annotation by name
     * @param pagePtr - pointer to pdf page object
     * @param name - name of annotation
     * @returns true on success
     *
     * @private
     */
    private removeAnnotationByName;
    /**
     * Set a string value (`/T`, `/M`, `/State`, …) to an annotation.
     *
     * @returns `true` if the operation was successful
     *
     * @private
     */
    private setAnnotString;
    /**
     * Set a string value (`/T`, `/M`, `/State`, …) to an attachment.
     *
     * @returns `true` if the operation was successful
     *
     * @private
     */
    private setAttachmentString;
    /**
     * Read vertices of pdf annotation
     * @param doc - pdf document object
     * @param page  - pdf page infor
     * @param annotationPtr - pointer to pdf annotation
     * @returns vertices of pdf annotation
     *
     * @private
     */
    private readPdfAnnoVertices;
    /**
     * Sync the vertices of a polygon or polyline annotation.
     *
     * @param doc - pdf document object
     * @param page  - pdf page infor
     * @param annotPtr - pointer to pdf annotation
     * @param vertices - the vertices to be set
     * @returns true on success
     *
     * @private
     */
    private setPdfAnnoVertices;
    /**
     * Read the target of pdf bookmark
     * @param docPtr - pointer to pdf document object
     * @param getActionPtr - callback function to retrive the pointer of action
     * @param getDestinationPtr - callback function to retrive the pointer of destination
     * @returns target of pdf bookmark
     *
     * @private
     */
    private readPdfBookmarkTarget;
    /**
     * Read field of pdf widget annotation
     * @param formHandle - form handle
     * @param annotationPtr - pointer to pdf annotation
     * @returns field of pdf widget annotation
     *
     * @private
     */
    private readPdfWidgetAnnoField;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.renderAnnotation}
     *
     * @public
     */
    renderPageAnnotationRaw(doc: PdfDocumentObject, page: PdfPageObject, annotation: PdfAnnotationObject, options?: PdfRenderPageAnnotationOptions): PdfTask<ImageDataLike>;
    /**
     * Batch-render all annotation appearance streams for a page in one call.
     * Returns a map of annotation ID -> rendered appearances (Normal/Rollover/Down).
     * Skips annotations that have rotation + unrotatedRect (EmbedPDF-rotated)
     * and annotations without any appearance stream.
     *
     * @public
     */
    renderPageAnnotationsRaw(doc: PdfDocumentObject, page: PdfPageObject, options?: PdfRenderPageAnnotationOptions): PdfTask<AnnotationAppearanceMap>;
    /**
     * Render a single annotation's appearance for a given mode.
     * Returns the image data and rect, or null on failure.
     * @private
     */
    private renderSingleAnnotAppearance;
    private renderRectEncoded;
    /**
     * Read the target of pdf link annotation
     * @param docPtr - pointer to pdf document object
     * @param getActionPtr - callback function to retrive the pointer of action
     * @param getDestinationPtr - callback function to retrive the pointer of destination
     * @returns target of link
     *
     * @private
     */
    private readPdfLinkAnnoTarget;
    private createLocalDestPtr;
    private applyBookmarkTarget;
    /**
     * Apply a link target (action or destination) to a link annotation
     * @param docPtr - pointer to pdf document
     * @param annotationPtr - pointer to the link annotation
     * @param target - the link target to apply
     * @returns true if successful
     *
     * @private
     */
    private applyLinkTarget;
    /**
     * Read pdf action from pdf document
     * @param docPtr - pointer to pdf document object
     * @param actionPtr - pointer to pdf action object
     * @returns pdf action object
     *
     * @private
     */
    private readPdfAction;
    /**
     * Read pdf destination object
     * @param docPtr - pointer to pdf document object
     * @param destinationPtr - pointer to pdf destination
     * @returns pdf destination object
     *
     * @private
     */
    private readPdfDestination;
    /**
     * Read attachmet from pdf document
     * @param docPtr - pointer to pdf document object
     * @param index - index of attachment
     * @returns attachment content
     *
     * @private
     */
    private readPdfAttachment;
    /**
     * Convert coordinate of point from device coordinate to page coordinate
     * @param doc - pdf document object
     * @param page  - pdf page infor
     * @param position - position of point
     * @returns converted position
     *
     * @private
     */
    private convertDevicePointToPagePoint;
    /**
     * Convert coordinate of point from page coordinate to device coordinate
     * @param doc - pdf document object
     * @param page  - pdf page infor
     * @param position - position of point
     * @returns converted position
     *
     * @private
     */
    private convertPagePointToDevicePoint;
    /**
     * Convert coordinate of rectangle from page coordinate to device coordinate
     * @param doc - pdf document object
     * @param page  - pdf page infor
     * @param pagePtr - pointer to pdf page object
     * @param pageRect - rectangle that needs to be converted
     * @returns converted rectangle
     *
     * @private
     */
    private convertPageRectToDeviceRect;
    /**
     * Read the appearance stream of annotation
     * @param annotationPtr - pointer to pdf annotation
     * @param mode - appearance mode
     * @returns appearance stream
     *
     * @private
     */
    private readPageAnnoAppearanceStreams;
    /**
     * Read the appearance stream of annotation
     * @param annotationPtr - pointer to pdf annotation
     * @param mode - appearance mode
     * @returns appearance stream
     *
     * @private
     */
    private readPageAnnoAppearanceStream;
    /**
     * Set the appearance stream of annotation
     * @param annotationPtr - pointer to pdf annotation
     * @param mode - appearance mode
     * @param apContent - appearance stream content (null to remove)
     * @returns whether the appearance stream was set successfully
     *
     * @private
     */
    private setPageAnnoAppearanceStream;
    /**
     * Set the rect of specified annotation
     * @param doc - pdf document object
     * @param page - page info that the annotation is belonged to
     * @param annotationPtr - pointer to annotation object
     * @param rect - target rectangle
     * @returns whether the rect is setted
     *
     * @private
     */
    private setPageAnnoRect;
    /**
     * Read the rectangle of annotation
     * @param annotationPtr - pointer to pdf annotation
     * @returns rectangle of annotation
     *
     * @private
     */
    private readPageAnnoRect;
    /**
     * Get highlight rects for a specific character range (for search highlighting)
     * @param doc - pdf document object
     * @param page - pdf page info
     * @param pagePtr - pointer to pdf page
     * @param textPagePtr - pointer to pdf text page
     * @param startIndex - starting character index
     * @param charCount - number of characters in the range
     * @returns array of rectangles for highlighting the specified character range
     *
     * @private
     */
    private getHighlightRects;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.searchAllPages}
     *
     * Runs inside the worker.
     * Emits per-page progress: { page, results }
     *
     * @public
     */
    searchInPage(doc: PdfDocumentObject, page: PdfPageObject, keyword: string, flags: number): PdfTask<SearchResult[]>;
    /**
     * Get annotations for multiple pages in a single batch.
     * Emits progress per page for streaming updates.
     *
     * @param doc - PDF document
     * @param pages - Array of pages to process
     * @returns Task with results keyed by page index, with per-page progress
     *
     * @public
     */
    getAnnotationsBatch(doc: PdfDocumentObject, pages: PdfPageObject[]): PdfTask<Record<number, PdfAnnotationObject[]>, BatchProgress<PdfAnnotationObject[]>>;
    /**
     * Search across multiple pages in a single batch.
     * Emits progress per page for streaming updates.
     *
     * @param doc - PDF document
     * @param pages - Array of pages to search
     * @param keyword - Search keyword
     * @param flags - Search flags
     * @returns Task with results keyed by page index, with per-page progress
     *
     * @public
     */
    searchBatch(doc: PdfDocumentObject, pages: PdfPageObject[], keyword: string, flags: number): PdfTask<Record<number, SearchResult[]>, BatchProgress<SearchResult[]>>;
    /**
     * Extract word-aligned context for a search hit.
     *
     * @param fullText      full UTF-16 page text (fetch this once per page!)
     * @param start         index of 1st char that matched
     * @param count         number of chars in the match
     * @param windowChars   minimum context chars to keep left & right
     */
    private buildContext;
    /**
     * Tidy the text to remove any non-printable characters and whitespace
     * @param s - text to tidy
     * @returns tidied text
     *
     * @private
     */
    private tidy;
    /**
     * Search for all occurrences of a keyword on a single page
     * This method efficiently loads the page only once and finds all matches
     *
     * @param docPtr - pointer to pdf document
     * @param page - pdf page object
     * @param pageIndex - index of the page
     * @param keywordPtr - pointer to the search keyword
     * @param flag - search flags
     * @returns array of search results on this page
     *
     * @private
     */
    private searchAllInPage;
    /**
     * {@inheritDoc @embedpdf/models!PdfEngine.preparePrintDocument}
     *
     * Prepares a PDF document for printing with specified options.
     * Creates a new document with selected pages and optionally removes annotations
     * for optimal printing performance.
     *
     * @public
     */
    preparePrintDocument(doc: PdfDocumentObject, options?: PdfPrintOptions): PdfTask<ArrayBuffer>;
    /**
     * Removes all annotations from a print document using fast raw annotation functions.
     * This method is optimized for performance by avoiding full page loading.
     *
     * @param printDocPtr - Pointer to the print document
     * @returns Result object with success status and statistics
     *
     * @private
     */
    private removeAnnotationsFromPrintDocument;
    /**
     * Sanitizes and validates a page range string.
     * Ensures page numbers are within valid bounds and properly formatted.
     *
     * @param pageRange - Page range string (e.g., "1,3,5-7") or null for all pages
     * @param totalPages - Total number of pages in the document
     * @returns Sanitized page range string or null for all pages
     *
     * @private
     */
    private sanitizePageRange;
}
