import { init } from "@embedpdf/pdfium";
import { Rotation, NoopLogger, PdfTaskHelper, PdfErrorCode, pdfDateToDate, isUuidV4, uuidV4, PdfAnnotationSubtype, PdfPageFlattenFlag, stripPdfUnwantedMarkers, PdfAnnotationIcon, PdfAnnotationColorType, PdfAnnotationBorderStyle, PdfAnnotationLineEnding, PdfStandardFont, PdfStampFit, PdfTrappedStatus, pdfColorToWebColor, webColorToPdfColor, pdfAlphaToWebOpacity, webOpacityToPdfAlpha, PdfAnnotationReplyType, dateToPdfDate, quadToRect, rectToQuad, PdfPageObjectType, flagsToNames, namesToFlags, PDF_FORM_FIELD_TYPE, AppearanceMode, Task, toIntRect, transformRect, buildUserToDeviceMatrix, AP_MODE_NORMAL, AP_MODE_ROLLOVER, AP_MODE_DOWN, PdfZoomMode, PdfActionType } from "@embedpdf/models";
import { P as PdfEngine } from "./pdf-engine-ZvReuoDb.js";
import { b as browserImageDataToBlobConverter } from "./browser-BISJ9naB.js";
function readString(wasmModule, readChars, parseChars, defaultLength = 100) {
  let buffer = wasmModule.wasmExports.malloc(defaultLength);
  for (let i = 0; i < defaultLength; i++) {
    wasmModule.HEAP8[buffer + i] = 0;
  }
  const actualLength = readChars(buffer, defaultLength);
  let str;
  if (actualLength > defaultLength) {
    wasmModule.wasmExports.free(buffer);
    buffer = wasmModule.wasmExports.malloc(actualLength);
    for (let i = 0; i < actualLength; i++) {
      wasmModule.HEAP8[buffer + i] = 0;
    }
    readChars(buffer, actualLength);
    str = parseChars(buffer);
  } else {
    str = parseChars(buffer);
  }
  wasmModule.wasmExports.free(buffer);
  return str;
}
function readArrayBuffer(wasmModule, readChars) {
  const bufferSize = readChars(0, 0);
  const bufferPtr = wasmModule.wasmExports.malloc(bufferSize);
  readChars(bufferPtr, bufferSize);
  const arrayBuffer = new ArrayBuffer(bufferSize);
  const view = new DataView(arrayBuffer);
  for (let i = 0; i < bufferSize; i++) {
    view.setInt8(i, wasmModule.getValue(bufferPtr + i, "i8"));
  }
  wasmModule.wasmExports.free(bufferPtr);
  return arrayBuffer;
}
const RESERVED_INFO_KEYS = /* @__PURE__ */ new Set([
  "Title",
  "Author",
  "Subject",
  "Keywords",
  "Producer",
  "Creator",
  "CreationDate",
  "ModDate",
  "Trapped"
]);
function isValidCustomKey(key) {
  if (!key || key.length > 127) return false;
  if (RESERVED_INFO_KEYS.has(key)) return false;
  if (key[0] === "/") return false;
  for (let i = 0; i < key.length; i++) {
    const c = key.charCodeAt(i);
    if (c < 32 || c > 126) return false;
  }
  return true;
}
function computeFormDrawParams(matrix, rect, pageSize, rotation) {
  const rectLeft = rect.origin.x;
  const rectBottom = rect.origin.y;
  const rectRight = rectLeft + rect.size.width;
  const rectTop = rectBottom + rect.size.height;
  const pageWidth = pageSize.width;
  const pageHeight = pageSize.height;
  const scaleX = Math.hypot(matrix.a, matrix.b);
  const scaleY = Math.hypot(matrix.c, matrix.d);
  const swap = (rotation & 1) === 1;
  const formsWidth = swap ? Math.max(1, Math.round(pageHeight * scaleX)) : Math.max(1, Math.round(pageWidth * scaleX));
  const formsHeight = swap ? Math.max(1, Math.round(pageWidth * scaleY)) : Math.max(1, Math.round(pageHeight * scaleY));
  let startX;
  let startY;
  switch (rotation) {
    case Rotation.Degree0:
      startX = -Math.round(rectLeft * scaleX);
      startY = -Math.round(rectBottom * scaleY);
      break;
    case Rotation.Degree90:
      startX = Math.round((rectTop - pageHeight) * scaleX);
      startY = -Math.round(rectLeft * scaleY);
      break;
    case Rotation.Degree180:
      startX = Math.round((rectRight - pageWidth) * scaleX);
      startY = Math.round((rectTop - pageHeight) * scaleY);
      break;
    case Rotation.Degree270:
      startX = -Math.round(rectBottom * scaleX);
      startY = Math.round((rectRight - pageWidth) * scaleY);
      break;
    default:
      startX = -Math.round(rectLeft * scaleX);
      startY = -Math.round(rectBottom * scaleY);
      break;
  }
  return { startX, startY, formsWidth, formsHeight, scaleX, scaleY };
}
const WasmPointer = (ptr) => ptr;
const DEFAULT_CONFIG = {
  pageTtl: 5e3,
  // 5 seconds
  maxPagesPerDocument: 10,
  normalizeRotation: false
};
class PdfCache {
  constructor(pdfium, memoryManager, config = {}) {
    this.pdfium = pdfium;
    this.memoryManager = memoryManager;
    this.docs = /* @__PURE__ */ new Map();
    this.config = { ...DEFAULT_CONFIG, ...config };
  }
  /** Open (or re-use) a document */
  setDocument(id, filePtr, docPtr, normalizeRotation = false) {
    let ctx = this.docs.get(id);
    if (!ctx) {
      const docConfig = { ...this.config, normalizeRotation };
      ctx = new DocumentContext(filePtr, docPtr, this.pdfium, this.memoryManager, docConfig);
      this.docs.set(id, ctx);
    }
  }
  /** Retrieve the DocumentContext for a given PdfDocumentObject */
  getContext(docId) {
    return this.docs.get(docId);
  }
  /** Close & fully release a document and all its pages */
  closeDocument(docId) {
    const ctx = this.docs.get(docId);
    if (!ctx) return false;
    ctx.dispose();
    this.docs.delete(docId);
    return true;
  }
  /** Close all documents */
  closeAllDocuments() {
    for (const ctx of this.docs.values()) {
      ctx.dispose();
    }
    this.docs.clear();
  }
  /** Update cache configuration for all existing documents */
  updateConfig(newConfig) {
    Object.assign(this.config, newConfig);
    for (const ctx of this.docs.values()) {
      ctx.updateConfig(this.config);
    }
  }
  /** Get current cache statistics */
  getCacheStats() {
    const pagesByDocument = {};
    let totalPages = 0;
    for (const [docId, ctx] of this.docs.entries()) {
      const pageCount = ctx.getCacheSize();
      pagesByDocument[docId] = pageCount;
      totalPages += pageCount;
    }
    return {
      documents: this.docs.size,
      totalPages,
      pagesByDocument
    };
  }
}
class DocumentContext {
  constructor(filePtr, docPtr, pdfium, memoryManager, config) {
    this.filePtr = filePtr;
    this.docPtr = docPtr;
    this.memoryManager = memoryManager;
    this.normalizeRotation = config.normalizeRotation;
    this.pageCache = new PageCache(pdfium, docPtr, config);
  }
  /** Main accessor for pages */
  acquirePage(pageIdx) {
    return this.pageCache.acquire(pageIdx);
  }
  /** Scoped accessor for one-off / bulk operations */
  borrowPage(pageIdx, fn) {
    return this.pageCache.borrowPage(pageIdx, fn);
  }
  /** Update cache configuration */
  updateConfig(config) {
    this.pageCache.updateConfig(config);
  }
  /** Get number of pages currently in cache */
  getCacheSize() {
    return this.pageCache.size();
  }
  /** Tear down all pages + this document */
  dispose() {
    this.pageCache.forceReleaseAll();
    this.pageCache.pdf.FPDF_CloseDocument(this.docPtr);
    this.memoryManager.free(WasmPointer(this.filePtr));
  }
}
class PageCache {
  constructor(pdf, docPtr, config) {
    this.pdf = pdf;
    this.docPtr = docPtr;
    this.cache = /* @__PURE__ */ new Map();
    this.accessOrder = [];
    this.config = config;
  }
  acquire(pageIdx) {
    let ctx = this.cache.get(pageIdx);
    if (!ctx) {
      this.evictIfNeeded();
      let pagePtr;
      if (this.config.normalizeRotation) {
        pagePtr = this.pdf.EPDF_LoadPageNormalized(this.docPtr, pageIdx, 0);
      } else {
        pagePtr = this.pdf.FPDF_LoadPage(this.docPtr, pageIdx);
      }
      ctx = new PageContext(this.pdf, this.docPtr, pageIdx, pagePtr, this.config.pageTtl, () => {
        this.cache.delete(pageIdx);
        this.removeFromAccessOrder(pageIdx);
      });
      this.cache.set(pageIdx, ctx);
    }
    this.updateAccessOrder(pageIdx);
    ctx.clearExpiryTimer();
    ctx.bumpRefCount();
    return ctx;
  }
  /** Helper: run a function "scoped" to a page.
   *    – if the page was already cached  → .release() (keeps TTL logic)
   *    – if the page was loaded just now → .disposeImmediate() (free right away)
   */
  borrowPage(pageIdx, fn) {
    const existed = this.cache.has(pageIdx);
    const ctx = this.acquire(pageIdx);
    try {
      return fn(ctx);
    } finally {
      existed ? ctx.release() : ctx.disposeImmediate();
    }
  }
  forceReleaseAll() {
    for (const ctx of this.cache.values()) {
      ctx.disposeImmediate();
    }
    this.cache.clear();
    this.accessOrder.length = 0;
  }
  /** Update cache configuration */
  updateConfig(config) {
    this.config = config;
    for (const ctx of this.cache.values()) {
      ctx.updateTtl(config.pageTtl);
    }
    this.evictIfNeeded();
  }
  /** Get current cache size */
  size() {
    return this.cache.size;
  }
  /** Evict least recently used pages if cache exceeds max size */
  evictIfNeeded() {
    while (this.cache.size >= this.config.maxPagesPerDocument) {
      const lruPageIdx = this.accessOrder[0];
      if (lruPageIdx !== void 0) {
        const ctx = this.cache.get(lruPageIdx);
        if (ctx) {
          if (ctx.getRefCount() === 0) {
            ctx.disposeImmediate();
          } else {
            break;
          }
        } else {
          this.removeFromAccessOrder(lruPageIdx);
        }
      } else {
        break;
      }
    }
  }
  /** Update the access order for LRU tracking */
  updateAccessOrder(pageIdx) {
    this.removeFromAccessOrder(pageIdx);
    this.accessOrder.push(pageIdx);
  }
  /** Remove a page from the access order array */
  removeFromAccessOrder(pageIdx) {
    const index = this.accessOrder.indexOf(pageIdx);
    if (index > -1) {
      this.accessOrder.splice(index, 1);
    }
  }
}
class PageContext {
  constructor(pdf, docPtr, pageIdx, pagePtr, ttl, onFinalDispose) {
    this.pdf = pdf;
    this.docPtr = docPtr;
    this.pageIdx = pageIdx;
    this.pagePtr = pagePtr;
    this.onFinalDispose = onFinalDispose;
    this.refCount = 0;
    this.disposed = false;
    this.ttl = ttl;
  }
  /** Called by PageCache.acquire() */
  bumpRefCount() {
    if (this.disposed) throw new Error("Context already disposed");
    this.refCount++;
  }
  /** Get current reference count */
  getRefCount() {
    return this.refCount;
  }
  /** Called by PageCache.acquire() */
  clearExpiryTimer() {
    if (this.expiryTimer) {
      clearTimeout(this.expiryTimer);
      this.expiryTimer = void 0;
    }
  }
  /** Update TTL configuration */
  updateTtl(newTtl) {
    this.ttl = newTtl;
    if (this.expiryTimer && this.refCount === 0) {
      this.clearExpiryTimer();
      this.expiryTimer = setTimeout(() => this.disposeImmediate(), this.ttl);
    }
  }
  /** Called by PageCache.release() internally */
  release() {
    if (this.disposed) return;
    this.refCount--;
    if (this.refCount === 0) {
      this.expiryTimer = setTimeout(() => this.disposeImmediate(), this.ttl);
    }
  }
  /** Tear down _all_ sub-pointers & the page. */
  disposeImmediate() {
    if (this.disposed) return;
    this.disposed = true;
    this.clearExpiryTimer();
    if (this.textPagePtr !== void 0) {
      this.pdf.FPDFText_ClosePage(this.textPagePtr);
    }
    if (this.formHandle !== void 0) {
      this.pdf.FORM_OnBeforeClosePage(this.pagePtr, this.formHandle);
      this.pdf.PDFiumExt_ExitFormFillEnvironment(this.formHandle);
    }
    if (this.formInfoPtr !== void 0) {
      this.pdf.PDFiumExt_CloseFormFillInfo(this.formInfoPtr);
    }
    this.pdf.FPDF_ClosePage(this.pagePtr);
    this.onFinalDispose();
  }
  // ── public helpers ──
  /** Always safe: opens (once) and returns the text-page ptr. */
  getTextPage() {
    this.ensureAlive();
    if (this.textPagePtr === void 0) {
      this.textPagePtr = this.pdf.FPDFText_LoadPage(this.pagePtr);
    }
    return this.textPagePtr;
  }
  /** Always safe: opens (once) and returns the form-fill handle. */
  getFormHandle() {
    this.ensureAlive();
    if (this.formHandle === void 0) {
      this.formInfoPtr = this.pdf.PDFiumExt_OpenFormFillInfo();
      this.formHandle = this.pdf.PDFiumExt_InitFormFillEnvironment(this.docPtr, this.formInfoPtr);
      this.pdf.FORM_OnAfterLoadPage(this.pagePtr, this.formHandle);
    }
    return this.formHandle;
  }
  /**
   * Safely execute `fn` with an annotation pointer.
   * Pointer is ALWAYS closed afterwards.
   */
  withAnnotation(annotIdx, fn) {
    this.ensureAlive();
    const annotPtr = this.pdf.FPDFPage_GetAnnot(this.pagePtr, annotIdx);
    try {
      return fn(annotPtr);
    } finally {
      this.pdf.FPDFPage_CloseAnnot(annotPtr);
    }
  }
  ensureAlive() {
    if (this.disposed) throw new Error("PageContext already disposed");
  }
}
const MEMORY_LIMITS = {
  /** Maximum total memory that can be allocated (2GB) */
  MAX_TOTAL_MEMORY: 2 * 1024 * 1024 * 1024
};
const LIMITS = {
  MEMORY: MEMORY_LIMITS
};
const LOG_SOURCE$2 = "PDFiumEngine";
const LOG_CATEGORY$2 = "MemoryManager";
class MemoryManager {
  constructor(pdfiumModule, logger) {
    this.pdfiumModule = pdfiumModule;
    this.logger = logger;
    this.allocations = /* @__PURE__ */ new Map();
    this.totalAllocated = 0;
  }
  /**
   * Allocate memory with tracking and validation
   */
  malloc(size) {
    if (this.totalAllocated + size > LIMITS.MEMORY.MAX_TOTAL_MEMORY) {
      throw new Error(
        `Total memory usage would exceed limit: ${this.totalAllocated + size} > ${LIMITS.MEMORY.MAX_TOTAL_MEMORY}`
      );
    }
    const ptr = this.pdfiumModule.pdfium.wasmExports.malloc(size);
    if (!ptr) {
      throw new Error(`Failed to allocate ${size} bytes`);
    }
    const allocation = {
      ptr: WasmPointer(ptr),
      size,
      timestamp: Date.now(),
      stack: this.logger.isEnabled("debug") ? new Error().stack : void 0
    };
    this.allocations.set(ptr, allocation);
    this.totalAllocated += size;
    return WasmPointer(ptr);
  }
  /**
   * Free memory with validation
   */
  free(ptr) {
    const allocation = this.allocations.get(ptr);
    if (!allocation) {
      this.logger.warn(LOG_SOURCE$2, LOG_CATEGORY$2, `Freeing untracked pointer: ${ptr}`);
    } else {
      this.totalAllocated -= allocation.size;
      this.allocations.delete(ptr);
    }
    this.pdfiumModule.pdfium.wasmExports.free(ptr);
  }
  /**
   * Get memory statistics
   */
  getStats() {
    return {
      totalAllocated: this.totalAllocated,
      allocationCount: this.allocations.size,
      allocations: this.logger.isEnabled("debug") ? Array.from(this.allocations.values()) : []
    };
  }
  /**
   * Check for memory leaks
   */
  checkLeaks() {
    if (this.allocations.size > 0) {
      this.logger.warn(
        LOG_SOURCE$2,
        LOG_CATEGORY$2,
        `Potential memory leak: ${this.allocations.size} unfreed allocations`
      );
      for (const [ptr, alloc] of this.allocations) {
        this.logger.warn(LOG_SOURCE$2, LOG_CATEGORY$2, `  - ${ptr}: ${alloc.size} bytes`, alloc.stack);
      }
    }
  }
}
const SYSFONTINFO_SIZE = 36;
const OFFSET_VERSION = 0;
const OFFSET_RELEASE = 4;
const OFFSET_ENUMFONTS = 8;
const OFFSET_MAPFONT = 12;
const OFFSET_GETFONT = 16;
const OFFSET_GETFONTDATA = 20;
const OFFSET_GETFACENAME = 24;
const OFFSET_GETFONTCHARSET = 28;
const OFFSET_DELETEFONT = 32;
const LOG_SOURCE$1 = "pdfium";
const LOG_CATEGORY$1 = "font-fallback";
class FontFallbackManager {
  constructor(config, logger = new NoopLogger()) {
    this.fontHandles = /* @__PURE__ */ new Map();
    this.fontCache = /* @__PURE__ */ new Map();
    this.nextHandleId = 1;
    this.module = null;
    this.enabled = false;
    this.structPtr = 0;
    this.releaseFnPtr = 0;
    this.enumFontsFnPtr = 0;
    this.mapFontFnPtr = 0;
    this.getFontFnPtr = 0;
    this.getFontDataFnPtr = 0;
    this.getFaceNameFnPtr = 0;
    this.getFontCharsetFnPtr = 0;
    this.deleteFontFnPtr = 0;
    this.fontConfig = config;
    this.logger = logger;
  }
  /**
   * Initialize the font fallback system and attach to PDFium module
   */
  initialize(module) {
    if (this.enabled) {
      this.logger.warn(LOG_SOURCE$1, LOG_CATEGORY$1, "Font fallback already initialized");
      return;
    }
    this.module = module;
    const pdfium = module.pdfium;
    if (typeof pdfium.addFunction !== "function") {
      this.logger.error(
        LOG_SOURCE$1,
        LOG_CATEGORY$1,
        "addFunction not available. Make sure WASM is compiled with -sALLOW_TABLE_GROWTH"
      );
      return;
    }
    try {
      this.structPtr = pdfium.wasmExports.malloc(SYSFONTINFO_SIZE);
      if (!this.structPtr) {
        throw new Error("Failed to allocate FPDF_SYSFONTINFO struct");
      }
      for (let i = 0; i < SYSFONTINFO_SIZE; i++) {
        pdfium.setValue(this.structPtr + i, 0, "i8");
      }
      this.releaseFnPtr = pdfium.addFunction((_pThis) => {
      }, "vi");
      this.enumFontsFnPtr = pdfium.addFunction((_pThis, _pMapper) => {
      }, "vii");
      this.mapFontFnPtr = pdfium.addFunction(
        (_pThis, weight, bItalic, charset, pitchFamily, facePtr, bExactPtr) => {
          const face = facePtr ? pdfium.UTF8ToString(facePtr) : "";
          const handle = this.mapFont(weight, bItalic, charset, pitchFamily, face);
          if (bExactPtr) {
            pdfium.setValue(bExactPtr, 0, "i32");
          }
          return handle;
        },
        "iiiiiiii"
      );
      this.getFontFnPtr = pdfium.addFunction((_pThis, facePtr) => {
        const face = facePtr ? pdfium.UTF8ToString(facePtr) : "";
        return this.mapFont(400, 0, 0, 0, face);
      }, "iii");
      this.getFontDataFnPtr = pdfium.addFunction(
        (_pThis, hFont, table, buffer, bufSize) => {
          return this.getFontData(hFont, table, buffer, bufSize);
        },
        "iiiiii"
      );
      this.getFaceNameFnPtr = pdfium.addFunction(
        (_pThis, _hFont, _buffer, _bufSize) => {
          return 0;
        },
        "iiiii"
      );
      this.getFontCharsetFnPtr = pdfium.addFunction((_pThis, hFont) => {
        const handle = this.fontHandles.get(hFont);
        return (handle == null ? void 0 : handle.charset) ?? 0;
      }, "iii");
      this.deleteFontFnPtr = pdfium.addFunction((_pThis, hFont) => {
        this.deleteFont(hFont);
      }, "vii");
      pdfium.setValue(this.structPtr + OFFSET_VERSION, 1, "i32");
      pdfium.setValue(this.structPtr + OFFSET_RELEASE, this.releaseFnPtr, "i32");
      pdfium.setValue(this.structPtr + OFFSET_ENUMFONTS, this.enumFontsFnPtr, "i32");
      pdfium.setValue(this.structPtr + OFFSET_MAPFONT, this.mapFontFnPtr, "i32");
      pdfium.setValue(this.structPtr + OFFSET_GETFONT, this.getFontFnPtr, "i32");
      pdfium.setValue(this.structPtr + OFFSET_GETFONTDATA, this.getFontDataFnPtr, "i32");
      pdfium.setValue(this.structPtr + OFFSET_GETFACENAME, this.getFaceNameFnPtr, "i32");
      pdfium.setValue(this.structPtr + OFFSET_GETFONTCHARSET, this.getFontCharsetFnPtr, "i32");
      pdfium.setValue(this.structPtr + OFFSET_DELETEFONT, this.deleteFontFnPtr, "i32");
      module.FPDF_SetSystemFontInfo(this.structPtr);
      this.enabled = true;
      this.logger.info(
        LOG_SOURCE$1,
        LOG_CATEGORY$1,
        "Font fallback system initialized (pure TypeScript)",
        Object.keys(this.fontConfig.fonts)
      );
    } catch (error) {
      this.logger.error(LOG_SOURCE$1, LOG_CATEGORY$1, "Failed to initialize font fallback", error);
      this.cleanup();
      throw error;
    }
  }
  /**
   * Disable the font fallback system and clean up resources
   */
  disable() {
    if (!this.enabled || !this.module) {
      return;
    }
    this.module.FPDF_SetSystemFontInfo(0);
    this.cleanup();
    this.enabled = false;
    this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, "Font fallback system disabled");
  }
  /**
   * Clean up allocated resources
   */
  cleanup() {
    if (!this.module) return;
    const pdfium = this.module.pdfium;
    if (this.structPtr) {
      pdfium.wasmExports.free(this.structPtr);
      this.structPtr = 0;
    }
    const removeIfExists = (ptr) => {
      if (ptr && typeof pdfium.removeFunction === "function") {
        try {
          pdfium.removeFunction(ptr);
        } catch {
        }
      }
    };
    removeIfExists(this.releaseFnPtr);
    removeIfExists(this.enumFontsFnPtr);
    removeIfExists(this.mapFontFnPtr);
    removeIfExists(this.getFontFnPtr);
    removeIfExists(this.getFontDataFnPtr);
    removeIfExists(this.getFaceNameFnPtr);
    removeIfExists(this.getFontCharsetFnPtr);
    removeIfExists(this.deleteFontFnPtr);
    this.releaseFnPtr = 0;
    this.enumFontsFnPtr = 0;
    this.mapFontFnPtr = 0;
    this.getFontFnPtr = 0;
    this.getFontDataFnPtr = 0;
    this.getFaceNameFnPtr = 0;
    this.getFontCharsetFnPtr = 0;
    this.deleteFontFnPtr = 0;
  }
  /**
   * Check if font fallback is enabled
   */
  isEnabled() {
    return this.enabled;
  }
  /**
   * Get statistics about font loading
   */
  getStats() {
    return {
      handleCount: this.fontHandles.size,
      cacheSize: this.fontCache.size,
      cachedUrls: Array.from(this.fontCache.keys())
    };
  }
  /**
   * Pre-load fonts for specific charsets (optional optimization)
   * This can be called to warm the cache before rendering
   */
  async preloadFonts(charsets) {
    const urls = charsets.map((charset) => this.getFontUrlForCharset(charset)).filter((url) => url !== null);
    const uniqueUrls = [...new Set(urls)];
    await Promise.all(
      uniqueUrls.map(async (url) => {
        if (!this.fontCache.has(url)) {
          try {
            const data = await this.fetchFontAsync(url);
            if (data) {
              this.fontCache.set(url, data);
              this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, `Pre-loaded font: ${url}`);
            }
          } catch (error) {
            this.logger.warn(LOG_SOURCE$1, LOG_CATEGORY$1, `Failed to pre-load font: ${url}`, error);
          }
        }
      })
    );
  }
  // ============================================================================
  // PDFium Callback Implementations
  // ============================================================================
  /**
   * MapFont - called by PDFium when it needs a font
   */
  mapFont(weight, bItalic, charset, pitchFamily, face) {
    const italic = bItalic !== 0;
    this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, "MapFont called", {
      weight,
      italic,
      charset,
      pitchFamily,
      face
    });
    const result = this.findBestFontMatch(charset, weight, italic);
    if (!result) {
      this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, `No font configured for charset ${charset}`);
      return 0;
    }
    const handle = {
      id: this.nextHandleId++,
      charset,
      weight,
      italic,
      url: result.url,
      data: null
    };
    this.fontHandles.set(handle.id, handle);
    this.logger.debug(
      LOG_SOURCE$1,
      LOG_CATEGORY$1,
      `Created font handle ${handle.id} for ${result.url} (requested: weight=${weight}, italic=${italic}, matched: weight=${result.matchedWeight}, italic=${result.matchedItalic})`
    );
    return handle.id;
  }
  /**
   * GetFontData - called by PDFium to get font bytes
   */
  getFontData(fontHandle, table, bufferPtr, bufSize) {
    const handle = this.fontHandles.get(fontHandle);
    if (!handle) {
      this.logger.warn(LOG_SOURCE$1, LOG_CATEGORY$1, `Unknown font handle: ${fontHandle}`);
      return 0;
    }
    if (!handle.data) {
      if (this.fontCache.has(handle.url)) {
        handle.data = this.fontCache.get(handle.url);
      } else {
        handle.data = this.fetchFontSync(handle.url);
        if (handle.data) {
          this.fontCache.set(handle.url, handle.data);
        }
      }
    }
    if (!handle.data) {
      this.logger.warn(LOG_SOURCE$1, LOG_CATEGORY$1, `Failed to load font: ${handle.url}`);
      return 0;
    }
    const fontData = handle.data;
    if (table !== 0) {
      this.logger.debug(
        LOG_SOURCE$1,
        LOG_CATEGORY$1,
        `Table ${table} requested - returning 0 to request whole file`
      );
      return 0;
    }
    if (bufferPtr === 0 || bufSize < fontData.length) {
      return fontData.length;
    }
    if (this.module) {
      const heap = this.module.pdfium.HEAPU8;
      heap.set(fontData, bufferPtr);
      this.logger.debug(
        LOG_SOURCE$1,
        LOG_CATEGORY$1,
        `Copied ${fontData.length} bytes to buffer for handle ${fontHandle}`
      );
    }
    return fontData.length;
  }
  /**
   * DeleteFont - called by PDFium when done with a font
   */
  deleteFont(fontHandle) {
    const handle = this.fontHandles.get(fontHandle);
    if (handle) {
      this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, `Deleting font handle ${fontHandle}`);
      this.fontHandles.delete(fontHandle);
    }
  }
  // ============================================================================
  // Helper Methods
  // ============================================================================
  /**
   * Find the best matching font variant for the given parameters
   */
  findBestFontMatch(charset, requestedWeight, requestedItalic) {
    const { fonts, defaultFont, baseUrl } = this.fontConfig;
    const entry = fonts[charset] ?? defaultFont;
    if (!entry) {
      return null;
    }
    const variants = this.normalizeToVariants(entry);
    if (variants.length === 0) {
      return null;
    }
    const best = this.selectBestVariant(variants, requestedWeight, requestedItalic);
    let url = best.url;
    if (baseUrl && !url.startsWith("http://") && !url.startsWith("https://") && !url.startsWith("/")) {
      url = `${baseUrl}/${url}`;
    }
    return {
      url,
      matchedWeight: best.weight ?? 400,
      matchedItalic: best.italic ?? false
    };
  }
  /**
   * Normalize a FontEntry to an array of FontVariants
   */
  normalizeToVariants(entry) {
    if (typeof entry === "string") {
      return [{ url: entry, weight: 400, italic: false }];
    }
    if (Array.isArray(entry)) {
      return entry.map((v) => ({
        url: v.url,
        weight: v.weight ?? 400,
        italic: v.italic ?? false
      }));
    }
    return [{ url: entry.url, weight: entry.weight ?? 400, italic: entry.italic ?? false }];
  }
  /**
   * Select the best matching variant based on weight and italic
   * Uses CSS font matching algorithm principles:
   * 1. Exact italic match preferred
   * 2. Closest weight (with bias toward bolder for weights >= 400)
   */
  selectBestVariant(variants, requestedWeight, requestedItalic) {
    if (variants.length === 1) {
      return variants[0];
    }
    const italicMatches = variants.filter((v) => (v.italic ?? false) === requestedItalic);
    const candidates = italicMatches.length > 0 ? italicMatches : variants;
    let bestMatch = candidates[0];
    let bestDistance = Math.abs((bestMatch.weight ?? 400) - requestedWeight);
    for (const variant of candidates) {
      const variantWeight = variant.weight ?? 400;
      const distance = Math.abs(variantWeight - requestedWeight);
      if (distance < bestDistance) {
        bestMatch = variant;
        bestDistance = distance;
      } else if (distance === bestDistance) {
        const currentWeight = bestMatch.weight ?? 400;
        if (requestedWeight >= 500) {
          if (variantWeight > currentWeight) {
            bestMatch = variant;
          }
        } else {
          if (variantWeight < currentWeight) {
            bestMatch = variant;
          }
        }
      }
    }
    return bestMatch;
  }
  /**
   * Get font URL for a charset (backward compatible helper)
   */
  getFontUrlForCharset(charset) {
    const result = this.findBestFontMatch(charset, 400, false);
    return (result == null ? void 0 : result.url) ?? null;
  }
  /**
   * Fetch font data synchronously
   * Uses custom fontLoader if provided, otherwise falls back to XMLHttpRequest (browser)
   */
  fetchFontSync(pathOrUrl) {
    this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, `Fetching font synchronously: ${pathOrUrl}`);
    if (this.fontConfig.fontLoader) {
      try {
        const data = this.fontConfig.fontLoader(pathOrUrl);
        if (data) {
          this.logger.info(
            LOG_SOURCE$1,
            LOG_CATEGORY$1,
            `Loaded font via custom loader: ${pathOrUrl} (${data.length} bytes)`
          );
        } else {
          this.logger.warn(
            LOG_SOURCE$1,
            LOG_CATEGORY$1,
            `Custom font loader returned null for: ${pathOrUrl}`
          );
        }
        return data;
      } catch (error) {
        this.logger.error(
          LOG_SOURCE$1,
          LOG_CATEGORY$1,
          `Error in custom font loader: ${pathOrUrl}`,
          error
        );
        return null;
      }
    }
    try {
      const xhr = new XMLHttpRequest();
      xhr.open("GET", pathOrUrl, false);
      xhr.responseType = "arraybuffer";
      xhr.send();
      if (xhr.status === 200) {
        const data = new Uint8Array(xhr.response);
        this.logger.info(
          LOG_SOURCE$1,
          LOG_CATEGORY$1,
          `Loaded font: ${pathOrUrl} (${data.length} bytes)`
        );
        return data;
      } else {
        this.logger.error(
          LOG_SOURCE$1,
          LOG_CATEGORY$1,
          `Failed to load font: ${pathOrUrl} (HTTP ${xhr.status})`
        );
        return null;
      }
    } catch (error) {
      this.logger.error(LOG_SOURCE$1, LOG_CATEGORY$1, `Error fetching font: ${pathOrUrl}`, error);
      return null;
    }
  }
  /**
   * Fetch font data asynchronously (for preloading)
   * Uses custom fontLoader if provided, otherwise falls back to fetch API
   */
  async fetchFontAsync(pathOrUrl) {
    if (this.fontConfig.fontLoader) {
      try {
        return this.fontConfig.fontLoader(pathOrUrl);
      } catch {
        return null;
      }
    }
    try {
      const response = await fetch(pathOrUrl);
      if (response.ok) {
        const buffer = await response.arrayBuffer();
        return new Uint8Array(buffer);
      }
      return null;
    } catch {
      return null;
    }
  }
}
function createNodeFontLoader(fs, path, basePath) {
  return (fontPath) => {
    try {
      const fullPath = path.join(basePath, fontPath);
      const data = fs.readFileSync(fullPath);
      if (data instanceof Uint8Array) {
        return data;
      }
      return new Uint8Array(data);
    } catch {
      return null;
    }
  };
}
var BitmapFormat = /* @__PURE__ */ ((BitmapFormat2) => {
  BitmapFormat2[BitmapFormat2["Bitmap_Gray"] = 1] = "Bitmap_Gray";
  BitmapFormat2[BitmapFormat2["Bitmap_BGR"] = 2] = "Bitmap_BGR";
  BitmapFormat2[BitmapFormat2["Bitmap_BGRx"] = 3] = "Bitmap_BGRx";
  BitmapFormat2[BitmapFormat2["Bitmap_BGRA"] = 4] = "Bitmap_BGRA";
  return BitmapFormat2;
})(BitmapFormat || {});
var RenderFlag = /* @__PURE__ */ ((RenderFlag2) => {
  RenderFlag2[RenderFlag2["ANNOT"] = 1] = "ANNOT";
  RenderFlag2[RenderFlag2["LCD_TEXT"] = 2] = "LCD_TEXT";
  RenderFlag2[RenderFlag2["NO_NATIVETEXT"] = 4] = "NO_NATIVETEXT";
  RenderFlag2[RenderFlag2["GRAYSCALE"] = 8] = "GRAYSCALE";
  RenderFlag2[RenderFlag2["DEBUG_INFO"] = 128] = "DEBUG_INFO";
  RenderFlag2[RenderFlag2["NO_CATCH"] = 256] = "NO_CATCH";
  RenderFlag2[RenderFlag2["RENDER_LIMITEDIMAGECACHE"] = 512] = "RENDER_LIMITEDIMAGECACHE";
  RenderFlag2[RenderFlag2["RENDER_FORCEHALFTONE"] = 1024] = "RENDER_FORCEHALFTONE";
  RenderFlag2[RenderFlag2["PRINTING"] = 2048] = "PRINTING";
  RenderFlag2[RenderFlag2["REVERSE_BYTE_ORDER"] = 16] = "REVERSE_BYTE_ORDER";
  return RenderFlag2;
})(RenderFlag || {});
const LOG_SOURCE = "PDFiumEngine";
const LOG_CATEGORY = "Engine";
var PdfiumErrorCode = /* @__PURE__ */ ((PdfiumErrorCode2) => {
  PdfiumErrorCode2[PdfiumErrorCode2["Success"] = 0] = "Success";
  PdfiumErrorCode2[PdfiumErrorCode2["Unknown"] = 1] = "Unknown";
  PdfiumErrorCode2[PdfiumErrorCode2["File"] = 2] = "File";
  PdfiumErrorCode2[PdfiumErrorCode2["Format"] = 3] = "Format";
  PdfiumErrorCode2[PdfiumErrorCode2["Password"] = 4] = "Password";
  PdfiumErrorCode2[PdfiumErrorCode2["Security"] = 5] = "Security";
  PdfiumErrorCode2[PdfiumErrorCode2["Page"] = 6] = "Page";
  PdfiumErrorCode2[PdfiumErrorCode2["XFALoad"] = 7] = "XFALoad";
  PdfiumErrorCode2[PdfiumErrorCode2["XFALayout"] = 8] = "XFALayout";
  return PdfiumErrorCode2;
})(PdfiumErrorCode || {});
class PdfiumNative {
  /**
   * Create an instance of PdfiumNative and initialize PDFium
   * @param wasmModule - pdfium wasm module
   * @param options - configuration options
   */
  constructor(pdfiumModule, options = {}) {
    this.pdfiumModule = pdfiumModule;
    this.memoryLeakCheckInterval = null;
    this.fontFallbackManager = null;
    const { logger = new NoopLogger(), fontFallback } = options;
    this.logger = logger;
    this.memoryManager = new MemoryManager(this.pdfiumModule, this.logger);
    this.cache = new PdfCache(this.pdfiumModule, this.memoryManager);
    if (this.logger.isEnabled("debug")) {
      this.memoryLeakCheckInterval = setInterval(() => {
        this.memoryManager.checkLeaks();
      }, 1e4);
    }
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "initialize");
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Initialize`, "Begin", "General");
    this.pdfiumModule.PDFiumExt_Init();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Initialize`, "End", "General");
    if (fontFallback) {
      this.fontFallbackManager = new FontFallbackManager(fontFallback, this.logger);
      this.fontFallbackManager.initialize(this.pdfiumModule);
      this.logger.info(LOG_SOURCE, LOG_CATEGORY, "Font fallback system enabled");
    }
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.destroy}
   *
   * @public
   */
  destroy() {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "destroy");
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Destroy`, "Begin", "General");
    if (this.fontFallbackManager) {
      this.fontFallbackManager.disable();
      this.fontFallbackManager = null;
    }
    this.pdfiumModule.FPDF_DestroyLibrary();
    if (this.memoryLeakCheckInterval) {
      clearInterval(this.memoryLeakCheckInterval);
      this.memoryLeakCheckInterval = null;
    }
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Destroy`, "End", "General");
    return PdfTaskHelper.resolve(true);
  }
  /**
   * Get the font fallback manager instance
   * Useful for pre-loading fonts or checking stats
   */
  getFontFallbackManager() {
    return this.fontFallbackManager;
  }
  /** Write a UTF-16LE (WIDESTRING) to wasm, call `fn(ptr)`, then free. */
  withWString(value, fn) {
    const length = (value.length + 1) * 2;
    const ptr = this.memoryManager.malloc(length);
    try {
      this.pdfiumModule.pdfium.stringToUTF16(value, ptr, length);
      return fn(ptr);
    } finally {
      this.memoryManager.free(ptr);
    }
  }
  /** Write a float[] to wasm, call `fn(ptr, count)`, then free. */
  withFloatArray(values, fn) {
    const arr = values ?? [];
    const bytes = arr.length * 4;
    const ptr = bytes ? this.memoryManager.malloc(bytes) : WasmPointer(0);
    try {
      if (bytes) {
        for (let i = 0; i < arr.length; i++) {
          this.pdfiumModule.pdfium.setValue(ptr + i * 4, arr[i], "float");
        }
      }
      return fn(ptr, arr.length);
    } finally {
      if (bytes) this.memoryManager.free(ptr);
    }
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.openDocument}
   *
   * @public
   */
  openDocumentBuffer(file, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "openDocumentBuffer", file, options);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `OpenDocumentBuffer`, "Begin", file.id);
    const normalizeRotation = (options == null ? void 0 : options.normalizeRotation) ?? false;
    const array = new Uint8Array(file.content);
    const length = array.length;
    const filePtr = this.memoryManager.malloc(length);
    this.pdfiumModule.pdfium.HEAPU8.set(array, filePtr);
    const docPtr = this.pdfiumModule.FPDF_LoadMemDocument(filePtr, length, (options == null ? void 0 : options.password) ?? "");
    if (!docPtr) {
      const lastError = this.pdfiumModule.FPDF_GetLastError();
      this.logger.error(LOG_SOURCE, LOG_CATEGORY, `FPDF_LoadMemDocument failed with ${lastError}`);
      this.memoryManager.free(filePtr);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `OpenDocumentBuffer`, "End", file.id);
      return PdfTaskHelper.reject({
        code: lastError,
        message: `FPDF_LoadMemDocument failed`
      });
    }
    const pageCount = this.pdfiumModule.FPDF_GetPageCount(docPtr);
    const pages = [];
    const sizePtr = this.memoryManager.malloc(8);
    for (let index = 0; index < pageCount; index++) {
      const result = normalizeRotation ? this.pdfiumModule.EPDF_GetPageSizeByIndexNormalized(docPtr, index, sizePtr) : this.pdfiumModule.FPDF_GetPageSizeByIndexF(docPtr, index, sizePtr);
      if (!result) {
        const lastError = this.pdfiumModule.FPDF_GetLastError();
        this.logger.error(
          LOG_SOURCE,
          LOG_CATEGORY,
          `${normalizeRotation ? "EPDF_GetPageSizeByIndexNormalized" : "FPDF_GetPageSizeByIndexF"} failed with ${lastError}`
        );
        this.memoryManager.free(sizePtr);
        this.pdfiumModule.FPDF_CloseDocument(docPtr);
        this.memoryManager.free(filePtr);
        this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `OpenDocumentBuffer`, "End", file.id);
        return PdfTaskHelper.reject({
          code: lastError,
          message: `${normalizeRotation ? "EPDF_GetPageSizeByIndexNormalized" : "FPDF_GetPageSizeByIndexF"} failed`
        });
      }
      const rotation = this.pdfiumModule.EPDF_GetPageRotationByIndex(docPtr, index);
      const page = {
        index,
        size: {
          width: this.pdfiumModule.pdfium.getValue(sizePtr, "float"),
          height: this.pdfiumModule.pdfium.getValue(sizePtr + 4, "float")
        },
        rotation
      };
      pages.push(page);
    }
    this.memoryManager.free(sizePtr);
    const isEncrypted = this.pdfiumModule.EPDF_IsEncrypted(docPtr);
    const isOwnerUnlocked = this.pdfiumModule.EPDF_IsOwnerUnlocked(docPtr);
    const permissions = this.pdfiumModule.FPDF_GetDocPermissions(docPtr);
    const pdfDoc = {
      id: file.id,
      pageCount,
      pages,
      isEncrypted,
      isOwnerUnlocked,
      permissions,
      normalizedRotation: normalizeRotation
    };
    this.cache.setDocument(file.id, filePtr, docPtr, normalizeRotation);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `OpenDocumentBuffer`, "End", file.id);
    return PdfTaskHelper.resolve(pdfDoc);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getMetadata}
   *
   * @public
   */
  getMetadata(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getMetadata", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetMetadata`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetMetadata`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const creationRaw = this.readMetaText(ctx.docPtr, "CreationDate");
    const modRaw = this.readMetaText(ctx.docPtr, "ModDate");
    const metadata = {
      title: this.readMetaText(ctx.docPtr, "Title"),
      author: this.readMetaText(ctx.docPtr, "Author"),
      subject: this.readMetaText(ctx.docPtr, "Subject"),
      keywords: this.readMetaText(ctx.docPtr, "Keywords"),
      producer: this.readMetaText(ctx.docPtr, "Producer"),
      creator: this.readMetaText(ctx.docPtr, "Creator"),
      creationDate: creationRaw ? pdfDateToDate(creationRaw) ?? null : null,
      modificationDate: modRaw ? pdfDateToDate(modRaw) ?? null : null,
      trapped: this.getMetaTrapped(ctx.docPtr),
      custom: this.readAllMeta(ctx.docPtr, true)
    };
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetMetadata`, "End", doc.id);
    return PdfTaskHelper.resolve(metadata);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setMetadata}
   *
   * @public
   */
  setMetadata(doc, meta) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "setMetadata", doc, meta);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "SetMetadata", "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "SetMetadata", "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const strMap = [
      ["title", "Title"],
      ["author", "Author"],
      ["subject", "Subject"],
      ["keywords", "Keywords"],
      ["producer", "Producer"],
      ["creator", "Creator"]
    ];
    let ok = true;
    for (const [field, key] of strMap) {
      const v = meta[field];
      if (v === void 0) continue;
      const s = v === null ? null : v;
      if (!this.setMetaText(ctx.docPtr, key, s)) ok = false;
    }
    const writeDate = (field, key) => {
      const v = meta[field];
      if (v === void 0) return;
      if (v === null) {
        if (!this.setMetaText(ctx.docPtr, key, null)) ok = false;
        return;
      }
      const d = v;
      const raw = dateToPdfDate(d);
      if (!this.setMetaText(ctx.docPtr, key, raw)) ok = false;
    };
    writeDate("creationDate", "CreationDate");
    writeDate("modificationDate", "ModDate");
    if (meta.trapped !== void 0) {
      if (!this.setMetaTrapped(ctx.docPtr, meta.trapped ?? null)) ok = false;
    }
    if (meta.custom !== void 0) {
      for (const [key, value] of Object.entries(meta.custom)) {
        if (!isValidCustomKey(key)) {
          this.logger.warn(LOG_SOURCE, LOG_CATEGORY, "Invalid custom metadata key skipped", key);
          continue;
        }
        if (!this.setMetaText(ctx.docPtr, key, value ?? null)) ok = false;
      }
    }
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "SetMetadata", "End", doc.id);
    return ok ? PdfTaskHelper.resolve(true) : PdfTaskHelper.reject({
      code: PdfErrorCode.Unknown,
      message: "one or more metadata fields could not be written"
    });
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getDocPermissions}
   *
   * @public
   */
  getDocPermissions(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getDocPermissions", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `getDocPermissions`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `getDocPermissions`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const permissions = this.pdfiumModule.FPDF_GetDocPermissions(ctx.docPtr);
    return PdfTaskHelper.resolve(permissions);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getDocUserPermissions}
   *
   * @public
   */
  getDocUserPermissions(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getDocUserPermissions", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `getDocUserPermissions`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `getDocUserPermissions`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const permissions = this.pdfiumModule.FPDF_GetDocUserPermissions(ctx.docPtr);
    return PdfTaskHelper.resolve(permissions);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getSignatures}
   *
   * @public
   */
  getSignatures(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getSignatures", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetSignatures`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetSignatures`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const signatures = [];
    const count = this.pdfiumModule.FPDF_GetSignatureCount(ctx.docPtr);
    for (let i = 0; i < count; i++) {
      const signatureObjPtr = this.pdfiumModule.FPDF_GetSignatureObject(ctx.docPtr, i);
      const contents = readArrayBuffer(this.pdfiumModule.pdfium, (buffer, bufferSize) => {
        return this.pdfiumModule.FPDFSignatureObj_GetContents(signatureObjPtr, buffer, bufferSize);
      });
      const byteRange = readArrayBuffer(this.pdfiumModule.pdfium, (buffer, bufferSize) => {
        return this.pdfiumModule.FPDFSignatureObj_GetByteRange(signatureObjPtr, buffer, bufferSize) * 4;
      });
      const subFilter = readArrayBuffer(this.pdfiumModule.pdfium, (buffer, bufferSize) => {
        return this.pdfiumModule.FPDFSignatureObj_GetSubFilter(signatureObjPtr, buffer, bufferSize);
      });
      const reason = readString(
        this.pdfiumModule.pdfium,
        (buffer, bufferLength) => {
          return this.pdfiumModule.FPDFSignatureObj_GetReason(
            signatureObjPtr,
            buffer,
            bufferLength
          );
        },
        this.pdfiumModule.pdfium.UTF16ToString
      );
      const time = readString(
        this.pdfiumModule.pdfium,
        (buffer, bufferLength) => {
          return this.pdfiumModule.FPDFSignatureObj_GetTime(signatureObjPtr, buffer, bufferLength);
        },
        this.pdfiumModule.pdfium.UTF8ToString
      );
      const docMDP = this.pdfiumModule.FPDFSignatureObj_GetDocMDPPermission(signatureObjPtr);
      signatures.push({
        contents,
        byteRange,
        subFilter,
        reason,
        time,
        docMDP
      });
    }
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetSignatures`, "End", doc.id);
    return PdfTaskHelper.resolve(signatures);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getBookmarks}
   *
   * @public
   */
  getBookmarks(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getBookmarks", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetBookmarks`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `getBookmarks`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const bookmarks = this.readPdfBookmarks(ctx.docPtr, 0);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetBookmarks`, "End", doc.id);
    return PdfTaskHelper.resolve({
      bookmarks
    });
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setBookmarks}
   *
   * @public
   */
  setBookmarks(doc, list) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "setBookmarks", doc, list);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SetBookmarks`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SetBookmarks`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    if (!this.pdfiumModule.EPDFBookmark_Clear(ctx.docPtr)) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SetBookmarks`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: "failed to clear existing bookmarks"
      });
    }
    const build = (parentPtr, items) => {
      var _a;
      for (const item of items) {
        const bmPtr = this.withWString(
          item.title ?? "",
          (wptr) => this.pdfiumModule.EPDFBookmark_AppendChild(ctx.docPtr, parentPtr, wptr)
        );
        if (!bmPtr) return false;
        if (item.target) {
          const ok2 = this.applyBookmarkTarget(ctx.docPtr, bmPtr, item.target);
          if (!ok2) return false;
        }
        if ((_a = item.children) == null ? void 0 : _a.length) {
          const ok2 = build(bmPtr, item.children);
          if (!ok2) return false;
        }
      }
      return true;
    };
    const ok = build(
      /*top-level*/
      0,
      list
    );
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SetBookmarks`, "End", doc.id);
    if (!ok) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: "failed to build bookmark tree"
      });
    }
    return PdfTaskHelper.resolve(true);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.deleteBookmarks}
   *
   * @public
   */
  deleteBookmarks(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "deleteBookmarks", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `DeleteBookmarks`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `DeleteBookmarks`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const ok = this.pdfiumModule.EPDFBookmark_Clear(ctx.docPtr);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `DeleteBookmarks`, "End", doc.id);
    return ok ? PdfTaskHelper.resolve(true) : PdfTaskHelper.reject({
      code: PdfErrorCode.Unknown,
      message: "failed to clear bookmarks"
    });
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderPage}
   *
   * @public
   */
  renderPageRaw(doc, page, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPage", doc, page, options);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `RenderPage`, "Begin", `${doc.id}-${page.index}`);
    const rect = { origin: { x: 0, y: 0 }, size: page.size };
    const task = this.renderRectEncoded(doc, page, rect, options);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `RenderPage`, "End", `${doc.id}-${page.index}`);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRect}
   *
   * @public
   */
  renderPageRect(doc, page, rect, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPageRect", doc, page, rect, options);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RenderPageRect`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const task = this.renderRectEncoded(doc, page, rect, options);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `RenderPageRect`, "End", `${doc.id}-${page.index}`);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getPageAnnotations}
   *
   * @public
   */
  getPageAnnotations(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageAnnotations", doc, page);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `GetPageAnnotations`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `GetPageAnnotations`,
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const annotations = this.readPageAnnotations(doc, ctx, page);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `GetPageAnnotations`,
      "End",
      `${doc.id}-${page.index}`
    );
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      `GetPageAnnotations`,
      `${doc.id}-${page.index}`,
      annotations
    );
    return PdfTaskHelper.resolve(annotations);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.createPageAnnotation}
   *
   * @public
   */
  createPageAnnotation(doc, page, annotation, context) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "createPageAnnotation", doc, page, annotation);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `CreatePageAnnotation`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `CreatePageAnnotation`,
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const annotationPtr = this.pdfiumModule.EPDFPage_CreateAnnot(pageCtx.pagePtr, annotation.type);
    if (!annotationPtr) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `CreatePageAnnotation`,
        "End",
        `${doc.id}-${page.index}`
      );
      pageCtx.release();
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantCreateAnnot,
        message: "can not create annotation with specified type"
      });
    }
    if (!isUuidV4(annotation.id)) {
      annotation.id = uuidV4();
    }
    if (!this.setAnnotString(annotationPtr, "NM", annotation.id)) {
      this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
      pageCtx.release();
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantSetAnnotString,
        message: "can not set the name of the annotation"
      });
    }
    if (!this.setPageAnnoRect(doc, page, annotationPtr, annotation.rect)) {
      this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
      pageCtx.release();
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `CreatePageAnnotation`,
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantSetAnnotRect,
        message: "can not set the rect of the annotation"
      });
    }
    const saveAnnotation = this.prepareAnnotationForSave(annotation);
    let isSucceed = false;
    switch (saveAnnotation.type) {
      case PdfAnnotationSubtype.INK:
        isSucceed = this.addInkStroke(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.STAMP:
        isSucceed = this.addStampContent(
          doc,
          ctx.docPtr,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation,
          context == null ? void 0 : context.imageData
        );
        break;
      case PdfAnnotationSubtype.TEXT:
        isSucceed = this.addTextContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.FREETEXT:
        isSucceed = this.addFreeTextContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.LINE:
        isSucceed = this.addLineContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.POLYLINE:
      case PdfAnnotationSubtype.POLYGON:
        isSucceed = this.addPolyContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.CIRCLE:
      case PdfAnnotationSubtype.SQUARE:
        isSucceed = this.addShapeContent(doc, page, pageCtx.pagePtr, annotationPtr, saveAnnotation);
        break;
      case PdfAnnotationSubtype.UNDERLINE:
      case PdfAnnotationSubtype.STRIKEOUT:
      case PdfAnnotationSubtype.SQUIGGLY:
      case PdfAnnotationSubtype.HIGHLIGHT:
        isSucceed = this.addTextMarkupContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.LINK:
        isSucceed = this.addLinkContent(
          doc,
          page,
          ctx.docPtr,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.CARET:
        isSucceed = this.addCaretContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
      case PdfAnnotationSubtype.REDACT:
        isSucceed = this.addRedactContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotationPtr,
          saveAnnotation
        );
        break;
    }
    if (!isSucceed) {
      this.pdfiumModule.FPDFPage_RemoveAnnot(pageCtx.pagePtr, annotationPtr);
      pageCtx.release();
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `CreatePageAnnotation`,
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantSetAnnotContent,
        message: "can not add content of the annotation"
      });
    }
    if (annotation.blendMode !== void 0) {
      this.pdfiumModule.EPDFAnnot_GenerateAppearanceWithBlend(annotationPtr, annotation.blendMode);
    } else {
      this.pdfiumModule.EPDFAnnot_GenerateAppearance(annotationPtr);
    }
    this.pdfiumModule.FPDFPage_GenerateContent(pageCtx.pagePtr);
    this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
    pageCtx.release();
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `CreatePageAnnotation`,
      "End",
      `${doc.id}-${page.index}`
    );
    return PdfTaskHelper.resolve(annotation.id);
  }
  /**
   * Update an existing page annotation in-place
   *
   *  • Locates the annot by page-local index (`annotation.id`)
   *  • Re-writes its /Rect and type-specific payload
   *  • Calls FPDFPage_GenerateContent so the new appearance is rendered
   *
   * @returns PdfTask<boolean>  –  true on success
   */
  updatePageAnnotation(doc, page, annotation, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "updatePageAnnotation", doc, page, annotation);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      "UpdatePageAnnotation",
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        "UpdatePageAnnotation",
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const annotPtr = this.getAnnotationByName(pageCtx.pagePtr, annotation.id);
    if (!annotPtr) {
      pageCtx.release();
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        "UpdatePageAnnotation",
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({ code: PdfErrorCode.NotFound, message: "annotation not found" });
    }
    if (!this.setPageAnnoRect(doc, page, annotPtr, annotation.rect)) {
      this.pdfiumModule.FPDFPage_CloseAnnot(annotPtr);
      pageCtx.release();
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        "UpdatePageAnnotation",
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantSetAnnotRect,
        message: "failed to move annotation"
      });
    }
    const saveAnnotation = this.prepareAnnotationForSave(annotation);
    let ok = false;
    switch (saveAnnotation.type) {
      /* ── Ink ─────────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.INK: {
        if (!this.pdfiumModule.FPDFAnnot_RemoveInkList(annotPtr)) break;
        ok = this.addInkStroke(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Stamp ───────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.STAMP: {
        ok = this.addStampContent(
          doc,
          ctx.docPtr,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      case PdfAnnotationSubtype.TEXT: {
        ok = this.addTextContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Free text ────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.FREETEXT: {
        ok = this.addFreeTextContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Shape ───────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.CIRCLE:
      case PdfAnnotationSubtype.SQUARE: {
        ok = this.addShapeContent(doc, page, pageCtx.pagePtr, annotPtr, saveAnnotation);
        break;
      }
      /* ── Line ─────────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.LINE: {
        ok = this.addLineContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Polygon / Polyline ───────────────────────────────────────────────── */
      case PdfAnnotationSubtype.POLYGON:
      case PdfAnnotationSubtype.POLYLINE: {
        ok = this.addPolyContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Text-markup family ──────────────────────────────────────────────── */
      case PdfAnnotationSubtype.HIGHLIGHT:
      case PdfAnnotationSubtype.UNDERLINE:
      case PdfAnnotationSubtype.STRIKEOUT:
      case PdfAnnotationSubtype.SQUIGGLY: {
        ok = this.addTextMarkupContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Link ─────────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.LINK: {
        ok = this.addLinkContent(
          doc,
          page,
          ctx.docPtr,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Caret ────────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.CARET: {
        ok = this.addCaretContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Redact ───────────────────────────────────────────────────────────── */
      case PdfAnnotationSubtype.REDACT: {
        ok = this.addRedactContent(
          doc,
          page,
          pageCtx.pagePtr,
          annotPtr,
          saveAnnotation
        );
        break;
      }
      /* ── Unsupported edits – fall through to error ───────────────────────── */
      default:
        ok = false;
    }
    if (ok && (options == null ? void 0 : options.regenerateAppearance) !== false) {
      if (annotation.blendMode !== void 0) {
        this.pdfiumModule.EPDFAnnot_GenerateAppearanceWithBlend(annotPtr, annotation.blendMode);
      } else {
        this.pdfiumModule.EPDFAnnot_GenerateAppearance(annotPtr);
      }
      this.pdfiumModule.FPDFPage_GenerateContent(pageCtx.pagePtr);
    }
    this.pdfiumModule.FPDFPage_CloseAnnot(annotPtr);
    pageCtx.release();
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      "UpdatePageAnnotation",
      "End",
      `${doc.id}-${page.index}`
    );
    return ok ? PdfTaskHelper.resolve(true) : PdfTaskHelper.reject({
      code: PdfErrorCode.CantSetAnnotContent,
      message: "failed to update annotation"
    });
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.removePageAnnotation}
   *
   * @public
   */
  removePageAnnotation(doc, page, annotation) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "removePageAnnotation", doc, page, annotation);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RemovePageAnnotation`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `RemovePageAnnotation`,
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    let result = false;
    result = this.removeAnnotationByName(pageCtx.pagePtr, annotation.id);
    if (!result) {
      this.logger.error(
        LOG_SOURCE,
        LOG_CATEGORY,
        `FPDFPage_RemoveAnnot Failed`,
        `${doc.id}-${page.index}`
      );
    } else {
      result = this.pdfiumModule.FPDFPage_GenerateContent(pageCtx.pagePtr);
      if (!result) {
        this.logger.error(
          LOG_SOURCE,
          LOG_CATEGORY,
          `FPDFPage_GenerateContent Failed`,
          `${doc.id}-${page.index}`
        );
      }
    }
    pageCtx.release();
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RemovePageAnnotation`,
      "End",
      `${doc.id}-${page.index}`
    );
    return PdfTaskHelper.resolve(result);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getPageTextRects}
   *
   * @public
   */
  getPageTextRects(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageTextRects", doc, page);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `GetPageTextRects`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `GetPageTextRects`,
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const textPagePtr = this.pdfiumModule.FPDFText_LoadPage(pageCtx.pagePtr);
    const textRects = this.readPageTextRects(page, pageCtx.docPtr, pageCtx.pagePtr, textPagePtr);
    this.pdfiumModule.FPDFText_ClosePage(textPagePtr);
    pageCtx.release();
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `GetPageTextRects`,
      "End",
      `${doc.id}-${page.index}`
    );
    return PdfTaskHelper.resolve(textRects);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderThumbnail}
   *
   * @public
   */
  renderThumbnailRaw(doc, page, options) {
    const { scaleFactor = 1, ...rest } = options ?? {};
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderThumbnail", doc, page, options);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RenderThumbnail`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `RenderThumbnail`,
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const result = this.renderPageRaw(doc, page, {
      scaleFactor: Math.max(scaleFactor, 0.5),
      ...rest
    });
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `RenderThumbnail`, "End", `${doc.id}-${page.index}`);
    return result;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getAttachments}
   *
   * @public
   */
  getAttachments(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getAttachments", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetAttachments`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetAttachments`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const attachments = [];
    const count = this.pdfiumModule.FPDFDoc_GetAttachmentCount(ctx.docPtr);
    for (let i = 0; i < count; i++) {
      const attachment = this.readPdfAttachment(ctx.docPtr, i);
      attachments.push(attachment);
    }
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `GetAttachments`, "End", doc.id);
    return PdfTaskHelper.resolve(attachments);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.addAttachment}
   *
   * @public
   */
  addAttachment(doc, params) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "addAttachment", doc, params == null ? void 0 : params.name);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `AddAttachment`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `AddAttachment`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const { name, description, mimeType, data } = params ?? {};
    if (!name) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `AddAttachment`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.NotFound,
        message: "attachment name is required"
      });
    }
    if (!data || (data instanceof Uint8Array ? data.byteLength === 0 : data.byteLength === 0)) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `AddAttachment`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.NotFound,
        message: "attachment data is empty"
      });
    }
    const attachmentPtr = this.withWString(
      name,
      (wNamePtr) => this.pdfiumModule.FPDFDoc_AddAttachment(ctx.docPtr, wNamePtr)
    );
    if (!attachmentPtr) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `AddAttachment`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: `An attachment named "${name}" already exists`
      });
    }
    this.withWString(
      description,
      (wDescriptionPtr) => this.pdfiumModule.EPDFAttachment_SetDescription(attachmentPtr, wDescriptionPtr)
    );
    this.pdfiumModule.EPDFAttachment_SetSubtype(attachmentPtr, mimeType);
    const u8 = data instanceof Uint8Array ? data : new Uint8Array(data);
    const len = u8.byteLength;
    const contentPtr = this.memoryManager.malloc(len);
    try {
      this.pdfiumModule.pdfium.HEAPU8.set(u8, contentPtr);
      const ok = this.pdfiumModule.FPDFAttachment_SetFile(
        attachmentPtr,
        ctx.docPtr,
        contentPtr,
        len
      );
      if (!ok) {
        this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `AddAttachment`, "End", doc.id);
        return PdfTaskHelper.reject({
          code: PdfErrorCode.Unknown,
          message: "failed to write attachment bytes"
        });
      }
    } finally {
      this.memoryManager.free(contentPtr);
    }
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `AddAttachment`, "End", doc.id);
    return PdfTaskHelper.resolve(true);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.removeAttachment}
   *
   * @public
   */
  removeAttachment(doc, attachment) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "deleteAttachment", doc, attachment);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `DeleteAttachment`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `DeleteAttachment`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const count = this.pdfiumModule.FPDFDoc_GetAttachmentCount(ctx.docPtr);
    if (attachment.index < 0 || attachment.index >= count) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `DeleteAttachment`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: `attachment index ${attachment.index} out of range`
      });
    }
    const ok = this.pdfiumModule.FPDFDoc_DeleteAttachment(ctx.docPtr, attachment.index);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `DeleteAttachment`, "End", doc.id);
    if (!ok) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: "failed to delete attachment"
      });
    }
    return PdfTaskHelper.resolve(true);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.readAttachmentContent}
   *
   * @public
   */
  readAttachmentContent(doc, attachment) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "readAttachmentContent", doc, attachment);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ReadAttachmentContent`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ReadAttachmentContent`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const attachmentPtr = this.pdfiumModule.FPDFDoc_GetAttachment(ctx.docPtr, attachment.index);
    const sizePtr = this.memoryManager.malloc(4);
    if (!this.pdfiumModule.FPDFAttachment_GetFile(attachmentPtr, 0, 0, sizePtr)) {
      this.memoryManager.free(sizePtr);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ReadAttachmentContent`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantReadAttachmentSize,
        message: "can not read attachment size"
      });
    }
    const size = this.pdfiumModule.pdfium.getValue(sizePtr, "i32") >>> 0;
    const contentPtr = this.memoryManager.malloc(size);
    if (!this.pdfiumModule.FPDFAttachment_GetFile(attachmentPtr, contentPtr, size, sizePtr)) {
      this.memoryManager.free(sizePtr);
      this.memoryManager.free(contentPtr);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ReadAttachmentContent`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantReadAttachmentContent,
        message: "can not read attachment content"
      });
    }
    const buffer = new ArrayBuffer(size);
    const view = new DataView(buffer);
    for (let i = 0; i < size; i++) {
      view.setInt8(i, this.pdfiumModule.pdfium.getValue(contentPtr + i, "i8"));
    }
    this.memoryManager.free(sizePtr);
    this.memoryManager.free(contentPtr);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ReadAttachmentContent`, "End", doc.id);
    return PdfTaskHelper.resolve(buffer);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setFormFieldValue}
   *
   * @public
   */
  setFormFieldValue(doc, page, annotation, value) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "SetFormFieldValue", doc, annotation, value);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `SetFormFieldValue`,
      "Begin",
      `${doc.id}-${annotation.id}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "SetFormFieldValue", "document is not opened");
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `SetFormFieldValue`,
        "End",
        `${doc.id}-${annotation.id}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const formFillInfoPtr = this.pdfiumModule.PDFiumExt_OpenFormFillInfo();
    const formHandle = this.pdfiumModule.PDFiumExt_InitFormFillEnvironment(
      ctx.docPtr,
      formFillInfoPtr
    );
    const pageCtx = ctx.acquirePage(page.index);
    this.pdfiumModule.FORM_OnAfterLoadPage(pageCtx.pagePtr, formHandle);
    const annotationPtr = this.getAnnotationByName(pageCtx.pagePtr, annotation.id);
    if (!annotationPtr) {
      pageCtx.release();
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        "SetFormFieldValue",
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({ code: PdfErrorCode.NotFound, message: "annotation not found" });
    }
    if (!this.pdfiumModule.FORM_SetFocusedAnnot(formHandle, annotationPtr)) {
      this.logger.debug(
        LOG_SOURCE,
        LOG_CATEGORY,
        "SetFormFieldValue",
        "failed to set focused annotation"
      );
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `SetFormFieldValue`,
        "End",
        `${doc.id}-${annotation.id}`
      );
      this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
      this.pdfiumModule.FORM_OnBeforeClosePage(pageCtx.pagePtr, formHandle);
      pageCtx.release();
      this.pdfiumModule.PDFiumExt_ExitFormFillEnvironment(formHandle);
      this.pdfiumModule.PDFiumExt_CloseFormFillInfo(formFillInfoPtr);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantFocusAnnot,
        message: "failed to set focused annotation"
      });
    }
    switch (value.kind) {
      case "text":
        {
          if (!this.pdfiumModule.FORM_SelectAllText(formHandle, pageCtx.pagePtr)) {
            this.logger.debug(
              LOG_SOURCE,
              LOG_CATEGORY,
              "SetFormFieldValue",
              "failed to select all text"
            );
            this.logger.perf(
              LOG_SOURCE,
              LOG_CATEGORY,
              `SetFormFieldValue`,
              "End",
              `${doc.id}-${annotation.id}`
            );
            this.pdfiumModule.FORM_ForceToKillFocus(formHandle);
            this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
            this.pdfiumModule.FORM_OnBeforeClosePage(pageCtx.pagePtr, formHandle);
            pageCtx.release();
            this.pdfiumModule.PDFiumExt_ExitFormFillEnvironment(formHandle);
            this.pdfiumModule.PDFiumExt_CloseFormFillInfo(formFillInfoPtr);
            return PdfTaskHelper.reject({
              code: PdfErrorCode.CantSelectText,
              message: "failed to select all text"
            });
          }
          const length = 2 * (value.text.length + 1);
          const textPtr = this.memoryManager.malloc(length);
          this.pdfiumModule.pdfium.stringToUTF16(value.text, textPtr, length);
          this.pdfiumModule.FORM_ReplaceSelection(formHandle, pageCtx.pagePtr, textPtr);
          this.memoryManager.free(textPtr);
        }
        break;
      case "selection":
        {
          if (!this.pdfiumModule.FORM_SetIndexSelected(
            formHandle,
            pageCtx.pagePtr,
            value.index,
            value.isSelected
          )) {
            this.logger.debug(
              LOG_SOURCE,
              LOG_CATEGORY,
              "SetFormFieldValue",
              "failed to set index selected"
            );
            this.logger.perf(
              LOG_SOURCE,
              LOG_CATEGORY,
              `SetFormFieldValue`,
              "End",
              `${doc.id}-${annotation.id}`
            );
            this.pdfiumModule.FORM_ForceToKillFocus(formHandle);
            this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
            this.pdfiumModule.FORM_OnBeforeClosePage(pageCtx.pagePtr, formHandle);
            pageCtx.release();
            this.pdfiumModule.PDFiumExt_ExitFormFillEnvironment(formHandle);
            this.pdfiumModule.PDFiumExt_CloseFormFillInfo(formFillInfoPtr);
            return PdfTaskHelper.reject({
              code: PdfErrorCode.CantSelectOption,
              message: "failed to set index selected"
            });
          }
        }
        break;
      case "checked":
        {
          const kReturn = 13;
          if (!this.pdfiumModule.FORM_OnChar(formHandle, pageCtx.pagePtr, kReturn, 0)) {
            this.logger.debug(
              LOG_SOURCE,
              LOG_CATEGORY,
              "SetFormFieldValue",
              "failed to set field checked"
            );
            this.logger.perf(
              LOG_SOURCE,
              LOG_CATEGORY,
              `SetFormFieldValue`,
              "End",
              `${doc.id}-${annotation.id}`
            );
            this.pdfiumModule.FORM_ForceToKillFocus(formHandle);
            this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
            this.pdfiumModule.FORM_OnBeforeClosePage(pageCtx.pagePtr, formHandle);
            pageCtx.release();
            this.pdfiumModule.PDFiumExt_ExitFormFillEnvironment(formHandle);
            this.pdfiumModule.PDFiumExt_CloseFormFillInfo(formFillInfoPtr);
            return PdfTaskHelper.reject({
              code: PdfErrorCode.CantCheckField,
              message: "failed to set field checked"
            });
          }
        }
        break;
    }
    this.pdfiumModule.FORM_ForceToKillFocus(formHandle);
    this.pdfiumModule.FPDFPage_CloseAnnot(annotationPtr);
    this.pdfiumModule.FORM_OnBeforeClosePage(pageCtx.pagePtr, formHandle);
    pageCtx.release();
    this.pdfiumModule.PDFiumExt_ExitFormFillEnvironment(formHandle);
    this.pdfiumModule.PDFiumExt_CloseFormFillInfo(formFillInfoPtr);
    return PdfTaskHelper.resolve(true);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.flattenPage}
   *
   * @public
   */
  flattenPage(doc, page, options) {
    const { flag = PdfPageFlattenFlag.Display } = options ?? {};
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "flattenPage", doc, page, flag);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `flattenPage`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `flattenPage`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const result = this.pdfiumModule.FPDFPage_Flatten(pageCtx.pagePtr, flag);
    pageCtx.release();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `flattenPage`, "End", doc.id);
    return PdfTaskHelper.resolve(result);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.extractPages}
   *
   * @public
   */
  extractPages(doc, pageIndexes) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "extractPages", doc, pageIndexes);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractPages`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractPages`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const newDocPtr = this.pdfiumModule.FPDF_CreateNewDocument();
    if (!newDocPtr) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractPages`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantCreateNewDoc,
        message: "can not create new document"
      });
    }
    const pageIndexesPtr = this.memoryManager.malloc(pageIndexes.length * 4);
    for (let i = 0; i < pageIndexes.length; i++) {
      this.pdfiumModule.pdfium.setValue(pageIndexesPtr + i * 4, pageIndexes[i], "i32");
    }
    if (!this.pdfiumModule.FPDF_ImportPagesByIndex(
      newDocPtr,
      ctx.docPtr,
      pageIndexesPtr,
      pageIndexes.length,
      0
    )) {
      this.pdfiumModule.FPDF_CloseDocument(newDocPtr);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractPages`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantImportPages,
        message: "can not import pages to new document"
      });
    }
    const buffer = this.saveDocument(newDocPtr);
    this.pdfiumModule.FPDF_CloseDocument(newDocPtr);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractPages`, "End", doc.id);
    return PdfTaskHelper.resolve(buffer);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.extractText}
   *
   * @public
   */
  extractText(doc, pageIndexes) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "extractText", doc, pageIndexes);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractText`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractText`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const strings = [];
    for (let i = 0; i < pageIndexes.length; i++) {
      const pageCtx = ctx.acquirePage(pageIndexes[i]);
      const textPagePtr = this.pdfiumModule.FPDFText_LoadPage(pageCtx.pagePtr);
      const charCount = this.pdfiumModule.FPDFText_CountChars(textPagePtr);
      const bufferPtr = this.memoryManager.malloc((charCount + 1) * 2);
      this.pdfiumModule.FPDFText_GetText(textPagePtr, 0, charCount, bufferPtr);
      const text2 = this.pdfiumModule.pdfium.UTF16ToString(bufferPtr);
      this.memoryManager.free(bufferPtr);
      strings.push(text2);
      this.pdfiumModule.FPDFText_ClosePage(textPagePtr);
      pageCtx.release();
    }
    const text = strings.join("\n\n");
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `ExtractText`, "End", doc.id);
    return PdfTaskHelper.resolve(text);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getTextSlices}
   *
   * @public
   */
  getTextSlices(doc, slices) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getTextSlices", doc, slices);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "GetTextSlices", "Begin", doc.id);
    if (slices.length === 0) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "GetTextSlices", "End", doc.id);
      return PdfTaskHelper.resolve([]);
    }
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "GetTextSlices", "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    try {
      const out = new Array(slices.length);
      const byPage = /* @__PURE__ */ new Map();
      slices.forEach((s, i) => {
        (byPage.get(s.pageIndex) ?? byPage.set(s.pageIndex, []).get(s.pageIndex)).push({
          slice: s,
          pos: i
        });
      });
      for (const [pageIdx, list] of byPage) {
        const pageCtx = ctx.acquirePage(pageIdx);
        const textPagePtr = pageCtx.getTextPage();
        for (const { slice, pos } of list) {
          const bufPtr = this.memoryManager.malloc(2 * (slice.charCount + 1));
          this.pdfiumModule.FPDFText_GetText(textPagePtr, slice.charIndex, slice.charCount, bufPtr);
          out[pos] = stripPdfUnwantedMarkers(this.pdfiumModule.pdfium.UTF16ToString(bufPtr));
          this.memoryManager.free(bufPtr);
        }
        pageCtx.release();
      }
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "GetTextSlices", "End", doc.id);
      return PdfTaskHelper.resolve(out);
    } catch (e) {
      this.logger.error(LOG_SOURCE, LOG_CATEGORY, "getTextSlices error", e);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "GetTextSlices", "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: String(e)
      });
    }
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.merge}
   *
   * @public
   */
  merge(files) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "merge", files);
    const fileIds = files.map((file2) => file2.id).join(".");
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Merge`, "Begin", fileIds);
    const newDocPtr = this.pdfiumModule.FPDF_CreateNewDocument();
    if (!newDocPtr) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Merge`, "End", fileIds);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantCreateNewDoc,
        message: "can not create new document"
      });
    }
    const ptrs = [];
    for (const file2 of files.reverse()) {
      const array = new Uint8Array(file2.content);
      const length = array.length;
      const filePtr = this.memoryManager.malloc(length);
      this.pdfiumModule.pdfium.HEAPU8.set(array, filePtr);
      const docPtr = this.pdfiumModule.FPDF_LoadMemDocument(filePtr, length, "");
      if (!docPtr) {
        const lastError = this.pdfiumModule.FPDF_GetLastError();
        this.logger.error(
          LOG_SOURCE,
          LOG_CATEGORY,
          `FPDF_LoadMemDocument failed with ${lastError}`
        );
        this.memoryManager.free(filePtr);
        for (const ptr of ptrs) {
          this.pdfiumModule.FPDF_CloseDocument(ptr.docPtr);
          this.memoryManager.free(ptr.filePtr);
        }
        this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Merge`, "End", fileIds);
        return PdfTaskHelper.reject({
          code: lastError,
          message: `FPDF_LoadMemDocument failed`
        });
      }
      ptrs.push({ filePtr, docPtr });
      if (!this.pdfiumModule.FPDF_ImportPages(newDocPtr, docPtr, "", 0)) {
        this.pdfiumModule.FPDF_CloseDocument(newDocPtr);
        for (const ptr of ptrs) {
          this.pdfiumModule.FPDF_CloseDocument(ptr.docPtr);
          this.memoryManager.free(ptr.filePtr);
        }
        this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Merge`, "End", fileIds);
        return PdfTaskHelper.reject({
          code: PdfErrorCode.CantImportPages,
          message: "can not import pages to new document"
        });
      }
    }
    const buffer = this.saveDocument(newDocPtr);
    this.pdfiumModule.FPDF_CloseDocument(newDocPtr);
    for (const ptr of ptrs) {
      this.pdfiumModule.FPDF_CloseDocument(ptr.docPtr);
      this.memoryManager.free(ptr.filePtr);
    }
    const file = {
      id: `${Math.random()}`,
      content: buffer
    };
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `Merge`, "End", fileIds);
    return PdfTaskHelper.resolve(file);
  }
  /**
   * Merges specific pages from multiple PDF documents in a custom order
   *
   * @param mergeConfigs Array of configurations specifying which pages to merge from which documents
   * @returns A PdfTask that resolves with the merged PDF file
   * @public
   */
  mergePages(mergeConfigs) {
    const configIds = mergeConfigs.map((config) => `${config.docId}:${config.pageIndices.join(",")}`).join("|");
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "mergePages", mergeConfigs);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `MergePages`, "Begin", configIds);
    const newDocPtr = this.pdfiumModule.FPDF_CreateNewDocument();
    if (!newDocPtr) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `MergePages`, "End", configIds);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantCreateNewDoc,
        message: "Cannot create new document"
      });
    }
    try {
      for (const config of [...mergeConfigs].reverse()) {
        const ctx = this.cache.getContext(config.docId);
        if (!ctx) {
          this.logger.warn(
            LOG_SOURCE,
            LOG_CATEGORY,
            `Document ${config.docId} is not open, skipping`
          );
          continue;
        }
        const pageCount = this.pdfiumModule.FPDF_GetPageCount(ctx.docPtr);
        const validPageIndices = config.pageIndices.filter(
          (index) => index >= 0 && index < pageCount
        );
        if (validPageIndices.length === 0) {
          continue;
        }
        const pageString = validPageIndices.map((index) => index + 1).join(",");
        try {
          if (!this.pdfiumModule.FPDF_ImportPages(
            newDocPtr,
            ctx.docPtr,
            pageString,
            0
            // Insert at the beginning
          )) {
            throw new Error(`Failed to import pages ${pageString} from document ${config.docId}`);
          }
        } finally {
        }
      }
      const buffer = this.saveDocument(newDocPtr);
      const file = {
        id: `${Math.random()}`,
        content: buffer
      };
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `MergePages`, "End", configIds);
      return PdfTaskHelper.resolve(file);
    } catch (error) {
      this.logger.error(LOG_SOURCE, LOG_CATEGORY, "mergePages failed", error);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `MergePages`, "End", configIds);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantImportPages,
        message: error instanceof Error ? error.message : "Failed to merge pages"
      });
    } finally {
      if (newDocPtr) {
        this.pdfiumModule.FPDF_CloseDocument(newDocPtr);
      }
    }
  }
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
  setDocumentEncryption(doc, userPassword, ownerPassword, allowedFlags) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "setDocumentEncryption", doc, allowedFlags);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const result = this.pdfiumModule.EPDF_SetEncryption(
      ctx.docPtr,
      userPassword,
      ownerPassword,
      allowedFlags
    );
    return PdfTaskHelper.resolve(result);
  }
  /**
   * Marks document for encryption removal on save.
   * When saveAsCopy is called, the document will be saved without encryption.
   *
   * @param doc - Document to remove encryption from
   * @returns true on success
   *
   * @public
   */
  removeEncryption(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "removeEncryption", doc);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const result = this.pdfiumModule.EPDF_RemoveEncryption(ctx.docPtr);
    return PdfTaskHelper.resolve(result);
  }
  /**
   * Attempts to unlock owner permissions for an already-opened encrypted document.
   *
   * @param doc - Document to unlock
   * @param ownerPassword - The owner password
   * @returns true on success, false on failure
   *
   * @public
   */
  unlockOwnerPermissions(doc, ownerPassword) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "unlockOwnerPermissions", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const success = this.pdfiumModule.EPDF_UnlockOwnerPermissions(ctx.docPtr, ownerPassword);
    return PdfTaskHelper.resolve(success);
  }
  /**
   * Check if a document is encrypted.
   *
   * @param doc - Document to check
   * @returns true if the document is encrypted
   *
   * @public
   */
  isEncrypted(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "isEncrypted", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const result = this.pdfiumModule.EPDF_IsEncrypted(ctx.docPtr);
    return PdfTaskHelper.resolve(result);
  }
  /**
   * Check if owner permissions are currently unlocked.
   *
   * @param doc - Document to check
   * @returns true if owner permissions are unlocked
   *
   * @public
   */
  isOwnerUnlocked(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "isOwnerUnlocked", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const result = this.pdfiumModule.EPDF_IsOwnerUnlocked(ctx.docPtr);
    return PdfTaskHelper.resolve(result);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.saveAsCopy}
   *
   * @public
   */
  saveAsCopy(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "saveAsCopy", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SaveAsCopy`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SaveAsCopy`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const buffer = this.saveDocument(ctx.docPtr);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SaveAsCopy`, "End", doc.id);
    return PdfTaskHelper.resolve(buffer);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.closeDocument}
   *
   * @public
   */
  closeDocument(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "closeDocument", doc);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `CloseDocument`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) return PdfTaskHelper.resolve(true);
    ctx.dispose();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `CloseDocument`, "End", doc.id);
    return PdfTaskHelper.resolve(true);
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.closeAllDocuments}
   *
   * @public
   */
  closeAllDocuments() {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "closeAllDocuments");
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `CloseAllDocuments`, "Begin");
    this.cache.closeAllDocuments();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `CloseAllDocuments`, "End");
    return PdfTaskHelper.resolve(true);
  }
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
  addTextContent(doc, page, pagePtr, annotationPtr, annotation) {
    if (!this.setAnnotationIcon(annotationPtr, annotation.icon || PdfAnnotationIcon.Comment)) {
      return false;
    }
    if (annotation.state && !this.setAnnotString(annotationPtr, "State", annotation.state)) {
      return false;
    }
    if (annotation.stateModel && !this.setAnnotString(annotationPtr, "StateModel", annotation.stateModel)) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    const strokeColor = annotation.strokeColor ?? annotation.color ?? "#FFFF00";
    if (!this.setAnnotationColor(annotationPtr, strokeColor, PdfAnnotationColorType.Color)) {
      return false;
    }
    if (!annotation.flags) {
      if (!this.setAnnotationFlags(annotationPtr, ["print", "noZoom", "noRotate"])) {
        return false;
      }
    }
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addCaretContent(doc, page, pagePtr, annotationPtr, annotation) {
    if (annotation.strokeColor) {
      this.setAnnotationColor(annotationPtr, annotation.strokeColor, PdfAnnotationColorType.Color);
    }
    if (annotation.opacity !== void 0) {
      this.setAnnotationOpacity(annotationPtr, annotation.opacity);
    }
    if (annotation.intent) {
      this.setAnnotIntent(annotationPtr, annotation.intent);
    }
    this.setRectangleDifferences(annotationPtr, annotation.rectangleDifferences);
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addFreeTextContent(doc, page, pagePtr, annotationPtr, annotation) {
    if (!this.setBorderStyle(annotationPtr, PdfAnnotationBorderStyle.SOLID, 0)) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    if (!this.setAnnotationTextAlignment(annotationPtr, annotation.textAlign)) {
      return false;
    }
    if (!this.setAnnotationVerticalAlignment(annotationPtr, annotation.verticalAlign)) {
      return false;
    }
    if (!this.setAnnotationDefaultAppearance(
      annotationPtr,
      annotation.fontFamily,
      annotation.fontSize,
      annotation.fontColor
    )) {
      return false;
    }
    if (annotation.intent && !this.setAnnotIntent(annotationPtr, annotation.intent)) {
      return false;
    }
    const bgColor = annotation.color ?? annotation.backgroundColor;
    if (!bgColor || bgColor === "transparent") {
      if (!this.pdfiumModule.EPDFAnnot_ClearColor(annotationPtr, PdfAnnotationColorType.Color)) {
        return false;
      }
    } else if (!this.setAnnotationColor(annotationPtr, bgColor ?? "#FFFFFF", PdfAnnotationColorType.Color)) {
      return false;
    }
    this.setRectangleDifferences(annotationPtr, annotation.rectangleDifferences);
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addInkStroke(doc, page, pagePtr, annotationPtr, annotation) {
    if (!this.setBorderStyle(annotationPtr, PdfAnnotationBorderStyle.SOLID, annotation.strokeWidth)) {
      return false;
    }
    if (!this.setInkList(doc, page, annotationPtr, annotation.inkList)) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    const strokeColor = annotation.strokeColor ?? annotation.color ?? "#FFFF00";
    if (!this.setAnnotationColor(annotationPtr, strokeColor, PdfAnnotationColorType.Color)) {
      return false;
    }
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addLineContent(doc, page, pagePtr, annotationPtr, annotation) {
    var _a, _b;
    if (!this.setLinePoints(
      doc,
      page,
      annotationPtr,
      annotation.linePoints.start,
      annotation.linePoints.end
    )) {
      return false;
    }
    if (!this.setLineEndings(
      annotationPtr,
      ((_a = annotation.lineEndings) == null ? void 0 : _a.start) ?? PdfAnnotationLineEnding.None,
      ((_b = annotation.lineEndings) == null ? void 0 : _b.end) ?? PdfAnnotationLineEnding.None
    )) {
      return false;
    }
    if (!this.setBorderStyle(annotationPtr, annotation.strokeStyle, annotation.strokeWidth)) {
      return false;
    }
    if (!this.setBorderDashPattern(annotationPtr, annotation.strokeDashArray ?? [])) {
      return false;
    }
    if (annotation.intent && !this.setAnnotIntent(annotationPtr, annotation.intent)) {
      return false;
    }
    if (!annotation.color || annotation.color === "transparent") {
      if (!this.pdfiumModule.EPDFAnnot_ClearColor(annotationPtr, PdfAnnotationColorType.InteriorColor)) {
        return false;
      }
    } else if (!this.setAnnotationColor(
      annotationPtr,
      annotation.color ?? "#FFFF00",
      PdfAnnotationColorType.InteriorColor
    )) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    if (!this.setAnnotationColor(
      annotationPtr,
      annotation.strokeColor ?? "#FFFF00",
      PdfAnnotationColorType.Color
    )) {
      return false;
    }
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addPolyContent(doc, page, pagePtr, annotationPtr, annotation) {
    var _a, _b;
    if (annotation.type === PdfAnnotationSubtype.POLYLINE && !this.setLineEndings(
      annotationPtr,
      ((_a = annotation.lineEndings) == null ? void 0 : _a.start) ?? PdfAnnotationLineEnding.None,
      ((_b = annotation.lineEndings) == null ? void 0 : _b.end) ?? PdfAnnotationLineEnding.None
    )) {
      return false;
    }
    if (!this.setPdfAnnoVertices(doc, page, annotationPtr, annotation.vertices)) {
      return false;
    }
    if (!this.setBorderStyle(annotationPtr, annotation.strokeStyle, annotation.strokeWidth)) {
      return false;
    }
    if (!this.setBorderDashPattern(annotationPtr, annotation.strokeDashArray ?? [])) {
      return false;
    }
    if (annotation.intent && !this.setAnnotIntent(annotationPtr, annotation.intent)) {
      return false;
    }
    if (!annotation.color || annotation.color === "transparent") {
      if (!this.pdfiumModule.EPDFAnnot_ClearColor(annotationPtr, PdfAnnotationColorType.InteriorColor)) {
        return false;
      }
    } else if (!this.setAnnotationColor(
      annotationPtr,
      annotation.color ?? "#FFFF00",
      PdfAnnotationColorType.InteriorColor
    )) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    if (!this.setAnnotationColor(
      annotationPtr,
      annotation.strokeColor ?? "#FFFF00",
      PdfAnnotationColorType.Color
    )) {
      return false;
    }
    if (annotation.type === PdfAnnotationSubtype.POLYGON) {
      const poly = annotation;
      this.setRectangleDifferences(annotationPtr, poly.rectangleDifferences);
      this.setBorderEffect(annotationPtr, poly.cloudyBorderIntensity);
    }
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addLinkContent(doc, page, docPtr, pagePtr, annotationPtr, annotation) {
    const style = annotation.strokeStyle ?? PdfAnnotationBorderStyle.UNDERLINE;
    const width = annotation.strokeWidth ?? 2;
    if (!this.setBorderStyle(annotationPtr, style, width)) {
      return false;
    }
    if (annotation.strokeDashArray && !this.setBorderDashPattern(annotationPtr, annotation.strokeDashArray)) {
      return false;
    }
    if (annotation.strokeColor) {
      if (!this.setAnnotationColor(
        annotationPtr,
        annotation.strokeColor,
        PdfAnnotationColorType.Color
      )) {
        return false;
      }
    }
    if (annotation.target) {
      if (!this.applyLinkTarget(docPtr, annotationPtr, annotation.target)) {
        return false;
      }
    }
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addShapeContent(doc, page, pagePtr, annotationPtr, annotation) {
    if (!this.setBorderStyle(annotationPtr, annotation.strokeStyle, annotation.strokeWidth)) {
      return false;
    }
    if (!this.setBorderDashPattern(annotationPtr, annotation.strokeDashArray ?? [])) {
      return false;
    }
    if (!annotation.color || annotation.color === "transparent") {
      if (!this.pdfiumModule.EPDFAnnot_ClearColor(annotationPtr, PdfAnnotationColorType.InteriorColor)) {
        return false;
      }
    } else if (!this.setAnnotationColor(
      annotationPtr,
      annotation.color ?? "#FFFF00",
      PdfAnnotationColorType.InteriorColor
    )) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    if (!this.setAnnotationColor(
      annotationPtr,
      annotation.strokeColor ?? "#FFFF00",
      PdfAnnotationColorType.Color
    )) {
      return false;
    }
    this.setRectangleDifferences(annotationPtr, annotation.rectangleDifferences);
    this.setBorderEffect(annotationPtr, annotation.cloudyBorderIntensity);
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
  /**
   * Add highlight content to annotation
   * @param page - page info
   * @param annotationPtr - pointer to highlight annotation
   * @param annotation - highlight annotation
   * @returns whether highlight content is added to annotation
   *
   * @private
   */
  addTextMarkupContent(doc, page, pagePtr, annotationPtr, annotation) {
    if (!this.syncQuadPointsAnno(doc, page, annotationPtr, annotation.segmentRects)) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    const strokeColor = annotation.strokeColor ?? annotation.color ?? "#FFFF00";
    if (!this.setAnnotationColor(annotationPtr, strokeColor, PdfAnnotationColorType.Color)) {
      return false;
    }
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addRedactContent(doc, page, pagePtr, annotationPtr, annotation) {
    if (!this.syncQuadPointsAnno(doc, page, annotationPtr, annotation.segmentRects)) {
      return false;
    }
    if (!this.setAnnotationOpacity(annotationPtr, annotation.opacity ?? 1)) {
      return false;
    }
    if (!annotation.color || annotation.color === "transparent") {
      if (!this.pdfiumModule.EPDFAnnot_ClearColor(annotationPtr, PdfAnnotationColorType.InteriorColor)) {
        return false;
      }
    } else if (!this.setAnnotationColor(
      annotationPtr,
      annotation.color,
      PdfAnnotationColorType.InteriorColor
    )) {
      return false;
    }
    if (!annotation.overlayColor || annotation.overlayColor === "transparent") {
      if (!this.pdfiumModule.EPDFAnnot_ClearColor(annotationPtr, PdfAnnotationColorType.OverlayColor)) {
        return false;
      }
    } else if (!this.setAnnotationColor(
      annotationPtr,
      annotation.overlayColor,
      PdfAnnotationColorType.OverlayColor
    )) {
      return false;
    }
    if (!annotation.strokeColor || annotation.strokeColor === "transparent") {
      if (!this.pdfiumModule.EPDFAnnot_ClearColor(annotationPtr, PdfAnnotationColorType.Color)) {
        return false;
      }
    } else if (!this.setAnnotationColor(annotationPtr, annotation.strokeColor, PdfAnnotationColorType.Color)) {
      return false;
    }
    if (!this.setOverlayText(annotationPtr, annotation.overlayText)) {
      return false;
    }
    if (annotation.overlayTextRepeat !== void 0 && !this.setOverlayTextRepeat(annotationPtr, annotation.overlayTextRepeat)) {
      return false;
    }
    if (annotation.fontFamily !== void 0 || annotation.fontSize !== void 0) {
      if (!this.setAnnotationDefaultAppearance(
        annotationPtr,
        annotation.fontFamily ?? PdfStandardFont.Helvetica,
        annotation.fontSize ?? 12,
        annotation.fontColor ?? "#000000"
      )) {
        return false;
      }
    }
    if (annotation.textAlign !== void 0 && !this.setAnnotationTextAlignment(annotationPtr, annotation.textAlign)) {
      return false;
    }
    return this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation);
  }
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
  addStampContent(doc, docPtr, page, pagePtr, annotationPtr, annotation, imageData) {
    if (annotation.icon && !this.setAnnotationIcon(annotationPtr, annotation.icon)) {
      return false;
    }
    if (annotation.subject && !this.setAnnotString(annotationPtr, "Subj", annotation.subject)) {
      return false;
    }
    if (imageData) {
      for (let i = this.pdfiumModule.FPDFAnnot_GetObjectCount(annotationPtr) - 1; i >= 0; i--) {
        this.pdfiumModule.FPDFAnnot_RemoveObject(annotationPtr, i);
      }
      if (!this.addImageObject(doc, docPtr, page, pagePtr, annotationPtr, annotation.rect, imageData)) {
        return false;
      }
    }
    if (!this.applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation)) {
      return false;
    }
    return !!this.pdfiumModule.EPDFAnnot_UpdateAppearanceToRect(annotationPtr, PdfStampFit.Cover);
  }
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
  addImageObject(doc, docPtr, page, pagePtr, annotationPtr, rect, imageData) {
    const bytesPerPixel = 4;
    const pixelCount = imageData.width * imageData.height;
    const bitmapBufferPtr = this.memoryManager.malloc(bytesPerPixel * pixelCount);
    if (!bitmapBufferPtr) {
      return false;
    }
    for (let i = 0; i < pixelCount; i++) {
      const red = imageData.data[i * bytesPerPixel];
      const green = imageData.data[i * bytesPerPixel + 1];
      const blue = imageData.data[i * bytesPerPixel + 2];
      const alpha = imageData.data[i * bytesPerPixel + 3];
      this.pdfiumModule.pdfium.setValue(bitmapBufferPtr + i * bytesPerPixel, blue, "i8");
      this.pdfiumModule.pdfium.setValue(bitmapBufferPtr + i * bytesPerPixel + 1, green, "i8");
      this.pdfiumModule.pdfium.setValue(bitmapBufferPtr + i * bytesPerPixel + 2, red, "i8");
      this.pdfiumModule.pdfium.setValue(bitmapBufferPtr + i * bytesPerPixel + 3, alpha, "i8");
    }
    const format = 4;
    const bitmapPtr = this.pdfiumModule.FPDFBitmap_CreateEx(
      imageData.width,
      imageData.height,
      format,
      bitmapBufferPtr,
      0
    );
    if (!bitmapPtr) {
      this.memoryManager.free(bitmapBufferPtr);
      return false;
    }
    const imageObjectPtr = this.pdfiumModule.FPDFPageObj_NewImageObj(docPtr);
    if (!imageObjectPtr) {
      this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
      this.memoryManager.free(bitmapBufferPtr);
      return false;
    }
    if (!this.pdfiumModule.FPDFImageObj_SetBitmap(pagePtr, 0, imageObjectPtr, bitmapPtr)) {
      this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
      this.pdfiumModule.FPDFPageObj_Destroy(imageObjectPtr);
      this.memoryManager.free(bitmapBufferPtr);
      return false;
    }
    const matrixPtr = this.memoryManager.malloc(6 * 4);
    this.pdfiumModule.pdfium.setValue(matrixPtr, imageData.width, "float");
    this.pdfiumModule.pdfium.setValue(matrixPtr + 4, 0, "float");
    this.pdfiumModule.pdfium.setValue(matrixPtr + 8, 0, "float");
    this.pdfiumModule.pdfium.setValue(matrixPtr + 12, imageData.height, "float");
    this.pdfiumModule.pdfium.setValue(matrixPtr + 16, 0, "float");
    this.pdfiumModule.pdfium.setValue(matrixPtr + 20, 0, "float");
    if (!this.pdfiumModule.FPDFPageObj_SetMatrix(imageObjectPtr, matrixPtr)) {
      this.memoryManager.free(matrixPtr);
      this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
      this.pdfiumModule.FPDFPageObj_Destroy(imageObjectPtr);
      this.memoryManager.free(bitmapBufferPtr);
      return false;
    }
    this.memoryManager.free(matrixPtr);
    const pagePos = this.convertDevicePointToPagePoint(doc, page, {
      x: rect.origin.x,
      y: rect.origin.y + imageData.height
      // shift down by the image height
    });
    this.pdfiumModule.FPDFPageObj_Transform(imageObjectPtr, 1, 0, 0, 1, pagePos.x, pagePos.y);
    if (!this.pdfiumModule.FPDFAnnot_AppendObject(annotationPtr, imageObjectPtr)) {
      this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
      this.pdfiumModule.FPDFPageObj_Destroy(imageObjectPtr);
      this.memoryManager.free(bitmapBufferPtr);
      return false;
    }
    this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
    this.memoryManager.free(bitmapBufferPtr);
    return true;
  }
  /**
   * Save document to array buffer
   * @param docPtr - pointer to pdf document
   * @returns array buffer contains the pdf content
   *
   * @private
   */
  saveDocument(docPtr) {
    const writerPtr = this.pdfiumModule.PDFiumExt_OpenFileWriter();
    this.pdfiumModule.PDFiumExt_SaveAsCopy(docPtr, writerPtr);
    const size = this.pdfiumModule.PDFiumExt_GetFileWriterSize(writerPtr);
    const dataPtr = this.memoryManager.malloc(size);
    this.pdfiumModule.PDFiumExt_GetFileWriterData(writerPtr, dataPtr, size);
    const buffer = new ArrayBuffer(size);
    const view = new DataView(buffer);
    for (let i = 0; i < size; i++) {
      view.setInt8(i, this.pdfiumModule.pdfium.getValue(dataPtr + i, "i8"));
    }
    this.memoryManager.free(dataPtr);
    this.pdfiumModule.PDFiumExt_CloseFileWriter(writerPtr);
    return buffer;
  }
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
  readCatalogLanguage(docPtr) {
    const byteLen = this.pdfiumModule.EPDFCatalog_GetLanguage(docPtr, 0, 0) >>> 0;
    if (byteLen === 0) return null;
    if (byteLen === 2) return "";
    return readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => this.pdfiumModule.EPDFCatalog_GetLanguage(docPtr, buffer, bufferLength),
      this.pdfiumModule.pdfium.UTF16ToString,
      byteLen
    );
  }
  /**
   * Read metadata from pdf document
   * @param docPtr - pointer to pdf document
   * @param key - key of metadata field
   * @returns metadata value
   *
   * @private
   */
  readMetaText(docPtr, key) {
    const exists = !!this.pdfiumModule.EPDF_HasMetaText(docPtr, key);
    if (!exists) return null;
    const len = this.pdfiumModule.FPDF_GetMetaText(docPtr, key, 0, 0);
    if (len === 2) return "";
    return readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => this.pdfiumModule.FPDF_GetMetaText(docPtr, key, buffer, bufferLength),
      this.pdfiumModule.pdfium.UTF16ToString,
      len
    );
  }
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
  setMetaText(docPtr, key, value) {
    if (value == null || value.length === 0) {
      const ok = this.pdfiumModule.EPDF_SetMetaText(docPtr, key, 0);
      return !!ok;
    }
    const bytes = 2 * (value.length + 1);
    const ptr = this.memoryManager.malloc(bytes);
    try {
      this.pdfiumModule.pdfium.stringToUTF16(value, ptr, bytes);
      const ok = this.pdfiumModule.EPDF_SetMetaText(docPtr, key, ptr);
      return !!ok;
    } finally {
      this.memoryManager.free(ptr);
    }
  }
  /**
   * Read the document's trapped status via PDFium.
   * Falls back to `Unknown` on unexpected values.
   *
   * @private
   */
  getMetaTrapped(docPtr) {
    const raw = Number(this.pdfiumModule.EPDF_GetMetaTrapped(docPtr));
    switch (raw) {
      case PdfTrappedStatus.NotSet:
      case PdfTrappedStatus.True:
      case PdfTrappedStatus.False:
      case PdfTrappedStatus.Unknown:
        return raw;
      default:
        return PdfTrappedStatus.Unknown;
    }
  }
  /**
   * Write (or clear) the document's trapped status via PDFium.
   * Pass `null`/`undefined` to remove the `/Trapped` key.
   *
   * @private
   */
  setMetaTrapped(docPtr, status) {
    const toSet = status == null || status === void 0 ? PdfTrappedStatus.NotSet : status;
    const valid = toSet === PdfTrappedStatus.NotSet || toSet === PdfTrappedStatus.True || toSet === PdfTrappedStatus.False || toSet === PdfTrappedStatus.Unknown;
    if (!valid) return false;
    return !!this.pdfiumModule.EPDF_SetMetaTrapped(docPtr, toSet);
  }
  /**
   * Get the number of keys in the document's Info dictionary.
   * @param docPtr - pointer to pdf document
   * @param customOnly - if true, only count non-reserved (custom) keys; if false, count all keys.
   * @returns the number of keys (possibly 0). On error, returns 0.
   *
   * @private
   */
  getMetaKeyCount(docPtr, customOnly) {
    return Number(this.pdfiumModule.EPDF_GetMetaKeyCount(docPtr, customOnly)) | 0;
  }
  /**
   * Get the name of the Info dictionary key at |index|.
   * @param docPtr - pointer to pdf document
   * @param index - 0-based key index in the order returned by PDFium.
   * @param customOnly - if true, indexes only over non-reserved (custom) keys; if false, indexes over all keys.
   * @returns the name of the key, or null if the key is not found.
   *
   * @private
   */
  getMetaKeyName(docPtr, index, customOnly) {
    const len = this.pdfiumModule.EPDF_GetMetaKeyName(docPtr, index, customOnly, 0, 0);
    if (!len) return null;
    return readString(
      this.pdfiumModule.pdfium,
      (buffer, buflen) => this.pdfiumModule.EPDF_GetMetaKeyName(docPtr, index, customOnly, buffer, buflen),
      this.pdfiumModule.pdfium.UTF8ToString,
      len
    );
  }
  /**
   * Read all metadata from the document's Info dictionary.
   * @param docPtr - pointer to pdf document
   * @param customOnly - if true, only read non-reserved (custom) keys; if false, read all keys.
   * @returns all metadata
   *
   * @private
   */
  readAllMeta(docPtr, customOnly = true) {
    const n = this.getMetaKeyCount(docPtr, customOnly);
    const out = {};
    for (let i = 0; i < n; i++) {
      const key = this.getMetaKeyName(docPtr, i, customOnly);
      if (!key) continue;
      out[key] = this.readMetaText(docPtr, key);
    }
    return out;
  }
  /**
   * Read bookmarks in the pdf document
   * @param docPtr - pointer to pdf document
   * @param rootBookmarkPtr - pointer to root bookmark
   * @returns bookmarks in the pdf document
   *
   * @private
   */
  readPdfBookmarks(docPtr, rootBookmarkPtr = 0) {
    let bookmarkPtr = this.pdfiumModule.FPDFBookmark_GetFirstChild(docPtr, rootBookmarkPtr);
    const bookmarks = [];
    while (bookmarkPtr) {
      const bookmark = this.readPdfBookmark(docPtr, bookmarkPtr);
      bookmarks.push(bookmark);
      const nextBookmarkPtr = this.pdfiumModule.FPDFBookmark_GetNextSibling(docPtr, bookmarkPtr);
      bookmarkPtr = nextBookmarkPtr;
    }
    return bookmarks;
  }
  /**
   * Read bookmark in the pdf document
   * @param docPtr - pointer to pdf document
   * @param bookmarkPtr - pointer to bookmark object
   * @returns pdf bookmark object
   *
   * @private
   */
  readPdfBookmark(docPtr, bookmarkPtr) {
    const title = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.FPDFBookmark_GetTitle(bookmarkPtr, buffer, bufferLength);
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const bookmarks = this.readPdfBookmarks(docPtr, bookmarkPtr);
    const target = this.readPdfBookmarkTarget(
      docPtr,
      () => {
        return this.pdfiumModule.FPDFBookmark_GetAction(bookmarkPtr);
      },
      () => {
        return this.pdfiumModule.FPDFBookmark_GetDest(docPtr, bookmarkPtr);
      }
    );
    return {
      title,
      target,
      children: bookmarks
    };
  }
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
  readPageTextRects(page, docPtr, pagePtr, textPagePtr) {
    const rectsCount = this.pdfiumModule.FPDFText_CountRects(textPagePtr, 0, -1);
    const textRects = [];
    for (let i = 0; i < rectsCount; i++) {
      const topPtr = this.memoryManager.malloc(8);
      const leftPtr = this.memoryManager.malloc(8);
      const rightPtr = this.memoryManager.malloc(8);
      const bottomPtr = this.memoryManager.malloc(8);
      const isSucceed = this.pdfiumModule.FPDFText_GetRect(
        textPagePtr,
        i,
        leftPtr,
        topPtr,
        rightPtr,
        bottomPtr
      );
      if (!isSucceed) {
        this.memoryManager.free(leftPtr);
        this.memoryManager.free(topPtr);
        this.memoryManager.free(rightPtr);
        this.memoryManager.free(bottomPtr);
        continue;
      }
      const left = this.pdfiumModule.pdfium.getValue(leftPtr, "double");
      const top = this.pdfiumModule.pdfium.getValue(topPtr, "double");
      const right = this.pdfiumModule.pdfium.getValue(rightPtr, "double");
      const bottom = this.pdfiumModule.pdfium.getValue(bottomPtr, "double");
      this.memoryManager.free(leftPtr);
      this.memoryManager.free(topPtr);
      this.memoryManager.free(rightPtr);
      this.memoryManager.free(bottomPtr);
      const deviceXPtr = this.memoryManager.malloc(4);
      const deviceYPtr = this.memoryManager.malloc(4);
      this.pdfiumModule.FPDF_PageToDevice(
        pagePtr,
        0,
        0,
        page.size.width,
        page.size.height,
        0,
        left,
        top,
        deviceXPtr,
        deviceYPtr
      );
      const x = this.pdfiumModule.pdfium.getValue(deviceXPtr, "i32");
      const y = this.pdfiumModule.pdfium.getValue(deviceYPtr, "i32");
      this.memoryManager.free(deviceXPtr);
      this.memoryManager.free(deviceYPtr);
      const rect = {
        origin: {
          x,
          y
        },
        size: {
          width: Math.ceil(Math.abs(right - left)),
          height: Math.ceil(Math.abs(top - bottom))
        }
      };
      const utf16Length = this.pdfiumModule.FPDFText_GetBoundedText(
        textPagePtr,
        left,
        top,
        right,
        bottom,
        0,
        0
      );
      const bytesCount = (utf16Length + 1) * 2;
      const textBuffer = this.memoryManager.malloc(bytesCount);
      this.pdfiumModule.FPDFText_GetBoundedText(
        textPagePtr,
        left,
        top,
        right,
        bottom,
        textBuffer,
        utf16Length
      );
      const content = this.pdfiumModule.pdfium.UTF16ToString(textBuffer);
      this.memoryManager.free(textBuffer);
      const charIndex = this.pdfiumModule.FPDFText_GetCharIndexAtPos(textPagePtr, left, top, 2, 2);
      let fontFamily = "";
      let fontSize = rect.size.height;
      if (charIndex >= 0) {
        fontSize = this.pdfiumModule.FPDFText_GetFontSize(textPagePtr, charIndex);
        const fontNameLength = this.pdfiumModule.FPDFText_GetFontInfo(
          textPagePtr,
          charIndex,
          0,
          0,
          0
        );
        const bytesCount2 = fontNameLength + 1;
        const textBufferPtr = this.memoryManager.malloc(bytesCount2);
        const flagsPtr = this.memoryManager.malloc(4);
        this.pdfiumModule.FPDFText_GetFontInfo(
          textPagePtr,
          charIndex,
          textBufferPtr,
          bytesCount2,
          flagsPtr
        );
        fontFamily = this.pdfiumModule.pdfium.UTF8ToString(textBufferPtr);
        this.memoryManager.free(textBufferPtr);
        this.memoryManager.free(flagsPtr);
      }
      const textRect = {
        content,
        rect,
        font: {
          family: fontFamily,
          size: fontSize
        }
      };
      textRects.push(textRect);
    }
    return textRects;
  }
  /**
   * Return geometric + logical text layout for one page
   * (glyph-only implementation, no FPDFText_GetRect).
   *
   * @public
   */
  getPageGeometry(doc, page) {
    const label = "getPageGeometry";
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const textPagePtr = pageCtx.getTextPage();
    const glyphCount = this.pdfiumModule.FPDFText_CountChars(textPagePtr);
    const glyphs = [];
    for (let i = 0; i < glyphCount; i++) {
      const g = this.readGlyphInfo(page, pageCtx.pagePtr, textPagePtr, i);
      glyphs.push(g);
    }
    const runs = this.buildRunsFromGlyphs(glyphs, textPagePtr);
    pageCtx.release();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", doc.id);
    return PdfTaskHelper.resolve({ runs });
  }
  /**
   * Group consecutive glyphs that belong to the same CPDF_TextObject
   * using FPDFText_GetTextObject(), and calculate rotation from glyph positions.
   */
  buildRunsFromGlyphs(glyphs, textPagePtr) {
    const runs = [];
    let current = null;
    let curObjPtr = null;
    let bounds = null;
    for (let i = 0; i < glyphs.length; i++) {
      const g = glyphs[i];
      const objPtr = this.pdfiumModule.FPDFText_GetTextObject(textPagePtr, i);
      if (objPtr !== curObjPtr) {
        curObjPtr = objPtr;
        current = {
          rect: {
            x: g.origin.x,
            y: g.origin.y,
            width: g.size.width,
            height: g.size.height
          },
          charStart: i,
          glyphs: [],
          fontSize: this.pdfiumModule.FPDFText_GetFontSize(textPagePtr, i)
        };
        bounds = {
          minX: g.origin.x,
          minY: g.origin.y,
          maxX: g.origin.x + g.size.width,
          maxY: g.origin.y + g.size.height
        };
        runs.push(current);
      }
      current.glyphs.push({
        x: g.origin.x,
        y: g.origin.y,
        width: g.size.width,
        height: g.size.height,
        flags: g.isEmpty ? 2 : g.isSpace ? 1 : 0,
        ...g.tightOrigin && { tightX: g.tightOrigin.x, tightY: g.tightOrigin.y },
        ...g.tightSize && { tightWidth: g.tightSize.width, tightHeight: g.tightSize.height }
      });
      if (g.isEmpty) {
        continue;
      }
      const right = g.origin.x + g.size.width;
      const bottom = g.origin.y + g.size.height;
      bounds.minX = Math.min(bounds.minX, g.origin.x);
      bounds.minY = Math.min(bounds.minY, g.origin.y);
      bounds.maxX = Math.max(bounds.maxX, right);
      bounds.maxY = Math.max(bounds.maxY, bottom);
      current.rect.x = bounds.minX;
      current.rect.y = bounds.minY;
      current.rect.width = bounds.maxX - bounds.minX;
      current.rect.height = bounds.maxY - bounds.minY;
    }
    return runs;
  }
  /**
   * Rich text runs: groups consecutive characters sharing the same
   * text object, font, size, and fill color into structured segments
   * with full font metadata and bounding boxes in PDF page coordinates.
   *
   * @public
   */
  getPageTextRuns(doc, page) {
    const label = "getPageTextRuns";
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const textPagePtr = pageCtx.getTextPage();
    const charCount = this.pdfiumModule.FPDFText_CountChars(textPagePtr);
    const runs = [];
    let runStart = 0;
    let curObjPtr = null;
    let curFont = null;
    let curFontSize = 0;
    let curColor = null;
    let bounds = null;
    const flushRun = (end) => {
      if (curObjPtr === null || curFont === null || curColor === null || bounds === null) return;
      const count = end - runStart;
      if (count <= 0) return;
      const bufPtr = this.memoryManager.malloc(2 * (count + 1));
      this.pdfiumModule.FPDFText_GetText(textPagePtr, runStart, count, bufPtr);
      const text = stripPdfUnwantedMarkers(this.pdfiumModule.pdfium.UTF16ToString(bufPtr));
      this.memoryManager.free(bufPtr);
      runs.push({
        text,
        rect: {
          origin: { x: bounds.minX, y: bounds.minY },
          size: {
            width: Math.max(1, bounds.maxX - bounds.minX),
            height: Math.max(1, bounds.maxY - bounds.minY)
          }
        },
        font: curFont,
        fontSize: curFontSize,
        color: curColor,
        charIndex: runStart,
        charCount: count
      });
    };
    const rPtr = this.memoryManager.malloc(4);
    const gPtr = this.memoryManager.malloc(4);
    const bPtr = this.memoryManager.malloc(4);
    const aPtr = this.memoryManager.malloc(4);
    const rectPtr = this.memoryManager.malloc(16);
    const dx1Ptr = this.memoryManager.malloc(4);
    const dy1Ptr = this.memoryManager.malloc(4);
    const dx2Ptr = this.memoryManager.malloc(4);
    const dy2Ptr = this.memoryManager.malloc(4);
    const italicAnglePtr = this.memoryManager.malloc(4);
    for (let i = 0; i < charCount; i++) {
      const uc = this.pdfiumModule.FPDFText_GetUnicode(textPagePtr, i);
      if (uc === 65534 || uc === 65533) continue;
      const objPtr = this.pdfiumModule.FPDFText_GetTextObject(textPagePtr, i);
      if (objPtr === 0) continue;
      const fontSize = this.pdfiumModule.FPDFText_GetFontSize(textPagePtr, i);
      this.pdfiumModule.FPDFText_GetFillColor(textPagePtr, i, rPtr, gPtr, bPtr, aPtr);
      const red = this.pdfiumModule.pdfium.getValue(rPtr, "i32") & 255;
      const green = this.pdfiumModule.pdfium.getValue(gPtr, "i32") & 255;
      const blue = this.pdfiumModule.pdfium.getValue(bPtr, "i32") & 255;
      const alpha = this.pdfiumModule.pdfium.getValue(aPtr, "i32") & 255;
      const fontInfo = this.readFontInfoFromTextObject(objPtr, italicAnglePtr);
      const needNewRun = curObjPtr === null || objPtr !== curObjPtr || fontInfo.name !== curFont.name || Math.abs(fontSize - curFontSize) > 0.01 || red !== curColor.red || green !== curColor.green || blue !== curColor.blue;
      if (needNewRun) {
        flushRun(i);
        curObjPtr = objPtr;
        curFont = fontInfo;
        curFontSize = fontSize;
        curColor = { red, green, blue, alpha };
        runStart = i;
        bounds = null;
      }
      if (this.pdfiumModule.FPDFText_GetLooseCharBox(textPagePtr, i, rectPtr)) {
        const left = this.pdfiumModule.pdfium.getValue(rectPtr, "float");
        const top = this.pdfiumModule.pdfium.getValue(rectPtr + 4, "float");
        const right = this.pdfiumModule.pdfium.getValue(rectPtr + 8, "float");
        const bottom = this.pdfiumModule.pdfium.getValue(rectPtr + 12, "float");
        if (left !== right && top !== bottom) {
          this.pdfiumModule.FPDF_PageToDevice(
            pageCtx.pagePtr,
            0,
            0,
            page.size.width,
            page.size.height,
            0,
            left,
            top,
            dx1Ptr,
            dy1Ptr
          );
          this.pdfiumModule.FPDF_PageToDevice(
            pageCtx.pagePtr,
            0,
            0,
            page.size.width,
            page.size.height,
            0,
            right,
            bottom,
            dx2Ptr,
            dy2Ptr
          );
          const x1 = this.pdfiumModule.pdfium.getValue(dx1Ptr, "i32");
          const y1 = this.pdfiumModule.pdfium.getValue(dy1Ptr, "i32");
          const x2 = this.pdfiumModule.pdfium.getValue(dx2Ptr, "i32");
          const y2 = this.pdfiumModule.pdfium.getValue(dy2Ptr, "i32");
          const cx = Math.min(x1, x2);
          const cy = Math.min(y1, y2);
          const cw = Math.abs(x2 - x1);
          const ch = Math.abs(y2 - y1);
          if (bounds === null) {
            bounds = { minX: cx, minY: cy, maxX: cx + cw, maxY: cy + ch };
          } else {
            bounds.minX = Math.min(bounds.minX, cx);
            bounds.minY = Math.min(bounds.minY, cy);
            bounds.maxX = Math.max(bounds.maxX, cx + cw);
            bounds.maxY = Math.max(bounds.maxY, cy + ch);
          }
        }
      }
    }
    flushRun(charCount);
    [rPtr, gPtr, bPtr, aPtr, rectPtr, dx1Ptr, dy1Ptr, dx2Ptr, dy2Ptr, italicAnglePtr].forEach(
      (p) => this.memoryManager.free(p)
    );
    pageCtx.release();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", doc.id);
    return PdfTaskHelper.resolve({ runs });
  }
  /**
   * Read font metadata from a text object handle via FPDFFont_* APIs.
   */
  readFontInfoFromTextObject(textObjPtr, italicAnglePtr) {
    const fontPtr = this.pdfiumModule.FPDFTextObj_GetFont(textObjPtr);
    let name = "";
    let familyName = "";
    let weight = 400;
    let italic = false;
    let monospaced = false;
    let embedded = false;
    if (fontPtr) {
      const nameLen = this.pdfiumModule.FPDFFont_GetBaseFontName(fontPtr, 0, 0);
      if (nameLen > 0) {
        const nameBuf = this.memoryManager.malloc(nameLen + 1);
        this.pdfiumModule.FPDFFont_GetBaseFontName(fontPtr, nameBuf, nameLen + 1);
        name = this.pdfiumModule.pdfium.UTF8ToString(nameBuf);
        this.memoryManager.free(nameBuf);
      }
      const famLen = this.pdfiumModule.FPDFFont_GetFamilyName(fontPtr, 0, 0);
      if (famLen > 0) {
        const famBuf = this.memoryManager.malloc(famLen + 1);
        this.pdfiumModule.FPDFFont_GetFamilyName(fontPtr, famBuf, famLen + 1);
        familyName = this.pdfiumModule.pdfium.UTF8ToString(famBuf);
        this.memoryManager.free(famBuf);
      }
      weight = this.pdfiumModule.FPDFFont_GetWeight(fontPtr);
      embedded = this.pdfiumModule.FPDFFont_GetIsEmbedded(fontPtr) !== 0;
      if (this.pdfiumModule.FPDFFont_GetItalicAngle(fontPtr, italicAnglePtr)) {
        const angle = this.pdfiumModule.pdfium.getValue(italicAnglePtr, "i32");
        italic = angle !== 0;
      }
      const flags = this.pdfiumModule.FPDFFont_GetFlags(fontPtr);
      monospaced = (flags & 1) !== 0;
    }
    return { name, familyName, weight, italic, monospaced, embedded };
  }
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
  readGlyphInfo(page, pagePtr, textPagePtr, charIndex) {
    const dx1Ptr = this.memoryManager.malloc(4);
    const dy1Ptr = this.memoryManager.malloc(4);
    const dx2Ptr = this.memoryManager.malloc(4);
    const dy2Ptr = this.memoryManager.malloc(4);
    const rectPtr = this.memoryManager.malloc(16);
    const tLeftPtr = this.memoryManager.malloc(8);
    const tRightPtr = this.memoryManager.malloc(8);
    const tBottomPtr = this.memoryManager.malloc(8);
    const tTopPtr = this.memoryManager.malloc(8);
    const allPtrs = [
      rectPtr,
      dx1Ptr,
      dy1Ptr,
      dx2Ptr,
      dy2Ptr,
      tLeftPtr,
      tRightPtr,
      tBottomPtr,
      tTopPtr
    ];
    let x = 0, y = 0, width = 0, height = 0, isSpace = false;
    let tightOrigin;
    let tightSize;
    if (this.pdfiumModule.FPDFText_GetLooseCharBox(textPagePtr, charIndex, rectPtr)) {
      const left = this.pdfiumModule.pdfium.getValue(rectPtr, "float");
      const top = this.pdfiumModule.pdfium.getValue(rectPtr + 4, "float");
      const right = this.pdfiumModule.pdfium.getValue(rectPtr + 8, "float");
      const bottom = this.pdfiumModule.pdfium.getValue(rectPtr + 12, "float");
      if (left === right || top === bottom) {
        allPtrs.forEach((p) => this.memoryManager.free(p));
        return {
          origin: { x: 0, y: 0 },
          size: { width: 0, height: 0 },
          isEmpty: true
        };
      }
      this.pdfiumModule.FPDF_PageToDevice(
        pagePtr,
        0,
        0,
        page.size.width,
        page.size.height,
        0,
        left,
        top,
        dx1Ptr,
        dy1Ptr
      );
      this.pdfiumModule.FPDF_PageToDevice(
        pagePtr,
        0,
        0,
        page.size.width,
        page.size.height,
        0,
        right,
        bottom,
        dx2Ptr,
        dy2Ptr
      );
      const x1 = this.pdfiumModule.pdfium.getValue(dx1Ptr, "i32");
      const y1 = this.pdfiumModule.pdfium.getValue(dy1Ptr, "i32");
      const x2 = this.pdfiumModule.pdfium.getValue(dx2Ptr, "i32");
      const y2 = this.pdfiumModule.pdfium.getValue(dy2Ptr, "i32");
      x = Math.min(x1, x2);
      y = Math.min(y1, y2);
      width = Math.max(1, Math.abs(x2 - x1));
      height = Math.max(1, Math.abs(y2 - y1));
      if (this.pdfiumModule.FPDFText_GetCharBox(
        textPagePtr,
        charIndex,
        tLeftPtr,
        tRightPtr,
        tBottomPtr,
        tTopPtr
      )) {
        const tLeft = this.pdfiumModule.pdfium.getValue(tLeftPtr, "double");
        const tRight = this.pdfiumModule.pdfium.getValue(tRightPtr, "double");
        const tBottom = this.pdfiumModule.pdfium.getValue(tBottomPtr, "double");
        const tTop = this.pdfiumModule.pdfium.getValue(tTopPtr, "double");
        this.pdfiumModule.FPDF_PageToDevice(
          pagePtr,
          0,
          0,
          page.size.width,
          page.size.height,
          0,
          tLeft,
          tTop,
          dx1Ptr,
          dy1Ptr
        );
        this.pdfiumModule.FPDF_PageToDevice(
          pagePtr,
          0,
          0,
          page.size.width,
          page.size.height,
          0,
          tRight,
          tBottom,
          dx2Ptr,
          dy2Ptr
        );
        const tx1 = this.pdfiumModule.pdfium.getValue(dx1Ptr, "i32");
        const ty1 = this.pdfiumModule.pdfium.getValue(dy1Ptr, "i32");
        const tx2 = this.pdfiumModule.pdfium.getValue(dx2Ptr, "i32");
        const ty2 = this.pdfiumModule.pdfium.getValue(dy2Ptr, "i32");
        tightOrigin = { x: Math.min(tx1, tx2), y: Math.min(ty1, ty2) };
        tightSize = {
          width: Math.max(1, Math.abs(tx2 - tx1)),
          height: Math.max(1, Math.abs(ty2 - ty1))
        };
      }
      const uc = this.pdfiumModule.FPDFText_GetUnicode(textPagePtr, charIndex);
      isSpace = uc === 32;
    }
    allPtrs.forEach((p) => this.memoryManager.free(p));
    return {
      origin: { x, y },
      size: { width, height },
      ...tightOrigin && { tightOrigin },
      ...tightSize && { tightSize },
      ...isSpace && { isSpace }
    };
  }
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
  getPageGlyphs(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageGlyphs", doc, page);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "getPageGlyphs", "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "getPageGlyphs", "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const textPagePtr = pageCtx.getTextPage();
    const total = this.pdfiumModule.FPDFText_CountChars(textPagePtr);
    const glyphs = new Array(total);
    for (let i = 0; i < total; i++) {
      const g = this.readGlyphInfo(page, pageCtx.pagePtr, textPagePtr, i);
      if (g.isEmpty) {
        continue;
      }
      glyphs[i] = { ...g };
    }
    pageCtx.release();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "getPageGlyphs", "End", doc.id);
    return PdfTaskHelper.resolve(glyphs);
  }
  readCharBox(page, pagePtr, textPagePtr, charIndex) {
    const topPtr = this.memoryManager.malloc(8);
    const leftPtr = this.memoryManager.malloc(8);
    const bottomPtr = this.memoryManager.malloc(8);
    const rightPtr = this.memoryManager.malloc(8);
    let x = 0;
    let y = 0;
    let width = 0;
    let height = 0;
    if (this.pdfiumModule.FPDFText_GetCharBox(
      textPagePtr,
      charIndex,
      leftPtr,
      rightPtr,
      bottomPtr,
      topPtr
    )) {
      const top = this.pdfiumModule.pdfium.getValue(topPtr, "double");
      const left = this.pdfiumModule.pdfium.getValue(leftPtr, "double");
      const bottom = this.pdfiumModule.pdfium.getValue(bottomPtr, "double");
      const right = this.pdfiumModule.pdfium.getValue(rightPtr, "double");
      const deviceXPtr = this.memoryManager.malloc(4);
      const deviceYPtr = this.memoryManager.malloc(4);
      this.pdfiumModule.FPDF_PageToDevice(
        pagePtr,
        0,
        0,
        page.size.width,
        page.size.height,
        0,
        left,
        top,
        deviceXPtr,
        deviceYPtr
      );
      x = this.pdfiumModule.pdfium.getValue(deviceXPtr, "i32");
      y = this.pdfiumModule.pdfium.getValue(deviceYPtr, "i32");
      this.memoryManager.free(deviceXPtr);
      this.memoryManager.free(deviceYPtr);
      width = Math.ceil(Math.abs(right - left));
      height = Math.ceil(Math.abs(top - bottom));
    }
    this.memoryManager.free(topPtr);
    this.memoryManager.free(leftPtr);
    this.memoryManager.free(bottomPtr);
    this.memoryManager.free(rightPtr);
    return {
      origin: {
        x,
        y
      },
      size: {
        width,
        height
      }
    };
  }
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
  readPageAnnotations(doc, ctx, page) {
    return ctx.borrowPage(page.index, (pageCtx) => {
      const annotationCount = this.pdfiumModule.FPDFPage_GetAnnotCount(pageCtx.pagePtr);
      const annotations = [];
      for (let i = 0; i < annotationCount; i++) {
        pageCtx.withAnnotation(i, (annotPtr) => {
          const anno = this.readPageAnnotation(doc, ctx.docPtr, page, annotPtr, pageCtx);
          if (anno) annotations.push(anno);
        });
      }
      return annotations;
    });
  }
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
  readPageAnnotationsRaw(doc, ctx, page) {
    const count = this.pdfiumModule.EPDFPage_GetAnnotCountRaw(ctx.docPtr, page.index);
    if (count <= 0) return [];
    const out = [];
    for (let i = 0; i < count; ++i) {
      const annotPtr = this.pdfiumModule.EPDFPage_GetAnnotRaw(ctx.docPtr, page.index, i);
      if (!annotPtr) continue;
      try {
        const anno = this.readPageAnnotation(doc, ctx.docPtr, page, annotPtr);
        if (anno) out.push(anno);
      } finally {
        this.pdfiumModule.FPDFPage_CloseAnnot(annotPtr);
      }
    }
    return out;
  }
  /**
   * Get page annotations (public API, returns Task)
   *
   * @param doc - pdf document
   * @param page - page info
   * @returns task with annotations on the pdf page
   *
   * @public
   */
  getPageAnnotationsRaw(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageAnnotationsRaw", doc, page);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `GetPageAnnotationsRaw`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const out = this.readPageAnnotationsRaw(doc, ctx, page);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `GetPageAnnotationsRaw`,
      "End",
      `${doc.id}-${page.index}`
    );
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      "getPageAnnotationsRaw",
      `${doc.id}-${page.index}`,
      out
    );
    return PdfTaskHelper.resolve(out);
  }
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
  readPageAnnotation(doc, docPtr, page, annotationPtr, pageCtx) {
    let index = this.getAnnotString(annotationPtr, "NM");
    if (!index || !isUuidV4(index)) {
      index = uuidV4();
      this.setAnnotString(annotationPtr, "NM", index);
    }
    const subType = this.pdfiumModule.FPDFAnnot_GetSubtype(
      annotationPtr
    );
    let annotation;
    switch (subType) {
      case PdfAnnotationSubtype.TEXT:
        {
          annotation = this.readPdfTextAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.FREETEXT:
        {
          annotation = this.readPdfFreeTextAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.LINK:
        {
          annotation = this.readPdfLinkAnno(doc, page, docPtr, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.WIDGET:
        if (pageCtx) {
          return this.readPdfWidgetAnno(doc, page, annotationPtr, pageCtx.getFormHandle(), index);
        }
      case PdfAnnotationSubtype.FILEATTACHMENT:
        {
          annotation = this.readPdfFileAttachmentAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.INK:
        {
          annotation = this.readPdfInkAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.POLYGON:
        {
          annotation = this.readPdfPolygonAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.POLYLINE:
        {
          annotation = this.readPdfPolylineAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.LINE:
        {
          annotation = this.readPdfLineAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.HIGHLIGHT:
        annotation = this.readPdfHighlightAnno(doc, page, annotationPtr, index);
        break;
      case PdfAnnotationSubtype.STAMP:
        {
          annotation = this.readPdfStampAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.SQUARE:
        {
          annotation = this.readPdfSquareAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.CIRCLE:
        {
          annotation = this.readPdfCircleAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.UNDERLINE:
        {
          annotation = this.readPdfUnderlineAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.SQUIGGLY:
        {
          annotation = this.readPdfSquigglyAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.STRIKEOUT:
        {
          annotation = this.readPdfStrikeOutAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.CARET:
        {
          annotation = this.readPdfCaretAnno(doc, page, annotationPtr, index);
        }
        break;
      case PdfAnnotationSubtype.REDACT:
        {
          annotation = this.readPdfRedactAnno(doc, page, annotationPtr, index);
        }
        break;
      default:
        {
          annotation = this.readPdfAnno(doc, page, subType, annotationPtr, index);
        }
        break;
    }
    if (annotation) {
      annotation = this.reverseRotateAnnotationOnLoad(annotation);
      const apModes = this.pdfiumModule.EPDFAnnot_GetAvailableAppearanceModes(annotationPtr);
      if (apModes) {
        annotation.appearanceModes = apModes;
      }
    }
    return annotation;
  }
  /**
   * On load, if a vertex-type annotation has rotation metadata in EPDFCustom,
   * reverse-rotate the PDF's physically rotated vertices by -rotation to recover
   * the unrotated vertices for runtime editing.
   */
  reverseRotateAnnotationOnLoad(annotation) {
    const rotation = annotation.rotation;
    const unrotatedRect = annotation.unrotatedRect;
    if (!rotation || rotation === 0 || !unrotatedRect) {
      return annotation;
    }
    const center = {
      x: unrotatedRect.origin.x + unrotatedRect.size.width / 2,
      y: unrotatedRect.origin.y + unrotatedRect.size.height / 2
    };
    switch (annotation.type) {
      case PdfAnnotationSubtype.INK: {
        const ink = annotation;
        const unrotatedInkList = ink.inkList.map((stroke) => ({
          points: stroke.points.map((p) => this.rotatePointForSave(p, center, -rotation))
        }));
        return { ...ink, inkList: unrotatedInkList };
      }
      case PdfAnnotationSubtype.LINE: {
        const line = annotation;
        return {
          ...line,
          linePoints: {
            start: this.rotatePointForSave(line.linePoints.start, center, -rotation),
            end: this.rotatePointForSave(line.linePoints.end, center, -rotation)
          }
        };
      }
      case PdfAnnotationSubtype.POLYGON: {
        const poly = annotation;
        return {
          ...poly,
          vertices: poly.vertices.map((v) => this.rotatePointForSave(v, center, -rotation))
        };
      }
      case PdfAnnotationSubtype.POLYLINE: {
        const polyline = annotation;
        return {
          ...polyline,
          vertices: polyline.vertices.map((v) => this.rotatePointForSave(v, center, -rotation))
        };
      }
      default:
        return annotation;
    }
  }
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
  readAnnotationColor(annotationPtr, colorType = PdfAnnotationColorType.Color) {
    const rPtr = this.memoryManager.malloc(4);
    const gPtr = this.memoryManager.malloc(4);
    const bPtr = this.memoryManager.malloc(4);
    const ok = this.pdfiumModule.EPDFAnnot_GetColor(annotationPtr, colorType, rPtr, gPtr, bPtr);
    let colour;
    if (ok) {
      colour = {
        red: this.pdfiumModule.pdfium.getValue(rPtr, "i32") & 255,
        green: this.pdfiumModule.pdfium.getValue(gPtr, "i32") & 255,
        blue: this.pdfiumModule.pdfium.getValue(bPtr, "i32") & 255
      };
    }
    this.memoryManager.free(rPtr);
    this.memoryManager.free(gPtr);
    this.memoryManager.free(bPtr);
    return colour;
  }
  /**
   * Get the fill/stroke colour annotation.
   *
   * @param annotationPtr - pointer to the annotation whose colour is being set
   * @param colorType - which colour to get (0 = fill, 1 = stroke)
   * @returns WebColor with hex color
   *
   * @private
   */
  getAnnotationColor(annotationPtr, colorType = PdfAnnotationColorType.Color) {
    const annotationColor = this.readAnnotationColor(annotationPtr, colorType);
    return annotationColor ? pdfColorToWebColor(annotationColor) : void 0;
  }
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
  setAnnotationColor(annotationPtr, webColor, colorType = PdfAnnotationColorType.Color) {
    const pdfColor = webColorToPdfColor(webColor);
    return this.pdfiumModule.EPDFAnnot_SetColor(
      annotationPtr,
      colorType,
      pdfColor.red & 255,
      pdfColor.green & 255,
      pdfColor.blue & 255
    );
  }
  /**
   * Get the opacity of the annotation.
   *
   * @param annotationPtr - pointer to the annotation whose opacity is being set
   * @returns opacity (0-1)
   *
   * @private
   */
  getAnnotationOpacity(annotationPtr) {
    const opacityPtr = this.memoryManager.malloc(4);
    const ok = this.pdfiumModule.EPDFAnnot_GetOpacity(annotationPtr, opacityPtr);
    const opacity = ok ? this.pdfiumModule.pdfium.getValue(opacityPtr, "i32") : 255;
    this.memoryManager.free(opacityPtr);
    return pdfAlphaToWebOpacity(opacity);
  }
  /**
   * Set the opacity of the annotation.
   *
   * @param annotationPtr - pointer to the annotation whose opacity is being set
   * @param opacity - opacity (0-1)
   * @returns true on success
   *
   * @private
   */
  setAnnotationOpacity(annotationPtr, opacity) {
    const pdfOpacity = webOpacityToPdfAlpha(opacity);
    return this.pdfiumModule.EPDFAnnot_SetOpacity(annotationPtr, pdfOpacity & 255);
  }
  /**
   * Get the rotation angle (in degrees) from the annotation's /Rotate entry.
   * Returns 0 if no rotation is set or on error.
   *
   * @param annotationPtr - pointer to the annotation
   * @returns rotation in degrees (0 if not set)
   */
  getAnnotationRotation(annotationPtr) {
    const rotationPtr = this.memoryManager.malloc(4);
    const ok = this.pdfiumModule.EPDFAnnot_GetRotate(annotationPtr, rotationPtr);
    if (!ok) {
      this.memoryManager.free(rotationPtr);
      return 0;
    }
    const rotation = this.pdfiumModule.pdfium.getValue(rotationPtr, "float");
    this.memoryManager.free(rotationPtr);
    return rotation;
  }
  /**
   * Set the rotation angle (in degrees) on the annotation's /Rotate entry.
   * A value of 0 removes the /Rotate key.
   *
   * @param annotationPtr - pointer to the annotation
   * @param rotation - rotation in degrees (clockwise)
   * @returns true on success
   */
  setAnnotationRotation(annotationPtr, rotation) {
    return !!this.pdfiumModule.EPDFAnnot_SetRotate(annotationPtr, rotation);
  }
  /**
   * Get the EmbedPDF extended rotation (in degrees) from the annotation's
   * /EPDFRotate entry. Returns 0 if not set or on error.
   *
   * @param annotationPtr - pointer to the annotation
   * @returns rotation in degrees (0 if not set)
   */
  getAnnotExtendedRotation(annotationPtr) {
    const rotationPtr = this.memoryManager.malloc(4);
    const ok = this.pdfiumModule.EPDFAnnot_GetExtendedRotation(annotationPtr, rotationPtr);
    if (!ok) {
      this.memoryManager.free(rotationPtr);
      return 0;
    }
    const rotation = this.pdfiumModule.pdfium.getValue(rotationPtr, "float");
    this.memoryManager.free(rotationPtr);
    return rotation;
  }
  /**
   * Set the EmbedPDF extended rotation (in degrees) on the annotation's
   * /EPDFRotate entry. A value of 0 removes the key.
   *
   * @param annotationPtr - pointer to the annotation
   * @param rotation - rotation in degrees
   * @returns true on success
   */
  setAnnotExtendedRotation(annotationPtr, rotation) {
    return !!this.pdfiumModule.EPDFAnnot_SetExtendedRotation(annotationPtr, rotation);
  }
  /**
   * Read the EmbedPDF unrotated rect from the annotation's /EPDFUnrotatedRect
   * entry. Returns the raw page-space rect (same format as `readPageAnnoRect`)
   * or null if not set.
   *
   * @param annotationPtr - pointer to the annotation
   * @returns raw `{ left, top, right, bottom }` in page coords, or null
   */
  readAnnotUnrotatedRect(annotationPtr) {
    const rectPtr = this.memoryManager.malloc(4 * 4);
    const ok = this.pdfiumModule.EPDFAnnot_GetUnrotatedRect(annotationPtr, rectPtr);
    if (!ok) {
      this.memoryManager.free(rectPtr);
      return null;
    }
    const left = this.pdfiumModule.pdfium.getValue(rectPtr, "float");
    const top = this.pdfiumModule.pdfium.getValue(rectPtr + 4, "float");
    const right = this.pdfiumModule.pdfium.getValue(rectPtr + 8, "float");
    const bottom = this.pdfiumModule.pdfium.getValue(rectPtr + 12, "float");
    this.memoryManager.free(rectPtr);
    if (left === 0 && top === 0 && right === 0 && bottom === 0) {
      return null;
    }
    return { left, top, right, bottom };
  }
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
  setAnnotUnrotatedRect(doc, page, annotPtr, rect) {
    const x0d = Math.floor(rect.origin.x);
    const y0d = Math.floor(rect.origin.y);
    const x1d = Math.floor(rect.origin.x + rect.size.width);
    const y1d = Math.floor(rect.origin.y + rect.size.height);
    const TL = this.convertDevicePointToPagePoint(doc, page, { x: x0d, y: y0d });
    const TR = this.convertDevicePointToPagePoint(doc, page, { x: x1d, y: y0d });
    const BR = this.convertDevicePointToPagePoint(doc, page, { x: x1d, y: y1d });
    const BL = this.convertDevicePointToPagePoint(doc, page, { x: x0d, y: y1d });
    let left = Math.min(TL.x, TR.x, BR.x, BL.x);
    let right = Math.max(TL.x, TR.x, BR.x, BL.x);
    let bottom = Math.min(TL.y, TR.y, BR.y, BL.y);
    let top = Math.max(TL.y, TR.y, BR.y, BL.y);
    if (left > right) [left, right] = [right, left];
    if (bottom > top) [bottom, top] = [top, bottom];
    const ptr = this.memoryManager.malloc(16);
    const pdf = this.pdfiumModule.pdfium;
    pdf.setValue(ptr + 0, left, "float");
    pdf.setValue(ptr + 4, top, "float");
    pdf.setValue(ptr + 8, right, "float");
    pdf.setValue(ptr + 12, bottom, "float");
    const ok = this.pdfiumModule.EPDFAnnot_SetUnrotatedRect(annotPtr, ptr);
    this.memoryManager.free(ptr);
    return !!ok;
  }
  /**
   * Fetch the `/Q` text-alignment value from a **FreeText** annotation.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @returns `PdfTextAlignment`
   */
  getAnnotationTextAlignment(annotationPtr) {
    return this.pdfiumModule.EPDFAnnot_GetTextAlignment(annotationPtr);
  }
  /**
   * Write the `/Q` text-alignment value into a **FreeText** annotation
   * and clear the existing appearance stream so it can be regenerated.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @param alignment     `PdfTextAlignment`
   * @returns `true` on success
   */
  setAnnotationTextAlignment(annotationPtr, alignment) {
    return !!this.pdfiumModule.EPDFAnnot_SetTextAlignment(annotationPtr, alignment);
  }
  /**
   * Fetch the `/EPDF:VerticalAlignment` vertical-alignment value from a **FreeText** annotation.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @returns `PdfVerticalAlignment`
   */
  getAnnotationVerticalAlignment(annotationPtr) {
    return this.pdfiumModule.EPDFAnnot_GetVerticalAlignment(annotationPtr);
  }
  /**
   * Write the `/EPDF:VerticalAlignment` vertical-alignment value into a **FreeText** annotation
   * and clear the existing appearance stream so it can be regenerated.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @param alignment     `PdfVerticalAlignment`
   * @returns `true` on success
   */
  setAnnotationVerticalAlignment(annotationPtr, alignment) {
    return !!this.pdfiumModule.EPDFAnnot_SetVerticalAlignment(annotationPtr, alignment);
  }
  /**
   * Get the overlay text from a Redact annotation.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @returns overlay text string or `undefined` if not set
   *
   * @private
   */
  getOverlayText(annotationPtr) {
    const len = this.pdfiumModule.EPDFAnnot_GetOverlayText(annotationPtr, 0, 0);
    if (len === 0) return void 0;
    const bytes = (len + 1) * 2;
    const ptr = this.memoryManager.malloc(bytes);
    this.pdfiumModule.EPDFAnnot_GetOverlayText(annotationPtr, ptr, bytes);
    const value = this.pdfiumModule.pdfium.UTF16ToString(ptr);
    this.memoryManager.free(ptr);
    return value || void 0;
  }
  /**
   * Set the overlay text on a Redact annotation.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @param text overlay text to set, or undefined/empty to clear
   * @returns `true` on success
   *
   * @private
   */
  setOverlayText(annotationPtr, text) {
    if (!text) {
      return this.pdfiumModule.EPDFAnnot_SetOverlayText(annotationPtr, 0);
    }
    return this.withWString(text, (wPtr) => {
      return this.pdfiumModule.EPDFAnnot_SetOverlayText(annotationPtr, wPtr);
    });
  }
  /**
   * Get whether overlay text repeats in a Redact annotation.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @returns `true` if overlay text repeats
   *
   * @private
   */
  getOverlayTextRepeat(annotationPtr) {
    return this.pdfiumModule.EPDFAnnot_GetOverlayTextRepeat(annotationPtr);
  }
  /**
   * Set whether overlay text repeats in a Redact annotation.
   *
   * @param annotationPtr pointer returned by `FPDFPage_GetAnnot`
   * @param repeat whether overlay text should repeat
   * @returns `true` on success
   *
   * @private
   */
  setOverlayTextRepeat(annotationPtr, repeat) {
    return this.pdfiumModule.EPDFAnnot_SetOverlayTextRepeat(annotationPtr, repeat);
  }
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
  getAnnotationDefaultAppearance(annotationPtr) {
    const fontPtr = this.memoryManager.malloc(4);
    const sizePtr = this.memoryManager.malloc(4);
    const rPtr = this.memoryManager.malloc(4);
    const gPtr = this.memoryManager.malloc(4);
    const bPtr = this.memoryManager.malloc(4);
    const ok = !!this.pdfiumModule.EPDFAnnot_GetDefaultAppearance(
      annotationPtr,
      fontPtr,
      sizePtr,
      rPtr,
      gPtr,
      bPtr
    );
    if (!ok) {
      [fontPtr, sizePtr, rPtr, gPtr, bPtr].forEach((p) => this.memoryManager.free(p));
      return;
    }
    const pdf = this.pdfiumModule.pdfium;
    const font = pdf.getValue(fontPtr, "i32");
    const fontSize = pdf.getValue(sizePtr, "float");
    const red = pdf.getValue(rPtr, "i32") & 255;
    const green = pdf.getValue(gPtr, "i32") & 255;
    const blue = pdf.getValue(bPtr, "i32") & 255;
    [fontPtr, sizePtr, rPtr, gPtr, bPtr].forEach((p) => this.memoryManager.free(p));
    return {
      fontFamily: font,
      fontSize,
      fontColor: pdfColorToWebColor({ red, green, blue })
    };
  }
  /**
   * Write a **default appearance** (`/DA`) into a FreeText annotation.
   *
   * @param annotationPtr pointer to `FPDF_ANNOTATION`
   * @param font          `FPDF_STANDARD_FONT` enum value
   * @param fontSize      size in points (≥ 0)
   * @param color         CSS-style `#rrggbb` string (alpha ignored)
   * @returns `true` on success
   */
  setAnnotationDefaultAppearance(annotationPtr, font, fontSize, color) {
    const resolvedFont = font === PdfStandardFont.Unknown ? PdfStandardFont.Helvetica : font;
    const { red, green, blue } = webColorToPdfColor(color);
    return !!this.pdfiumModule.EPDFAnnot_SetDefaultAppearance(
      annotationPtr,
      resolvedFont,
      fontSize,
      red & 255,
      green & 255,
      blue & 255
    );
  }
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
  getBorderStyle(annotationPtr) {
    const widthPtr = this.memoryManager.malloc(4);
    let width = 0;
    let style = PdfAnnotationBorderStyle.UNKNOWN;
    let ok = false;
    style = this.pdfiumModule.EPDFAnnot_GetBorderStyle(annotationPtr, widthPtr);
    width = this.pdfiumModule.pdfium.getValue(widthPtr, "float");
    ok = style !== PdfAnnotationBorderStyle.UNKNOWN;
    this.memoryManager.free(widthPtr);
    return { ok, style, width };
  }
  setBorderStyle(annotationPtr, style, width) {
    return this.pdfiumModule.EPDFAnnot_SetBorderStyle(annotationPtr, style, width);
  }
  /**
   * Get the icon of the annotation
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @returns `PdfAnnotationIcon`
   */
  getAnnotationIcon(annotationPtr) {
    return this.pdfiumModule.EPDFAnnot_GetIcon(annotationPtr);
  }
  /**
   * Set the icon of the annotation
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @param icon - `PdfAnnotationIcon`
   * @returns `true` on success
   */
  setAnnotationIcon(annotationPtr, icon) {
    return this.pdfiumModule.EPDFAnnot_SetIcon(annotationPtr, icon);
  }
  /**
   * Get the reply type of the annotation (RT property per ISO 32000-2)
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @returns `PdfAnnotationReplyType`
   */
  getReplyType(annotationPtr) {
    return this.pdfiumModule.EPDFAnnot_GetReplyType(annotationPtr);
  }
  /**
   * Set the reply type of the annotation (RT property per ISO 32000-2)
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @param replyType - `PdfAnnotationReplyType`
   * @returns `true` on success
   */
  setReplyType(annotationPtr, replyType) {
    return this.pdfiumModule.EPDFAnnot_SetReplyType(
      annotationPtr,
      replyType ?? PdfAnnotationReplyType.Unknown
    );
  }
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
  getBorderEffect(annotationPtr) {
    const intensityPtr = this.memoryManager.malloc(4);
    const ok = !!this.pdfiumModule.EPDFAnnot_GetBorderEffect(annotationPtr, intensityPtr);
    const intensity = ok ? this.pdfiumModule.pdfium.getValue(intensityPtr, "float") : 0;
    this.memoryManager.free(intensityPtr);
    return { ok, intensity };
  }
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
  getRectangleDifferences(annotationPtr) {
    const lPtr = this.memoryManager.malloc(4);
    const tPtr = this.memoryManager.malloc(4);
    const rPtr = this.memoryManager.malloc(4);
    const bPtr = this.memoryManager.malloc(4);
    const ok = !!this.pdfiumModule.EPDFAnnot_GetRectangleDifferences(
      annotationPtr,
      lPtr,
      tPtr,
      rPtr,
      bPtr
    );
    const pdf = this.pdfiumModule.pdfium;
    const left = pdf.getValue(lPtr, "float");
    const top = pdf.getValue(tPtr, "float");
    const right = pdf.getValue(rPtr, "float");
    const bottom = pdf.getValue(bPtr, "float");
    this.memoryManager.free(lPtr);
    this.memoryManager.free(tPtr);
    this.memoryManager.free(rPtr);
    this.memoryManager.free(bPtr);
    return { ok, left, top, right, bottom };
  }
  /**
   * Sets the /RD array on an annotation.
   *
   * @param annotationPtr  pointer to an `FPDF_ANNOTATION`
   * @param rd  the four inset values, or `undefined` to clear
   * @returns `true` on success
   */
  setRectangleDifferences(annotationPtr, rd) {
    if (!rd) {
      return this.pdfiumModule.EPDFAnnot_ClearRectangleDifferences(annotationPtr);
    }
    return this.pdfiumModule.EPDFAnnot_SetRectangleDifferences(
      annotationPtr,
      rd.left,
      rd.top,
      rd.right,
      rd.bottom
    );
  }
  /**
   * Sets or clears the /BE (border effect) dictionary on an annotation.
   *
   * @param annotationPtr  pointer to an `FPDF_ANNOTATION`
   * @param intensity  cloudy border intensity, or `undefined` to clear
   * @returns `true` on success
   */
  setBorderEffect(annotationPtr, intensity) {
    if (intensity === void 0 || intensity <= 0) {
      return this.pdfiumModule.EPDFAnnot_ClearBorderEffect(annotationPtr);
    }
    return this.pdfiumModule.EPDFAnnot_SetBorderEffect(annotationPtr, intensity);
  }
  /**
   * Get the date of the annotation
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @param key - 'M' for modified date, 'CreationDate' for creation date
   * @returns `Date` or `undefined` when PDFium can't read the date
   */
  getAnnotationDate(annotationPtr, key) {
    const raw = this.getAnnotString(annotationPtr, key);
    return raw ? pdfDateToDate(raw) : void 0;
  }
  /**
   * Set the date of the annotation
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @param key - 'M' for modified date, 'CreationDate' for creation date
   * @param date - `Date` to set
   * @returns `true` on success
   */
  setAnnotationDate(annotationPtr, key, date) {
    const raw = dateToPdfDate(date);
    return this.setAnnotString(annotationPtr, key, raw);
  }
  /**
   * Get the date of the attachment
   *
   * @param attachmentPtr - pointer to an `FPDF_ATTACHMENT`
   * @param key - 'ModDate' for modified date, 'CreationDate' for creation date
   * @returns `Date` or `undefined` when PDFium can't read the date
   */
  getAttachmentDate(attachmentPtr, key) {
    const raw = this.getAttachmentString(attachmentPtr, key);
    return raw ? pdfDateToDate(raw) : void 0;
  }
  /**
   * Set the date of the attachment
   *
   * @param attachmentPtr - pointer to an `FPDF_ATTACHMENT`
   * @param key - 'ModDate' for modified date, 'CreationDate' for creation date
   * @param date - `Date` to set
   * @returns `true` on success
   */
  setAttachmentDate(attachmentPtr, key, date) {
    const raw = dateToPdfDate(date);
    return this.setAttachmentString(attachmentPtr, key, raw);
  }
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
  getBorderDashPattern(annotationPtr) {
    const count = this.pdfiumModule.EPDFAnnot_GetBorderDashPatternCount(annotationPtr);
    if (count === 0) {
      return { ok: false, pattern: [] };
    }
    const arrPtr = this.memoryManager.malloc(4 * count);
    const okNative = !!this.pdfiumModule.EPDFAnnot_GetBorderDashPattern(
      annotationPtr,
      arrPtr,
      count
    );
    const pattern = [];
    if (okNative) {
      const pdf = this.pdfiumModule.pdfium;
      for (let i = 0; i < count; i++) {
        pattern.push(pdf.getValue(arrPtr + 4 * i, "float"));
      }
    }
    this.memoryManager.free(arrPtr);
    return { ok: okNative, pattern };
  }
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
  setBorderDashPattern(annotationPtr, pattern) {
    if (!pattern || pattern.length === 0) {
      return this.pdfiumModule.EPDFAnnot_SetBorderDashPattern(annotationPtr, 0, 0);
    }
    const clean = pattern.map((n) => Number.isFinite(n) && n > 0 ? n : 0).filter((n) => n > 0);
    if (clean.length === 0) {
      return this.pdfiumModule.EPDFAnnot_SetBorderDashPattern(annotationPtr, 0, 0);
    }
    const bytes = 4 * clean.length;
    const bufPtr = this.memoryManager.malloc(bytes);
    for (let i = 0; i < clean.length; i++) {
      this.pdfiumModule.pdfium.setValue(bufPtr + 4 * i, clean[i], "float");
    }
    const ok = !!this.pdfiumModule.EPDFAnnot_SetBorderDashPattern(
      annotationPtr,
      bufPtr,
      clean.length
    );
    this.memoryManager.free(bufPtr);
    return ok;
  }
  /**
   * Return the `/LE` array (start/end line-ending styles) for a LINE / POLYLINE annot.
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @returns `{ start, end }` or `undefined` when PDFium can't read them
   *
   * @private
   */
  getLineEndings(annotationPtr) {
    const startPtr = this.memoryManager.malloc(4);
    const endPtr = this.memoryManager.malloc(4);
    const ok = !!this.pdfiumModule.EPDFAnnot_GetLineEndings(annotationPtr, startPtr, endPtr);
    if (!ok) {
      this.memoryManager.free(startPtr);
      this.memoryManager.free(endPtr);
      return void 0;
    }
    const start = this.pdfiumModule.pdfium.getValue(startPtr, "i32");
    const end = this.pdfiumModule.pdfium.getValue(endPtr, "i32");
    this.memoryManager.free(startPtr);
    this.memoryManager.free(endPtr);
    return { start, end };
  }
  /**
   * Write the `/LE` array (start/end line-ending styles) for a LINE / POLYLINE annot.
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @param start - start line ending style
   * @param end - end line ending style
   * @returns `true` on success
   */
  setLineEndings(annotationPtr, start, end) {
    return !!this.pdfiumModule.EPDFAnnot_SetLineEndings(annotationPtr, start, end);
  }
  /**
   * Get the start and end points of a LINE / POLYLINE annot.
   * @param doc - pdf document object
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @param page - logical page info object (`PdfPageObject`)
   * @returns `{ start, end }` or `undefined` when PDFium can't read them
   */
  getLinePoints(doc, page, annotationPtr) {
    const startPtr = this.memoryManager.malloc(8);
    const endPtr = this.memoryManager.malloc(8);
    const ok = this.pdfiumModule.FPDFAnnot_GetLine(annotationPtr, startPtr, endPtr);
    if (!ok) {
      this.memoryManager.free(startPtr);
      this.memoryManager.free(endPtr);
      return void 0;
    }
    const pdf = this.pdfiumModule.pdfium;
    const sx = pdf.getValue(startPtr + 0, "float");
    const sy = pdf.getValue(startPtr + 4, "float");
    const ex = pdf.getValue(endPtr + 0, "float");
    const ey = pdf.getValue(endPtr + 4, "float");
    this.memoryManager.free(startPtr);
    this.memoryManager.free(endPtr);
    const start = this.convertPagePointToDevicePoint(doc, page, { x: sx, y: sy });
    const end = this.convertPagePointToDevicePoint(doc, page, { x: ex, y: ey });
    return { start, end };
  }
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
  setLinePoints(doc, page, annotPtr, start, end) {
    const p1 = this.convertDevicePointToPagePoint(doc, page, start);
    const p2 = this.convertDevicePointToPagePoint(doc, page, end);
    if (!p1 || !p2) return false;
    const buf = this.memoryManager.malloc(16);
    const pdf = this.pdfiumModule.pdfium;
    pdf.setValue(buf + 0, p1.x, "float");
    pdf.setValue(buf + 4, p1.y, "float");
    pdf.setValue(buf + 8, p2.x, "float");
    pdf.setValue(buf + 12, p2.y, "float");
    const ok = this.pdfiumModule.EPDFAnnot_SetLine(annotPtr, buf, buf + 8);
    this.memoryManager.free(buf);
    return !!ok;
  }
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
  getQuadPointsAnno(doc, page, annotationPtr) {
    const quadCount = this.pdfiumModule.FPDFAnnot_CountAttachmentPoints(annotationPtr);
    if (quadCount === 0) return [];
    const FS_QUADPOINTSF_SIZE = 8 * 4;
    const quads = [];
    for (let qi = 0; qi < quadCount; qi++) {
      const quadPtr = this.memoryManager.malloc(FS_QUADPOINTSF_SIZE);
      const ok = this.pdfiumModule.FPDFAnnot_GetAttachmentPoints(annotationPtr, qi, quadPtr);
      if (ok) {
        const xs = [];
        const ys = [];
        for (let i = 0; i < 4; i++) {
          const base = quadPtr + i * 8;
          xs.push(this.pdfiumModule.pdfium.getValue(base, "float"));
          ys.push(this.pdfiumModule.pdfium.getValue(base + 4, "float"));
        }
        const p1 = this.convertPagePointToDevicePoint(doc, page, { x: xs[0], y: ys[0] });
        const p2 = this.convertPagePointToDevicePoint(doc, page, { x: xs[1], y: ys[1] });
        const p3 = this.convertPagePointToDevicePoint(doc, page, { x: xs[2], y: ys[2] });
        const p4 = this.convertPagePointToDevicePoint(doc, page, { x: xs[3], y: ys[3] });
        quads.push({ p1, p2, p3, p4 });
      }
      this.memoryManager.free(quadPtr);
    }
    return quads.map(quadToRect);
  }
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
  syncQuadPointsAnno(doc, page, annotPtr, rects) {
    const FS_QUADPOINTSF_SIZE = 8 * 4;
    const pdf = this.pdfiumModule.pdfium;
    const count = this.pdfiumModule.FPDFAnnot_CountAttachmentPoints(annotPtr);
    const buf = this.memoryManager.malloc(FS_QUADPOINTSF_SIZE);
    const writeQuad = (r) => {
      const q = rectToQuad(r);
      const p1 = this.convertDevicePointToPagePoint(doc, page, q.p1);
      const p2 = this.convertDevicePointToPagePoint(doc, page, q.p2);
      const p3 = this.convertDevicePointToPagePoint(doc, page, q.p3);
      const p4 = this.convertDevicePointToPagePoint(doc, page, q.p4);
      pdf.setValue(buf + 0, p1.x, "float");
      pdf.setValue(buf + 4, p1.y, "float");
      pdf.setValue(buf + 8, p2.x, "float");
      pdf.setValue(buf + 12, p2.y, "float");
      pdf.setValue(buf + 16, p4.x, "float");
      pdf.setValue(buf + 20, p4.y, "float");
      pdf.setValue(buf + 24, p3.x, "float");
      pdf.setValue(buf + 28, p3.y, "float");
    };
    const min = Math.min(count, rects.length);
    for (let i = 0; i < min; i++) {
      writeQuad(rects[i]);
      if (!this.pdfiumModule.FPDFAnnot_SetAttachmentPoints(annotPtr, i, buf)) {
        this.memoryManager.free(buf);
        return false;
      }
    }
    for (let i = count; i < rects.length; i++) {
      writeQuad(rects[i]);
      if (!this.pdfiumModule.FPDFAnnot_AppendAttachmentPoints(annotPtr, buf)) {
        this.memoryManager.free(buf);
        return false;
      }
    }
    this.memoryManager.free(buf);
    return true;
  }
  /**
   * Redact text that intersects ANY of the provided **quads** (device-space).
   * Returns `true` if the page changed. Always regenerates the page stream.
   */
  redactTextInRects(doc, page, rects, options) {
    const { recurseForms = true, drawBlackBoxes = false } = options ?? {};
    this.logger.debug(
      "PDFiumEngine",
      "Engine",
      "redactTextInQuads",
      doc.id,
      page.index,
      rects.length
    );
    const label = "RedactTextInQuads";
    this.logger.perf("PDFiumEngine", "Engine", label, "Begin", `${doc.id}-${page.index}`);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf("PDFiumEngine", "Engine", label, "End", `${doc.id}-${page.index}`);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const clean = (rects ?? []).filter(
      (r) => {
        var _a, _b, _c, _d;
        return r && Number.isFinite((_a = r.origin) == null ? void 0 : _a.x) && Number.isFinite((_b = r.origin) == null ? void 0 : _b.y) && Number.isFinite((_c = r.size) == null ? void 0 : _c.width) && Number.isFinite((_d = r.size) == null ? void 0 : _d.height) && r.size.width > 0 && r.size.height > 0;
      }
    );
    if (clean.length === 0) {
      this.logger.perf("PDFiumEngine", "Engine", label, "End", `${doc.id}-${page.index}`);
      return PdfTaskHelper.resolve(false);
    }
    const pageCtx = ctx.acquirePage(page.index);
    const { ptr, count } = this.allocFSQuadsBufferFromRects(doc, page, clean);
    let ok = false;
    try {
      ok = !!this.pdfiumModule.EPDFText_RedactInQuads(
        pageCtx.pagePtr,
        ptr,
        count,
        recurseForms ? true : false,
        false
      );
    } finally {
      this.memoryManager.free(ptr);
    }
    if (ok) {
      ok = !!this.pdfiumModule.FPDFPage_GenerateContent(pageCtx.pagePtr);
    }
    pageCtx.disposeImmediate();
    this.logger.perf("PDFiumEngine", "Engine", label, "End", `${doc.id}-${page.index}`);
    return PdfTaskHelper.resolve(!!ok);
  }
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
  applyRedaction(doc, page, annotation) {
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      "applyRedaction",
      doc.id,
      page.index,
      annotation.id
    );
    const label = "ApplyRedaction";
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "Begin", `${doc.id}-${page.index}`);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const annotPtr = this.getAnnotationByName(pageCtx.pagePtr, annotation.id);
    if (!annotPtr) {
      pageCtx.release();
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.NotFound,
        message: "annotation not found"
      });
    }
    const ok = this.pdfiumModule.EPDFAnnot_ApplyRedaction(pageCtx.pagePtr, annotPtr);
    this.pdfiumModule.FPDFPage_CloseAnnot(annotPtr);
    if (ok) {
      this.pdfiumModule.FPDFPage_GenerateContent(pageCtx.pagePtr);
    }
    pageCtx.disposeImmediate();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
    return PdfTaskHelper.resolve(!!ok);
  }
  /**
   * Apply all redaction annotations on a page, permanently removing content
   * underneath each one and flattening RO streams if present.
   * All redact annotations are removed after successful application.
   *
   * @param doc - document object
   * @param page - page object
   * @returns true if any redactions were applied
   */
  applyAllRedactions(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "applyAllRedactions", doc.id, page.index);
    const label = "ApplyAllRedactions";
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "Begin", `${doc.id}-${page.index}`);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const ok = this.pdfiumModule.EPDFPage_ApplyRedactions(pageCtx.pagePtr);
    if (ok) {
      this.pdfiumModule.FPDFPage_GenerateContent(pageCtx.pagePtr);
    }
    pageCtx.disposeImmediate();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
    return PdfTaskHelper.resolve(!!ok);
  }
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
  flattenAnnotation(doc, page, annotation) {
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      "flattenAnnotation",
      doc.id,
      page.index,
      annotation.id
    );
    const label = "FlattenAnnotation";
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "Begin", `${doc.id}-${page.index}`);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const annotPtr = this.getAnnotationByName(pageCtx.pagePtr, annotation.id);
    if (!annotPtr) {
      pageCtx.release();
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.NotFound,
        message: "annotation not found"
      });
    }
    const ok = this.pdfiumModule.EPDFAnnot_Flatten(pageCtx.pagePtr, annotPtr);
    this.pdfiumModule.FPDFPage_CloseAnnot(annotPtr);
    if (ok) {
      this.pdfiumModule.FPDFPage_GenerateContent(pageCtx.pagePtr);
    }
    pageCtx.disposeImmediate();
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, label, "End", `${doc.id}-${page.index}`);
    return PdfTaskHelper.resolve(!!ok);
  }
  /** Pack device-space Rects into an FS_QUADPOINTSF[] buffer (page space). */
  allocFSQuadsBufferFromRects(doc, page, rects) {
    const STRIDE = 32;
    const count = rects.length;
    const ptr = this.memoryManager.malloc(STRIDE * count);
    const pdf = this.pdfiumModule.pdfium;
    for (let i = 0; i < count; i++) {
      const r = rects[i];
      const q = rectToQuad(r);
      const p1 = this.convertDevicePointToPagePoint(doc, page, q.p1);
      const p2 = this.convertDevicePointToPagePoint(doc, page, q.p2);
      const p3 = this.convertDevicePointToPagePoint(doc, page, q.p3);
      const p4 = this.convertDevicePointToPagePoint(doc, page, q.p4);
      const base = ptr + i * STRIDE;
      pdf.setValue(base + 0, p1.x, "float");
      pdf.setValue(base + 4, p1.y, "float");
      pdf.setValue(base + 8, p2.x, "float");
      pdf.setValue(base + 12, p2.y, "float");
      pdf.setValue(base + 16, p4.x, "float");
      pdf.setValue(base + 20, p4.y, "float");
      pdf.setValue(base + 24, p3.x, "float");
      pdf.setValue(base + 28, p3.y, "float");
    }
    return { ptr, count };
  }
  /**
   * Read ink list from annotation
   * @param doc - pdf document object
   * @param page  - logical page info object (`PdfPageObject`)
   * @param pagePtr - pointer to the page
   * @param annotationPtr - pointer to the annotation whose ink list is needed
   * @returns ink list
   */
  getInkList(doc, page, annotationPtr) {
    const inkList = [];
    const pathCount = this.pdfiumModule.FPDFAnnot_GetInkListCount(annotationPtr);
    if (pathCount <= 0) return inkList;
    const pdf = this.pdfiumModule.pdfium;
    const POINT_STRIDE = 8;
    for (let i = 0; i < pathCount; i++) {
      const points = [];
      const n = this.pdfiumModule.FPDFAnnot_GetInkListPath(annotationPtr, i, 0, 0);
      if (n > 0) {
        const buf = this.memoryManager.malloc(n * POINT_STRIDE);
        this.pdfiumModule.FPDFAnnot_GetInkListPath(annotationPtr, i, buf, n);
        for (let j = 0; j < n; j++) {
          const base = buf + j * POINT_STRIDE;
          const px = pdf.getValue(base + 0, "float");
          const py = pdf.getValue(base + 4, "float");
          const d = this.convertPagePointToDevicePoint(doc, page, { x: px, y: py });
          points.push({ x: d.x, y: d.y });
        }
        this.memoryManager.free(buf);
      }
      inkList.push({ points });
    }
    return inkList;
  }
  /**
   * Add ink list to annotation
   * @param doc - pdf document object
   * @param page  - logical page info object (`PdfPageObject`)
   * @param pagePtr - pointer to the page
   * @param annotationPtr - pointer to the annotation whose ink list is needed
   * @param inkList - ink list array of `PdfInkListObject`
   * @returns `true` if the operation was successful
   */
  setInkList(doc, page, annotationPtr, inkList) {
    const pdf = this.pdfiumModule.pdfium;
    const POINT_STRIDE = 8;
    for (const stroke of inkList) {
      const n = stroke.points.length;
      if (n === 0) continue;
      const buf = this.memoryManager.malloc(n * POINT_STRIDE);
      for (let i = 0; i < n; i++) {
        const pDev = stroke.points[i];
        const pPage = this.convertDevicePointToPagePoint(doc, page, pDev);
        pdf.setValue(buf + i * POINT_STRIDE + 0, pPage.x, "float");
        pdf.setValue(buf + i * POINT_STRIDE + 4, pPage.y, "float");
      }
      const idx = this.pdfiumModule.FPDFAnnot_AddInkStroke(annotationPtr, buf, n);
      this.memoryManager.free(buf);
      if (idx === -1) {
        return false;
      }
    }
    return true;
  }
  /**
   * Read pdf text annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf text annotation
   *
   * @private
   */
  readPdfTextAnno(doc, page, annotationPtr, index) {
    const annoRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, annoRect);
    const state = this.getAnnotString(annotationPtr, "State");
    const stateModel = this.getAnnotString(annotationPtr, "StateModel");
    const color = this.getAnnotationColor(annotationPtr);
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const icon = this.getAnnotationIcon(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.TEXT,
      rect,
      strokeColor: color ?? "#FFFF00",
      color: color ?? "#FFFF00",
      opacity,
      state,
      stateModel,
      icon,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf freetext annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf freetext annotation
   *
   * @private
   */
  readPdfFreeTextAnno(doc, page, annotationPtr, index) {
    const annoRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, annoRect);
    const defaultStyle = this.getAnnotString(annotationPtr, "DS");
    const da = this.getAnnotationDefaultAppearance(annotationPtr);
    const bgColor = this.getAnnotationColor(annotationPtr);
    const textAlign = this.getAnnotationTextAlignment(annotationPtr);
    const verticalAlign = this.getAnnotationVerticalAlignment(annotationPtr);
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const richContent = this.getAnnotRichContent(annotationPtr);
    const rd = this.getRectangleDifferences(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.FREETEXT,
      rect,
      fontFamily: (da == null ? void 0 : da.fontFamily) ?? PdfStandardFont.Unknown,
      fontSize: (da == null ? void 0 : da.fontSize) ?? 12,
      fontColor: (da == null ? void 0 : da.fontColor) ?? "#000000",
      verticalAlign,
      color: bgColor,
      // fill color (matches shape convention)
      backgroundColor: bgColor,
      // deprecated alias
      opacity,
      textAlign,
      defaultStyle,
      richContent,
      ...rd.ok && {
        rectangleDifferences: {
          left: rd.left,
          top: rd.top,
          right: rd.right,
          bottom: rd.bottom
        }
      },
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
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
  readPdfLinkAnno(doc, page, docPtr, annotationPtr, index) {
    const linkPtr = this.pdfiumModule.FPDFAnnot_GetLink(annotationPtr);
    if (!linkPtr) {
      return;
    }
    const annoRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, annoRect);
    const { style: strokeStyle, width: strokeWidth } = this.getBorderStyle(annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr, PdfAnnotationColorType.Color);
    let strokeDashArray;
    if (strokeStyle === PdfAnnotationBorderStyle.DASHED) {
      const { ok, pattern } = this.getBorderDashPattern(annotationPtr);
      if (ok) {
        strokeDashArray = pattern;
      }
    }
    const target = this.readPdfLinkAnnoTarget(
      docPtr,
      () => {
        return this.pdfiumModule.FPDFLink_GetAction(linkPtr);
      },
      () => {
        return this.pdfiumModule.FPDFLink_GetDest(docPtr, linkPtr);
      }
    );
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.LINK,
      rect,
      target,
      strokeColor,
      strokeWidth,
      strokeStyle,
      strokeDashArray,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
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
  readPdfWidgetAnno(doc, page, annotationPtr, formHandle, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const field = this.readPdfWidgetAnnoField(formHandle, annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.WIDGET,
      rect,
      field,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf file attachment annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf file attachment annotation
   *
   * @private
   */
  readPdfFileAttachmentAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.FILEATTACHMENT,
      rect,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf ink annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf ink annotation
   *
   * @private
   */
  readPdfInkAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const strokeColor = this.getAnnotationColor(annotationPtr) ?? "#FF0000";
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const { width: strokeWidth } = this.getBorderStyle(annotationPtr);
    const inkList = this.getInkList(doc, page, annotationPtr);
    const intent = this.getAnnotIntent(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.INK,
      rect,
      ...intent && { intent },
      strokeColor,
      color: strokeColor,
      // deprecated alias
      opacity,
      strokeWidth: strokeWidth === 0 ? 1 : strokeWidth,
      inkList,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf polygon annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf polygon annotation
   *
   * @private
   */
  readPdfPolygonAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const vertices = this.readPdfAnnoVertices(doc, page, annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr);
    const interiorColor = this.getAnnotationColor(
      annotationPtr,
      PdfAnnotationColorType.InteriorColor
    );
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const { style: strokeStyle, width: strokeWidth } = this.getBorderStyle(annotationPtr);
    let strokeDashArray;
    if (strokeStyle === PdfAnnotationBorderStyle.DASHED) {
      const { ok, pattern } = this.getBorderDashPattern(annotationPtr);
      if (ok) {
        strokeDashArray = pattern;
      }
    }
    if (vertices.length > 1) {
      const first = vertices[0];
      const last = vertices[vertices.length - 1];
      if (first.x === last.x && first.y === last.y) {
        vertices.pop();
      }
    }
    const rd = this.getRectangleDifferences(annotationPtr);
    const be = this.getBorderEffect(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.POLYGON,
      rect,
      strokeColor: strokeColor ?? "#FF0000",
      color: interiorColor ?? "transparent",
      opacity,
      strokeWidth: strokeWidth === 0 ? 1 : strokeWidth,
      strokeStyle,
      strokeDashArray,
      vertices,
      ...be.ok && { cloudyBorderIntensity: be.intensity },
      ...rd.ok && {
        rectangleDifferences: {
          left: rd.left,
          top: rd.top,
          right: rd.right,
          bottom: rd.bottom
        }
      },
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf polyline annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf polyline annotation
   *
   * @private
   */
  readPdfPolylineAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const vertices = this.readPdfAnnoVertices(doc, page, annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr);
    const interiorColor = this.getAnnotationColor(
      annotationPtr,
      PdfAnnotationColorType.InteriorColor
    );
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const { style: strokeStyle, width: strokeWidth } = this.getBorderStyle(annotationPtr);
    let strokeDashArray;
    if (strokeStyle === PdfAnnotationBorderStyle.DASHED) {
      const { ok, pattern } = this.getBorderDashPattern(annotationPtr);
      if (ok) {
        strokeDashArray = pattern;
      }
    }
    const lineEndings = this.getLineEndings(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.POLYLINE,
      rect,
      strokeColor: strokeColor ?? "#FF0000",
      color: interiorColor ?? "transparent",
      opacity,
      strokeWidth: strokeWidth === 0 ? 1 : strokeWidth,
      strokeStyle,
      strokeDashArray,
      lineEndings,
      vertices,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf line annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf line annotation
   *
   * @private
   */
  readPdfLineAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const linePoints = this.getLinePoints(doc, page, annotationPtr);
    const lineEndings = this.getLineEndings(annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr);
    const interiorColor = this.getAnnotationColor(
      annotationPtr,
      PdfAnnotationColorType.InteriorColor
    );
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const { style: strokeStyle, width: strokeWidth } = this.getBorderStyle(annotationPtr);
    let strokeDashArray;
    if (strokeStyle === PdfAnnotationBorderStyle.DASHED) {
      const { ok, pattern } = this.getBorderDashPattern(annotationPtr);
      if (ok) {
        strokeDashArray = pattern;
      }
    }
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.LINE,
      rect,
      strokeWidth: strokeWidth === 0 ? 1 : strokeWidth,
      strokeStyle,
      strokeDashArray,
      strokeColor: strokeColor ?? "#FF0000",
      color: interiorColor ?? "transparent",
      opacity,
      linePoints: linePoints || { start: { x: 0, y: 0 }, end: { x: 0, y: 0 } },
      lineEndings: lineEndings || {
        start: PdfAnnotationLineEnding.None,
        end: PdfAnnotationLineEnding.None
      },
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf highlight annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf highlight annotation
   *
   * @private
   */
  readPdfHighlightAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const segmentRects = this.getQuadPointsAnno(doc, page, annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr) ?? "#FFFF00";
    const opacity = this.getAnnotationOpacity(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.HIGHLIGHT,
      rect,
      segmentRects,
      strokeColor,
      color: strokeColor,
      // deprecated alias
      opacity,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf underline annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf underline annotation
   *
   * @private
   */
  readPdfUnderlineAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const segmentRects = this.getQuadPointsAnno(doc, page, annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr) ?? "#FF0000";
    const opacity = this.getAnnotationOpacity(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.UNDERLINE,
      rect,
      segmentRects,
      strokeColor,
      color: strokeColor,
      // deprecated alias
      opacity,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read strikeout annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf strikeout annotation
   *
   * @private
   */
  readPdfStrikeOutAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const segmentRects = this.getQuadPointsAnno(doc, page, annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr) ?? "#FF0000";
    const opacity = this.getAnnotationOpacity(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.STRIKEOUT,
      rect,
      segmentRects,
      strokeColor,
      color: strokeColor,
      // deprecated alias
      opacity,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf squiggly annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf squiggly annotation
   *
   * @private
   */
  readPdfSquigglyAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const segmentRects = this.getQuadPointsAnno(doc, page, annotationPtr);
    const strokeColor = this.getAnnotationColor(annotationPtr) ?? "#FF0000";
    const opacity = this.getAnnotationOpacity(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.SQUIGGLY,
      rect,
      segmentRects,
      strokeColor,
      color: strokeColor,
      // deprecated alias
      opacity,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf caret annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf caret annotation
   *
   * @private
   */
  readPdfCaretAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const strokeColor = this.getAnnotationColor(annotationPtr);
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const intent = this.getAnnotIntent(annotationPtr);
    const rd = this.getRectangleDifferences(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.CARET,
      rect,
      strokeColor,
      opacity,
      intent,
      ...rd.ok && {
        rectangleDifferences: {
          left: rd.left,
          top: rd.top,
          right: rd.right,
          bottom: rd.bottom
        }
      },
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf redact annotation
   * @param page  - pdf page info
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf redact annotation
   *
   * @private
   */
  readPdfRedactAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const segmentRects = this.getQuadPointsAnno(doc, page, annotationPtr);
    const color = this.getAnnotationColor(annotationPtr, PdfAnnotationColorType.InteriorColor);
    const overlayColor = this.getAnnotationColor(
      annotationPtr,
      PdfAnnotationColorType.OverlayColor
    );
    const strokeColor = this.getAnnotationColor(annotationPtr, PdfAnnotationColorType.Color);
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const overlayText = this.getOverlayText(annotationPtr);
    const overlayTextRepeat = this.getOverlayTextRepeat(annotationPtr);
    const da = this.getAnnotationDefaultAppearance(annotationPtr);
    const textAlign = this.getAnnotationTextAlignment(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.REDACT,
      rect,
      segmentRects,
      color,
      overlayColor,
      strokeColor,
      opacity,
      overlayText,
      overlayTextRepeat,
      fontFamily: da == null ? void 0 : da.fontFamily,
      fontSize: da == null ? void 0 : da.fontSize,
      fontColor: da == null ? void 0 : da.fontColor,
      textAlign,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf stamp annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf stamp annotation
   *
   * @private
   */
  readPdfStampAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.STAMP,
      rect,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read pdf object in pdf page
   * @param pageObjectPtr  - pointer to pdf object in page
   * @returns pdf object in page
   *
   * @private
   */
  readPdfPageObject(pageObjectPtr) {
    const type = this.pdfiumModule.FPDFPageObj_GetType(pageObjectPtr);
    switch (type) {
      case PdfPageObjectType.PATH:
        return this.readPathObject(pageObjectPtr);
      case PdfPageObjectType.IMAGE:
        return this.readImageObject(pageObjectPtr);
      case PdfPageObjectType.FORM:
        return this.readFormObject(pageObjectPtr);
    }
  }
  /**
   * Read pdf path object
   * @param pathObjectPtr  - pointer to pdf path object in page
   * @returns pdf path object
   *
   * @private
   */
  readPathObject(pathObjectPtr) {
    const segmentCount = this.pdfiumModule.FPDFPath_CountSegments(pathObjectPtr);
    const leftPtr = this.memoryManager.malloc(4);
    const bottomPtr = this.memoryManager.malloc(4);
    const rightPtr = this.memoryManager.malloc(4);
    const topPtr = this.memoryManager.malloc(4);
    this.pdfiumModule.FPDFPageObj_GetBounds(pathObjectPtr, leftPtr, bottomPtr, rightPtr, topPtr);
    const left = this.pdfiumModule.pdfium.getValue(leftPtr, "float");
    const bottom = this.pdfiumModule.pdfium.getValue(bottomPtr, "float");
    const right = this.pdfiumModule.pdfium.getValue(rightPtr, "float");
    const top = this.pdfiumModule.pdfium.getValue(topPtr, "float");
    const bounds = { left, bottom, right, top };
    this.memoryManager.free(leftPtr);
    this.memoryManager.free(bottomPtr);
    this.memoryManager.free(rightPtr);
    this.memoryManager.free(topPtr);
    const segments = [];
    for (let i = 0; i < segmentCount; i++) {
      const segment = this.readPdfSegment(pathObjectPtr, i);
      segments.push(segment);
    }
    const matrix = this.readPdfPageObjectTransformMatrix(pathObjectPtr);
    return {
      type: PdfPageObjectType.PATH,
      bounds,
      segments,
      matrix
    };
  }
  /**
   * Read segment of pdf path object
   * @param annotationObjectPtr - pointer to pdf path object
   * @param segmentIndex - index of segment
   * @returns pdf segment in pdf path
   *
   * @private
   */
  readPdfSegment(annotationObjectPtr, segmentIndex) {
    const segmentPtr = this.pdfiumModule.FPDFPath_GetPathSegment(annotationObjectPtr, segmentIndex);
    const segmentType = this.pdfiumModule.FPDFPathSegment_GetType(segmentPtr);
    const isClosed = this.pdfiumModule.FPDFPathSegment_GetClose(segmentPtr);
    const pointXPtr = this.memoryManager.malloc(4);
    const pointYPtr = this.memoryManager.malloc(4);
    this.pdfiumModule.FPDFPathSegment_GetPoint(segmentPtr, pointXPtr, pointYPtr);
    const pointX = this.pdfiumModule.pdfium.getValue(pointXPtr, "float");
    const pointY = this.pdfiumModule.pdfium.getValue(pointYPtr, "float");
    this.memoryManager.free(pointXPtr);
    this.memoryManager.free(pointYPtr);
    return {
      type: segmentType,
      point: { x: pointX, y: pointY },
      isClosed
    };
  }
  /**
   * Read pdf image object from pdf document
   * @param pageObjectPtr  - pointer to pdf image object in page
   * @returns pdf image object
   *
   * @private
   */
  readImageObject(imageObjectPtr) {
    const bitmapPtr = this.pdfiumModule.FPDFImageObj_GetBitmap(imageObjectPtr);
    const bitmapBufferPtr = this.pdfiumModule.FPDFBitmap_GetBuffer(bitmapPtr);
    const bitmapWidth = this.pdfiumModule.FPDFBitmap_GetWidth(bitmapPtr);
    const bitmapHeight = this.pdfiumModule.FPDFBitmap_GetHeight(bitmapPtr);
    const format = this.pdfiumModule.FPDFBitmap_GetFormat(bitmapPtr);
    const pixelCount = bitmapWidth * bitmapHeight;
    const bytesPerPixel = 4;
    const array = new Uint8ClampedArray(pixelCount * bytesPerPixel);
    for (let i = 0; i < pixelCount; i++) {
      switch (format) {
        case 2:
          {
            const blue = this.pdfiumModule.pdfium.getValue(bitmapBufferPtr + i * 3, "i8");
            const green = this.pdfiumModule.pdfium.getValue(bitmapBufferPtr + i * 3 + 1, "i8");
            const red = this.pdfiumModule.pdfium.getValue(bitmapBufferPtr + i * 3 + 2, "i8");
            array[i * bytesPerPixel] = red;
            array[i * bytesPerPixel + 1] = green;
            array[i * bytesPerPixel + 2] = blue;
            array[i * bytesPerPixel + 3] = 100;
          }
          break;
      }
    }
    const imageDataLike = {
      data: array,
      width: bitmapWidth,
      height: bitmapHeight
    };
    const matrix = this.readPdfPageObjectTransformMatrix(imageObjectPtr);
    return {
      type: PdfPageObjectType.IMAGE,
      imageData: imageDataLike,
      matrix
    };
  }
  /**
   * Read form object from pdf document
   * @param formObjectPtr  - pointer to pdf form object in page
   * @returns pdf form object
   *
   * @private
   */
  readFormObject(formObjectPtr) {
    const objectCount = this.pdfiumModule.FPDFFormObj_CountObjects(formObjectPtr);
    const objects = [];
    for (let i = 0; i < objectCount; i++) {
      const pageObjectPtr = this.pdfiumModule.FPDFFormObj_GetObject(formObjectPtr, i);
      const pageObj = this.readPdfPageObject(pageObjectPtr);
      if (pageObj) {
        objects.push(pageObj);
      }
    }
    const matrix = this.readPdfPageObjectTransformMatrix(formObjectPtr);
    return {
      type: PdfPageObjectType.FORM,
      objects,
      matrix
    };
  }
  /**
   * Read pdf object in pdf page
   * @param pageObjectPtr  - pointer to pdf object in page
   * @returns pdf object in page
   *
   * @private
   */
  readPdfPageObjectTransformMatrix(pageObjectPtr) {
    const matrixPtr = this.memoryManager.malloc(4 * 6);
    if (this.pdfiumModule.FPDFPageObj_GetMatrix(pageObjectPtr, matrixPtr)) {
      const a = this.pdfiumModule.pdfium.getValue(matrixPtr, "float");
      const b = this.pdfiumModule.pdfium.getValue(matrixPtr + 4, "float");
      const c = this.pdfiumModule.pdfium.getValue(matrixPtr + 8, "float");
      const d = this.pdfiumModule.pdfium.getValue(matrixPtr + 12, "float");
      const e = this.pdfiumModule.pdfium.getValue(matrixPtr + 16, "float");
      const f = this.pdfiumModule.pdfium.getValue(matrixPtr + 20, "float");
      this.memoryManager.free(matrixPtr);
      return { a, b, c, d, e, f };
    }
    this.memoryManager.free(matrixPtr);
    return { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
  }
  /**
   * Read contents of a stamp annotation
   * @param annotationPtr - pointer to pdf annotation
   * @returns contents of the stamp annotation
   *
   * @private
   */
  readStampAnnotationContents(annotationPtr) {
    const contents = [];
    const objectCount = this.pdfiumModule.FPDFAnnot_GetObjectCount(annotationPtr);
    for (let i = 0; i < objectCount; i++) {
      const annotationObjectPtr = this.pdfiumModule.FPDFAnnot_GetObject(annotationPtr, i);
      const pageObj = this.readPdfPageObject(annotationObjectPtr);
      if (pageObj) {
        contents.push(pageObj);
      }
    }
    return contents;
  }
  /**
   * Return the stroke-width declared in the annotation’s /Border or /BS entry.
   * Falls back to 1 pt when nothing is defined.
   *
   * @param annotationPtr - pointer to pdf annotation
   * @returns stroke-width
   *
   * @private
   */
  getStrokeWidth(annotationPtr) {
    const hPtr = this.memoryManager.malloc(4);
    const vPtr = this.memoryManager.malloc(4);
    const wPtr = this.memoryManager.malloc(4);
    const ok = this.pdfiumModule.FPDFAnnot_GetBorder(annotationPtr, hPtr, vPtr, wPtr);
    const width = ok ? this.pdfiumModule.pdfium.getValue(wPtr, "float") : 1;
    this.memoryManager.free(hPtr);
    this.memoryManager.free(vPtr);
    this.memoryManager.free(wPtr);
    return width;
  }
  /**
   * Fetches the `/F` flag bit-field from an annotation.
   *
   * @param annotationPtr pointer to an `FPDF_ANNOTATION`
   * @returns `{ raw, flags }`
   *          • `raw`   – the 32-bit integer returned by PDFium
   *          • `flags` – object with individual booleans
   */
  getAnnotationFlags(annotationPtr) {
    const rawFlags = this.pdfiumModule.FPDFAnnot_GetFlags(annotationPtr);
    return flagsToNames(rawFlags);
  }
  setAnnotationFlags(annotationPtr, flags) {
    const rawFlags = namesToFlags(flags);
    return this.pdfiumModule.FPDFAnnot_SetFlags(annotationPtr, rawFlags);
  }
  /**
   * Read circle annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf circle annotation
   *
   * @private
   */
  readPdfCircleAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const interiorColor = this.getAnnotationColor(
      annotationPtr,
      PdfAnnotationColorType.InteriorColor
    );
    const strokeColor = this.getAnnotationColor(annotationPtr);
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const { style: strokeStyle, width: strokeWidth } = this.getBorderStyle(annotationPtr);
    let strokeDashArray;
    if (strokeStyle === PdfAnnotationBorderStyle.DASHED) {
      const { ok, pattern } = this.getBorderDashPattern(annotationPtr);
      if (ok) {
        strokeDashArray = pattern;
      }
    }
    const rd = this.getRectangleDifferences(annotationPtr);
    const be = this.getBorderEffect(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.CIRCLE,
      rect,
      color: interiorColor ?? "transparent",
      opacity,
      strokeWidth,
      strokeColor: strokeColor ?? "#FF0000",
      strokeStyle,
      ...strokeDashArray !== void 0 && { strokeDashArray },
      ...be.ok && { cloudyBorderIntensity: be.intensity },
      ...rd.ok && {
        rectangleDifferences: {
          left: rd.left,
          top: rd.top,
          right: rd.right,
          bottom: rd.bottom
        }
      },
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Read square annotation
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @param index  - index of annotation in the pdf page
   * @returns pdf square annotation
   *
   * @private
   */
  readPdfSquareAnno(doc, page, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const interiorColor = this.getAnnotationColor(
      annotationPtr,
      PdfAnnotationColorType.InteriorColor
    );
    const strokeColor = this.getAnnotationColor(annotationPtr);
    const opacity = this.getAnnotationOpacity(annotationPtr);
    const { style: strokeStyle, width: strokeWidth } = this.getBorderStyle(annotationPtr);
    let strokeDashArray;
    if (strokeStyle === PdfAnnotationBorderStyle.DASHED) {
      const { ok, pattern } = this.getBorderDashPattern(annotationPtr);
      if (ok) {
        strokeDashArray = pattern;
      }
    }
    const rd = this.getRectangleDifferences(annotationPtr);
    const be = this.getBorderEffect(annotationPtr);
    return {
      pageIndex: page.index,
      id: index,
      type: PdfAnnotationSubtype.SQUARE,
      rect,
      color: interiorColor ?? "transparent",
      opacity,
      strokeColor: strokeColor ?? "#FF0000",
      strokeWidth,
      strokeStyle,
      ...strokeDashArray !== void 0 && { strokeDashArray },
      ...be.ok && { cloudyBorderIntensity: be.intensity },
      ...rd.ok && {
        rectangleDifferences: {
          left: rd.left,
          top: rd.top,
          right: rd.right,
          bottom: rd.bottom
        }
      },
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
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
  readPdfAnno(doc, page, type, annotationPtr, index) {
    const pageRect = this.readPageAnnoRect(annotationPtr);
    const rect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    return {
      pageIndex: page.index,
      id: index,
      type,
      rect,
      ...this.readBaseAnnotationProperties(doc, page, annotationPtr)
    };
  }
  /**
   * Resolve `/IRT` → parent-annotation index on the same page.
   *
   * @param pagePtr        - pointer to FPDF_PAGE
   * @param annotationPtr  - pointer to FPDF_ANNOTATION
   * @returns index (`0…count-1`) or `undefined` when the annotation is *not* a reply
   *
   * @private
   */
  getInReplyToId(annotationPtr) {
    const parentPtr = this.pdfiumModule.FPDFAnnot_GetLinkedAnnot(annotationPtr, "IRT");
    if (!parentPtr) return;
    let nm = this.getAnnotString(parentPtr, "NM");
    if (!nm || !isUuidV4(nm)) {
      nm = uuidV4();
      this.setAnnotString(parentPtr, "NM", nm);
    }
    this.pdfiumModule.FPDFPage_CloseAnnot(parentPtr);
    return nm;
  }
  /**
   * Set the in reply to id of the annotation
   *
   * @param annotationPtr - pointer to an `FPDF_ANNOTATION`
   * @param id - the id of the parent annotation
   * @returns `true` on success
   */
  setInReplyToId(pagePtr, annotationPtr, id) {
    if (!id) {
      return this.pdfiumModule.EPDFAnnot_SetLinkedAnnot(annotationPtr, "IRT", 0);
    }
    const parentPtr = this.getAnnotationByName(pagePtr, id);
    if (!parentPtr) return false;
    return this.pdfiumModule.EPDFAnnot_SetLinkedAnnot(annotationPtr, "IRT", parentPtr);
  }
  /**
   * Rotate a point around a center by the given angle in degrees.
   * Used to rotate vertices for PDF storage.
   */
  rotatePointForSave(point, center, angleDegrees) {
    const rad = angleDegrees * Math.PI / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    const dx = point.x - center.x;
    const dy = point.y - center.y;
    return {
      x: center.x + dx * cos - dy * sin,
      y: center.y + dx * sin + dy * cos
    };
  }
  /**
   * Prepare an annotation for saving to PDF.
   * For vertex types (ink, line, polygon, polyline) with rotation,
   * physically rotates the vertices by +rotation so that other PDF viewers
   * see the correct visual result. Our viewer reverse-rotates on load.
   */
  prepareAnnotationForSave(annotation) {
    const rotation = annotation.rotation;
    const unrotatedRect = annotation.unrotatedRect;
    if (!rotation || rotation === 0 || !unrotatedRect) {
      return annotation;
    }
    const center = {
      x: unrotatedRect.origin.x + unrotatedRect.size.width / 2,
      y: unrotatedRect.origin.y + unrotatedRect.size.height / 2
    };
    switch (annotation.type) {
      case PdfAnnotationSubtype.INK: {
        const ink = annotation;
        const rotatedInkList = ink.inkList.map((stroke) => ({
          points: stroke.points.map((p) => this.rotatePointForSave(p, center, rotation))
        }));
        return { ...ink, inkList: rotatedInkList };
      }
      case PdfAnnotationSubtype.LINE: {
        const line = annotation;
        return {
          ...line,
          linePoints: {
            start: this.rotatePointForSave(line.linePoints.start, center, rotation),
            end: this.rotatePointForSave(line.linePoints.end, center, rotation)
          }
        };
      }
      case PdfAnnotationSubtype.POLYGON: {
        const poly = annotation;
        return {
          ...poly,
          vertices: poly.vertices.map((v) => this.rotatePointForSave(v, center, rotation))
        };
      }
      case PdfAnnotationSubtype.POLYLINE: {
        const polyline = annotation;
        return {
          ...polyline,
          vertices: polyline.vertices.map((v) => this.rotatePointForSave(v, center, rotation))
        };
      }
      default:
        return annotation;
    }
  }
  /**
   * Apply all base annotation properties from PdfAnnotationObjectBase.
   * The setInReplyToId and setReplyType functions handle clearing when undefined.
   *
   * @param pagePtr - pointer to page object
   * @param annotationPtr - pointer to annotation object
   * @param annotation - the annotation object containing properties to apply
   * @returns `true` on success
   */
  applyBaseAnnotationProperties(doc, page, pagePtr, annotationPtr, annotation) {
    if (!this.setAnnotString(annotationPtr, "T", annotation.author || "")) {
      return false;
    }
    if (!this.setAnnotString(annotationPtr, "Contents", annotation.contents ?? "")) {
      return false;
    }
    if (annotation.modified) {
      if (!this.setAnnotationDate(annotationPtr, "M", annotation.modified)) {
        return false;
      }
    }
    if (annotation.created) {
      if (!this.setAnnotationDate(annotationPtr, "CreationDate", annotation.created)) {
        return false;
      }
    }
    if (annotation.flags) {
      if (!this.setAnnotationFlags(annotationPtr, annotation.flags)) {
        return false;
      }
    }
    const existingCustom = this.getAnnotCustom(annotationPtr) ?? {};
    const customData = {
      ...existingCustom,
      ...annotation.custom ?? {}
    };
    delete customData.unrotatedRect;
    delete customData.rotation;
    const hasCustomData = Object.keys(customData).length > 0;
    if (hasCustomData) {
      if (!this.setAnnotCustom(annotationPtr, customData)) {
        return false;
      }
    } else if (Object.keys(existingCustom).length > 0) {
      if (!this.setAnnotCustom(annotationPtr, null)) {
        return false;
      }
    }
    if (annotation.rotation !== void 0) {
      const pdfRotation = annotation.rotation ? (360 - annotation.rotation) % 360 : 0;
      this.setAnnotExtendedRotation(annotationPtr, pdfRotation);
    }
    if (annotation.unrotatedRect) {
      this.setAnnotUnrotatedRect(doc, page, annotationPtr, annotation.unrotatedRect);
    } else if (annotation.rotation && annotation.rotation !== 0) {
      this.setAnnotUnrotatedRect(doc, page, annotationPtr, annotation.rect);
    }
    if (!this.setInReplyToId(pagePtr, annotationPtr, annotation.inReplyToId)) {
      return false;
    }
    if (!this.setReplyType(annotationPtr, annotation.replyType)) {
      return false;
    }
    return true;
  }
  /**
   * Read all base annotation properties from PdfAnnotationObjectBase.
   * Returns an object that can be spread into the annotation return value.
   *
   * @param doc - pdf document object
   * @param page - pdf page object
   * @param annotationPtr - pointer to annotation object
   * @returns object with base annotation properties
   */
  readBaseAnnotationProperties(doc, page, annotationPtr) {
    const author = this.getAnnotString(annotationPtr, "T");
    const contents = this.getAnnotString(annotationPtr, "Contents") || "";
    const modified = this.getAnnotationDate(annotationPtr, "M");
    const created = this.getAnnotationDate(annotationPtr, "CreationDate");
    const flags = this.getAnnotationFlags(annotationPtr);
    const custom = this.getAnnotCustom(annotationPtr);
    const inReplyToId = this.getInReplyToId(annotationPtr);
    const replyType = this.getReplyType(annotationPtr);
    const blendMode = this.pdfiumModule.EPDFAnnot_GetBlendMode(annotationPtr);
    const pdfRotation = this.getAnnotExtendedRotation(annotationPtr);
    const rotation = pdfRotation !== 0 ? (360 - pdfRotation) % 360 : 0;
    const rawUnrotatedRect = this.readAnnotUnrotatedRect(annotationPtr);
    const unrotatedRect = rawUnrotatedRect ? this.convertPageRectToDeviceRect(doc, page, rawUnrotatedRect) : void 0;
    return {
      author,
      contents,
      modified,
      created,
      flags,
      custom,
      blendMode,
      // Only include IRT if present
      ...inReplyToId && { inReplyToId },
      // Only include RT if present and not the default (Reply)
      ...replyType && replyType !== PdfAnnotationReplyType.Reply && { replyType },
      ...rotation !== 0 && { rotation },
      ...unrotatedRect !== void 0 && { unrotatedRect }
    };
  }
  /**
   * Fetch a string value (`/T`, `/M`, `/State`, …) from an annotation.
   *
   * @returns decoded UTF-8 string or `undefined` when the key is absent
   *
   * @private
   */
  getAnnotString(annotationPtr, key) {
    const len = this.pdfiumModule.FPDFAnnot_GetStringValue(annotationPtr, key, 0, 0);
    if (len === 0) return;
    const bytes = (len + 1) * 2;
    const ptr = this.memoryManager.malloc(bytes);
    this.pdfiumModule.FPDFAnnot_GetStringValue(annotationPtr, key, ptr, bytes);
    const value = this.pdfiumModule.pdfium.UTF16ToString(ptr);
    this.memoryManager.free(ptr);
    return value || void 0;
  }
  /**
   * Get a string value (`/T`, `/M`, `/State`, …) from an attachment.
   *
   * @returns decoded UTF-8 string or `undefined` when the key is absent
   *
   * @private
   */
  getAttachmentString(attachmentPtr, key) {
    const len = this.pdfiumModule.FPDFAttachment_GetStringValue(attachmentPtr, key, 0, 0);
    if (len === 0) return;
    const bytes = (len + 1) * 2;
    const ptr = this.memoryManager.malloc(bytes);
    this.pdfiumModule.FPDFAttachment_GetStringValue(attachmentPtr, key, ptr, bytes);
    const value = this.pdfiumModule.pdfium.UTF16ToString(ptr);
    this.memoryManager.free(ptr);
    return value || void 0;
  }
  /**
   * Get a number value (`/Size`) from an attachment.
   *
   * @returns number or `null` when the key is absent
   *
   * @private
   */
  getAttachmentNumber(attachmentPtr, key) {
    const outPtr = this.memoryManager.malloc(4);
    try {
      const ok = this.pdfiumModule.EPDFAttachment_GetIntegerValue(
        attachmentPtr,
        key,
        // FPDF_BYTESTRING → ASCII JS string is fine in your glue
        outPtr
      );
      if (!ok) return void 0;
      return this.pdfiumModule.pdfium.getValue(outPtr, "i32") >>> 0;
    } finally {
      this.memoryManager.free(outPtr);
    }
  }
  /**
   * Get custom data of the annotation
   * @param annotationPtr - pointer to pdf annotation
   * @returns custom data of the annotation
   *
   * @private
   */
  getAnnotCustom(annotationPtr) {
    const custom = this.getAnnotString(annotationPtr, "EPDFCustom");
    if (!custom) return;
    try {
      return JSON.parse(custom);
    } catch (error) {
      console.warn("Failed to parse annotation custom data as JSON:", error);
      console.warn("Invalid JSON string:", custom);
      return void 0;
    }
  }
  /**
   * Sets custom data for an annotation by safely stringifying and storing JSON
   * @private
   */
  setAnnotCustom(annotationPtr, data) {
    if (data === void 0 || data === null) {
      return this.setAnnotString(annotationPtr, "EPDFCustom", "");
    }
    try {
      const jsonString = JSON.stringify(data);
      return this.setAnnotString(annotationPtr, "EPDFCustom", jsonString);
    } catch (error) {
      console.warn("Failed to stringify annotation custom data as JSON:", error);
      console.warn("Invalid data object:", data);
      return false;
    }
  }
  /**
   * Fetches the /IT (Intent) name from an annotation as a UTF-8 JS string.
   *
   * Mirrors getAnnotString(): calls EPDFAnnot_GetIntent twice (length probe + copy).
   * Returns `undefined` if no intent present.
   */
  getAnnotIntent(annotationPtr) {
    const len = this.pdfiumModule.EPDFAnnot_GetIntent(annotationPtr, 0, 0);
    if (len === 0) return;
    const codeUnits = len + 1;
    const bytes = codeUnits * 2;
    const ptr = this.memoryManager.malloc(bytes);
    this.pdfiumModule.EPDFAnnot_GetIntent(annotationPtr, ptr, bytes);
    const value = this.pdfiumModule.pdfium.UTF16ToString(ptr);
    this.memoryManager.free(ptr);
    return value && value !== "undefined" ? value : void 0;
  }
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
  setAnnotIntent(annotationPtr, intent) {
    return this.pdfiumModule.EPDFAnnot_SetIntent(annotationPtr, intent);
  }
  /**
   * Returns the rich‑content string stored in the annotation’s `/RC` entry.
   *
   * Works like `getAnnotIntent()`: first probe for length, then copy.
   * `undefined` when the annotation has no rich content.
   */
  getAnnotRichContent(annotationPtr) {
    const len = this.pdfiumModule.EPDFAnnot_GetRichContent(annotationPtr, 0, 0);
    if (len === 0) return;
    const codeUnits = len + 1;
    const bytes = codeUnits * 2;
    const ptr = this.memoryManager.malloc(bytes);
    this.pdfiumModule.EPDFAnnot_GetRichContent(annotationPtr, ptr, bytes);
    const value = this.pdfiumModule.pdfium.UTF16ToString(ptr);
    this.memoryManager.free(ptr);
    return value || void 0;
  }
  /**
   * Get annotation by name
   * @param pagePtr - pointer to pdf page object
   * @param name - name of annotation
   * @returns pointer to pdf annotation
   *
   * @private
   */
  getAnnotationByName(pagePtr, name) {
    return this.withWString(name, (wNamePtr) => {
      return this.pdfiumModule.EPDFPage_GetAnnotByName(pagePtr, wNamePtr);
    });
  }
  /**
   * Remove annotation by name
   * @param pagePtr - pointer to pdf page object
   * @param name - name of annotation
   * @returns true on success
   *
   * @private
   */
  removeAnnotationByName(pagePtr, name) {
    return this.withWString(name, (wNamePtr) => {
      return this.pdfiumModule.EPDFPage_RemoveAnnotByName(pagePtr, wNamePtr);
    });
  }
  /**
   * Set a string value (`/T`, `/M`, `/State`, …) to an annotation.
   *
   * @returns `true` if the operation was successful
   *
   * @private
   */
  setAnnotString(annotationPtr, key, value) {
    return this.withWString(value, (wValPtr) => {
      return this.pdfiumModule.FPDFAnnot_SetStringValue(annotationPtr, key, wValPtr);
    });
  }
  /**
   * Set a string value (`/T`, `/M`, `/State`, …) to an attachment.
   *
   * @returns `true` if the operation was successful
   *
   * @private
   */
  setAttachmentString(attachmentPtr, key, value) {
    return this.withWString(value, (wValPtr) => {
      return this.pdfiumModule.FPDFAttachment_SetStringValue(attachmentPtr, key, wValPtr);
    });
  }
  /**
   * Read vertices of pdf annotation
   * @param doc - pdf document object
   * @param page  - pdf page infor
   * @param annotationPtr - pointer to pdf annotation
   * @returns vertices of pdf annotation
   *
   * @private
   */
  readPdfAnnoVertices(doc, page, annotationPtr) {
    const vertices = [];
    const count = this.pdfiumModule.FPDFAnnot_GetVertices(annotationPtr, 0, 0);
    const pointMemorySize = 8;
    const pointsPtr = this.memoryManager.malloc(count * pointMemorySize);
    this.pdfiumModule.FPDFAnnot_GetVertices(annotationPtr, pointsPtr, count);
    for (let i = 0; i < count; i++) {
      const pointX = this.pdfiumModule.pdfium.getValue(pointsPtr + i * pointMemorySize, "float");
      const pointY = this.pdfiumModule.pdfium.getValue(
        pointsPtr + i * pointMemorySize + 4,
        "float"
      );
      const { x, y } = this.convertPagePointToDevicePoint(doc, page, {
        x: pointX,
        y: pointY
      });
      const last = vertices[vertices.length - 1];
      if (!last || last.x !== x || last.y !== y) {
        vertices.push({ x, y });
      }
    }
    this.memoryManager.free(pointsPtr);
    return vertices;
  }
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
  setPdfAnnoVertices(doc, page, annotPtr, vertices) {
    const pdf = this.pdfiumModule.pdfium;
    const FS_POINTF_SIZE = 8;
    const buf = this.memoryManager.malloc(FS_POINTF_SIZE * vertices.length);
    vertices.forEach((v, i) => {
      const pagePt = this.convertDevicePointToPagePoint(doc, page, v);
      pdf.setValue(buf + i * FS_POINTF_SIZE + 0, pagePt.x, "float");
      pdf.setValue(buf + i * FS_POINTF_SIZE + 4, pagePt.y, "float");
    });
    const ok = this.pdfiumModule.EPDFAnnot_SetVertices(annotPtr, buf, vertices.length);
    this.memoryManager.free(buf);
    return ok;
  }
  /**
   * Read the target of pdf bookmark
   * @param docPtr - pointer to pdf document object
   * @param getActionPtr - callback function to retrive the pointer of action
   * @param getDestinationPtr - callback function to retrive the pointer of destination
   * @returns target of pdf bookmark
   *
   * @private
   */
  readPdfBookmarkTarget(docPtr, getActionPtr, getDestinationPtr) {
    const actionPtr = getActionPtr();
    if (actionPtr) {
      const action = this.readPdfAction(docPtr, actionPtr);
      return {
        type: "action",
        action
      };
    } else {
      const destinationPtr = getDestinationPtr();
      if (destinationPtr) {
        const destination = this.readPdfDestination(docPtr, destinationPtr);
        return {
          type: "destination",
          destination
        };
      }
    }
  }
  /**
   * Read field of pdf widget annotation
   * @param formHandle - form handle
   * @param annotationPtr - pointer to pdf annotation
   * @returns field of pdf widget annotation
   *
   * @private
   */
  readPdfWidgetAnnoField(formHandle, annotationPtr) {
    const flag = this.pdfiumModule.FPDFAnnot_GetFormFieldFlags(
      formHandle,
      annotationPtr
    );
    const type = this.pdfiumModule.FPDFAnnot_GetFormFieldType(
      formHandle,
      annotationPtr
    );
    const name = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.FPDFAnnot_GetFormFieldName(
          formHandle,
          annotationPtr,
          buffer,
          bufferLength
        );
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const alternateName = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.FPDFAnnot_GetFormFieldAlternateName(
          formHandle,
          annotationPtr,
          buffer,
          bufferLength
        );
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const value = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.FPDFAnnot_GetFormFieldValue(
          formHandle,
          annotationPtr,
          buffer,
          bufferLength
        );
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const options = [];
    if (type === PDF_FORM_FIELD_TYPE.COMBOBOX || type === PDF_FORM_FIELD_TYPE.LISTBOX) {
      const count = this.pdfiumModule.FPDFAnnot_GetOptionCount(formHandle, annotationPtr);
      for (let i = 0; i < count; i++) {
        const label = readString(
          this.pdfiumModule.pdfium,
          (buffer, bufferLength) => {
            return this.pdfiumModule.FPDFAnnot_GetOptionLabel(
              formHandle,
              annotationPtr,
              i,
              buffer,
              bufferLength
            );
          },
          this.pdfiumModule.pdfium.UTF16ToString
        );
        const isSelected = this.pdfiumModule.FPDFAnnot_IsOptionSelected(
          formHandle,
          annotationPtr,
          i
        );
        options.push({
          label,
          isSelected
        });
      }
    }
    let isChecked = false;
    if (type === PDF_FORM_FIELD_TYPE.CHECKBOX || type === PDF_FORM_FIELD_TYPE.RADIOBUTTON) {
      isChecked = this.pdfiumModule.FPDFAnnot_IsChecked(formHandle, annotationPtr);
    }
    return {
      flag,
      type,
      name,
      alternateName,
      value,
      isChecked,
      options
    };
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderAnnotation}
   *
   * @public
   */
  renderPageAnnotationRaw(doc, page, annotation, options) {
    const {
      scaleFactor = 1,
      rotation = Rotation.Degree0,
      dpr = 1,
      mode = AppearanceMode.Normal
    } = options ?? {};
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      "renderPageAnnotation",
      doc,
      page,
      annotation,
      options
    );
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RenderPageAnnotation`,
      "Begin",
      `${doc.id}-${page.index}-${annotation.id}`
    );
    const task = new Task();
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `RenderPageAnnotation`,
        "End",
        `${doc.id}-${page.index}-${annotation.id}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const annotPtr = this.getAnnotationByName(pageCtx.pagePtr, annotation.id);
    if (!annotPtr) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `RenderPageAnnotation`,
        "End",
        `${doc.id}-${page.index}-${annotation.id}`
      );
      pageCtx.release();
      return PdfTaskHelper.reject({ code: PdfErrorCode.NotFound, message: "annotation not found" });
    }
    const finalScale = Math.max(0.01, scaleFactor * dpr);
    const unrotated = !!(options == null ? void 0 : options.unrotated) && !!annotation.unrotatedRect;
    const renderRect = unrotated ? annotation.unrotatedRect : annotation.rect;
    const rect = toIntRect(renderRect);
    const devRect = toIntRect(transformRect(page.size, rect, rotation, finalScale));
    const wDev = Math.max(1, devRect.size.width);
    const hDev = Math.max(1, devRect.size.height);
    const stride = wDev * 4;
    const bytes = stride * hDev;
    const heapPtr = this.memoryManager.malloc(bytes);
    const bitmapPtr = this.pdfiumModule.FPDFBitmap_CreateEx(
      wDev,
      hDev,
      4,
      heapPtr,
      stride
    );
    this.pdfiumModule.FPDFBitmap_FillRect(bitmapPtr, 0, 0, wDev, hDev, 0);
    const M = buildUserToDeviceMatrix(
      rect,
      // {origin:{L,B}, size:{W,H}}
      rotation,
      wDev,
      hDev
    );
    const mPtr = this.memoryManager.malloc(6 * 4);
    const mView = new Float32Array(this.pdfiumModule.pdfium.HEAPF32.buffer, mPtr, 6);
    mView.set([M.a, M.b, M.c, M.d, M.e, M.f]);
    const FLAGS = 16;
    let ok = false;
    try {
      if (unrotated) {
        ok = !!this.pdfiumModule.EPDF_RenderAnnotBitmapUnrotated(
          bitmapPtr,
          pageCtx.pagePtr,
          annotPtr,
          mode,
          mPtr,
          FLAGS
        );
      } else {
        ok = !!this.pdfiumModule.EPDF_RenderAnnotBitmap(
          bitmapPtr,
          pageCtx.pagePtr,
          annotPtr,
          mode,
          mPtr,
          FLAGS
        );
      }
    } finally {
      this.memoryManager.free(mPtr);
      this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
      this.pdfiumModule.FPDFPage_CloseAnnot(annotPtr);
      pageCtx.release();
    }
    if (!ok) {
      this.memoryManager.free(heapPtr);
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        `RenderPageAnnotation`,
        "End",
        `${doc.id}-${page.index}-${annotation.id}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: "EPDF_RenderAnnotBitmap failed"
      });
    }
    const data = this.pdfiumModule.pdfium.HEAPU8.subarray(heapPtr, heapPtr + bytes);
    const imageDataLike = {
      data: new Uint8ClampedArray(data),
      width: wDev,
      height: hDev
    };
    task.resolve(imageDataLike);
    this.memoryManager.free(heapPtr);
    return task;
  }
  /**
   * Batch-render all annotation appearance streams for a page in one call.
   * Returns a map of annotation ID -> rendered appearances (Normal/Rollover/Down).
   * Skips annotations that have rotation + unrotatedRect (EmbedPDF-rotated)
   * and annotations without any appearance stream.
   *
   * @public
   */
  renderPageAnnotationsRaw(doc, page, options) {
    const { scaleFactor = 1, rotation = Rotation.Degree0, dpr = 1 } = options ?? {};
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPageAnnotationsRaw", doc, page, options);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      "RenderPageAnnotationsRaw",
      "Begin",
      `${doc.id}-${page.index}`
    );
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(
        LOG_SOURCE,
        LOG_CATEGORY,
        "RenderPageAnnotationsRaw",
        "End",
        `${doc.id}-${page.index}`
      );
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const pageCtx = ctx.acquirePage(page.index);
    const result = {};
    const finalScale = Math.max(0.01, scaleFactor * dpr);
    const annotCount = this.pdfiumModule.FPDFPage_GetAnnotCount(pageCtx.pagePtr);
    for (let i = 0; i < annotCount; i++) {
      const annotPtr = this.pdfiumModule.FPDFPage_GetAnnot(pageCtx.pagePtr, i);
      if (!annotPtr) continue;
      try {
        const nm = this.getAnnotString(annotPtr, "NM");
        if (!nm) continue;
        const extRotation = this.getAnnotExtendedRotation(annotPtr);
        if (extRotation !== 0) {
          const unrotatedRaw = this.readAnnotUnrotatedRect(annotPtr);
          if (unrotatedRaw) continue;
        }
        const apModes = this.pdfiumModule.EPDFAnnot_GetAvailableAppearanceModes(annotPtr);
        if (!apModes) continue;
        const appearances = {};
        const modesToRender = [
          { bit: AP_MODE_NORMAL, mode: AppearanceMode.Normal, key: "normal" },
          { bit: AP_MODE_ROLLOVER, mode: AppearanceMode.Rollover, key: "rollover" },
          { bit: AP_MODE_DOWN, mode: AppearanceMode.Down, key: "down" }
        ];
        for (const { bit, mode, key } of modesToRender) {
          if (!(apModes & bit)) continue;
          const rendered = this.renderSingleAnnotAppearance(
            doc,
            page,
            pageCtx,
            annotPtr,
            mode,
            rotation,
            finalScale
          );
          if (rendered) {
            appearances[key] = rendered;
          }
        }
        if (appearances.normal || appearances.rollover || appearances.down) {
          result[nm] = appearances;
        }
      } finally {
        this.pdfiumModule.FPDFPage_CloseAnnot(annotPtr);
      }
    }
    pageCtx.release();
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      "RenderPageAnnotationsRaw",
      "End",
      `${doc.id}-${page.index}`
    );
    const task = new Task();
    task.resolve(result);
    return task;
  }
  /**
   * Render a single annotation's appearance for a given mode.
   * Returns the image data and rect, or null on failure.
   * @private
   */
  renderSingleAnnotAppearance(doc, page, pageCtx, annotPtr, mode, rotation, finalScale) {
    const pageRect = this.readPageAnnoRect(annotPtr);
    const annotRect = this.convertPageRectToDeviceRect(doc, page, pageRect);
    const rect = toIntRect(annotRect);
    const devRect = toIntRect(transformRect(page.size, rect, rotation, finalScale));
    const wDev = Math.max(1, devRect.size.width);
    const hDev = Math.max(1, devRect.size.height);
    const stride = wDev * 4;
    const bytes = stride * hDev;
    const heapPtr = this.memoryManager.malloc(bytes);
    const bitmapPtr = this.pdfiumModule.FPDFBitmap_CreateEx(
      wDev,
      hDev,
      4,
      heapPtr,
      stride
    );
    this.pdfiumModule.FPDFBitmap_FillRect(bitmapPtr, 0, 0, wDev, hDev, 0);
    const M = buildUserToDeviceMatrix(rect, rotation, wDev, hDev);
    const mPtr = this.memoryManager.malloc(6 * 4);
    const mView = new Float32Array(this.pdfiumModule.pdfium.HEAPF32.buffer, mPtr, 6);
    mView.set([M.a, M.b, M.c, M.d, M.e, M.f]);
    const FLAGS = 16;
    let ok = false;
    try {
      ok = !!this.pdfiumModule.EPDF_RenderAnnotBitmap(
        bitmapPtr,
        pageCtx.pagePtr,
        annotPtr,
        mode,
        mPtr,
        FLAGS
      );
    } finally {
      this.memoryManager.free(mPtr);
      this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
    }
    if (!ok) {
      this.memoryManager.free(heapPtr);
      return null;
    }
    const data = this.pdfiumModule.pdfium.HEAPU8.subarray(heapPtr, heapPtr + bytes);
    const imageData = {
      data: new Uint8ClampedArray(data),
      width: wDev,
      height: hDev
    };
    this.memoryManager.free(heapPtr);
    return { data: imageData, rect: annotRect };
  }
  renderRectEncoded(doc, page, rect, options) {
    const task = new Task();
    const rotation = (options == null ? void 0 : options.rotation) ?? Rotation.Degree0;
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "document does not open"
      });
    }
    const scale = Math.max(0.01, (options == null ? void 0 : options.scaleFactor) ?? 1);
    const dpr = Math.max(1, (options == null ? void 0 : options.dpr) ?? 1);
    const finalScale = scale * dpr;
    const baseW = rect.size.width;
    const baseH = rect.size.height;
    const swap = (rotation & 1) === 1;
    const wDev = Math.max(1, Math.round((swap ? baseH : baseW) * finalScale));
    const hDev = Math.max(1, Math.round((swap ? baseW : baseH) * finalScale));
    const stride = wDev * 4;
    const bytes = stride * hDev;
    const pageCtx = ctx.acquirePage(page.index);
    const shouldRenderForms = (options == null ? void 0 : options.withForms) ?? false;
    const formHandle = shouldRenderForms ? pageCtx.getFormHandle() : void 0;
    const heapPtr = this.memoryManager.malloc(bytes);
    const bitmapPtr = this.pdfiumModule.FPDFBitmap_CreateEx(
      wDev,
      hDev,
      4,
      heapPtr,
      stride
    );
    this.pdfiumModule.FPDFBitmap_FillRect(bitmapPtr, 0, 0, wDev, hDev, 4294967295);
    const M = buildUserToDeviceMatrix(rect, rotation, wDev, hDev);
    const mPtr = this.memoryManager.malloc(6 * 4);
    const mView = new Float32Array(this.pdfiumModule.pdfium.HEAPF32.buffer, mPtr, 6);
    mView.set([M.a, M.b, M.c, M.d, M.e, M.f]);
    const clipPtr = this.memoryManager.malloc(4 * 4);
    const clipView = new Float32Array(this.pdfiumModule.pdfium.HEAPF32.buffer, clipPtr, 4);
    clipView.set([0, 0, wDev, hDev]);
    let flags = 16;
    if ((options == null ? void 0 : options.withAnnotations) ?? false) flags |= 1;
    try {
      this.pdfiumModule.FPDF_RenderPageBitmapWithMatrix(
        bitmapPtr,
        pageCtx.pagePtr,
        mPtr,
        clipPtr,
        flags
      );
      if (formHandle !== void 0) {
        const formParams = computeFormDrawParams(M, rect, page.size, rotation);
        const { startX, startY, formsWidth, formsHeight, scaleX, scaleY } = formParams;
        this.pdfiumModule.FPDF_FFLDraw(
          formHandle,
          bitmapPtr,
          pageCtx.pagePtr,
          startX,
          startY,
          formsWidth,
          formsHeight,
          rotation,
          flags
        );
      }
    } finally {
      pageCtx.release();
      this.memoryManager.free(mPtr);
      this.memoryManager.free(clipPtr);
    }
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RenderRectEncodedData`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const data = this.pdfiumModule.pdfium.HEAPU8.subarray(heapPtr, heapPtr + bytes);
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RenderRectEncodedData`,
      "End",
      `${doc.id}-${page.index}`
    );
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RenderRectEncodedImageData`,
      "Begin",
      `${doc.id}-${page.index}`
    );
    const imageDataLike = {
      data: new Uint8ClampedArray(data),
      width: wDev,
      height: hDev
    };
    this.logger.perf(
      LOG_SOURCE,
      LOG_CATEGORY,
      `RenderRectEncodedImageData`,
      "End",
      `${doc.id}-${page.index}`
    );
    task.resolve(imageDataLike);
    this.pdfiumModule.FPDFBitmap_Destroy(bitmapPtr);
    this.memoryManager.free(heapPtr);
    return task;
  }
  /**
   * Read the target of pdf link annotation
   * @param docPtr - pointer to pdf document object
   * @param getActionPtr - callback function to retrive the pointer of action
   * @param getDestinationPtr - callback function to retrive the pointer of destination
   * @returns target of link
   *
   * @private
   */
  readPdfLinkAnnoTarget(docPtr, getActionPtr, getDestinationPtr) {
    const destinationPtr = getDestinationPtr();
    if (destinationPtr) {
      const destination = this.readPdfDestination(docPtr, destinationPtr);
      return {
        type: "destination",
        destination
      };
    } else {
      const actionPtr = getActionPtr();
      if (actionPtr) {
        const action = this.readPdfAction(docPtr, actionPtr);
        return {
          type: "action",
          action
        };
      }
    }
  }
  createLocalDestPtr(docPtr, dest) {
    var _a, _b;
    const pagePtr = this.pdfiumModule.FPDF_LoadPage(docPtr, dest.pageIndex);
    if (!pagePtr) return 0;
    try {
      if (dest.zoom.mode === PdfZoomMode.XYZ) {
        const { x, y, zoom } = dest.zoom.params;
        return this.pdfiumModule.EPDFDest_CreateXYZ(
          pagePtr,
          /*has_left*/
          true,
          x,
          /*has_top*/
          true,
          y,
          /*has_zoom*/
          true,
          zoom
        );
      }
      let viewEnum;
      let params = [];
      switch (dest.zoom.mode) {
        case PdfZoomMode.FitPage:
          viewEnum = PdfZoomMode.FitPage;
          break;
        case PdfZoomMode.FitHorizontal:
          viewEnum = PdfZoomMode.FitHorizontal;
          params = [((_a = dest.view) == null ? void 0 : _a[0]) ?? 0];
          break;
        case PdfZoomMode.FitVertical:
          viewEnum = PdfZoomMode.FitVertical;
          params = [((_b = dest.view) == null ? void 0 : _b[0]) ?? 0];
          break;
        case PdfZoomMode.FitRectangle:
          {
            const v = dest.view ?? [];
            params = [v[0] ?? 0, v[1] ?? 0, v[2] ?? 0, v[3] ?? 0];
            viewEnum = PdfZoomMode.FitRectangle;
          }
          break;
        case PdfZoomMode.Unknown:
        default:
          return 0;
      }
      return this.withFloatArray(
        params,
        (ptr, count) => this.pdfiumModule.EPDFDest_CreateView(pagePtr, viewEnum, ptr, count)
      );
    } finally {
      this.pdfiumModule.FPDF_ClosePage(pagePtr);
    }
  }
  applyBookmarkTarget(docPtr, bmPtr, target) {
    if (target.type === "destination") {
      const destPtr = this.createLocalDestPtr(docPtr, target.destination);
      if (!destPtr) return false;
      const ok = this.pdfiumModule.EPDFBookmark_SetDest(docPtr, bmPtr, destPtr);
      return !!ok;
    }
    const action = target.action;
    switch (action.type) {
      case PdfActionType.Goto: {
        const destPtr = this.createLocalDestPtr(docPtr, action.destination);
        if (!destPtr) return false;
        const actPtr = this.pdfiumModule.EPDFAction_CreateGoTo(docPtr, destPtr);
        if (!actPtr) return false;
        return !!this.pdfiumModule.EPDFBookmark_SetAction(docPtr, bmPtr, actPtr);
      }
      case PdfActionType.URI: {
        const actPtr = this.pdfiumModule.EPDFAction_CreateURI(docPtr, action.uri);
        if (!actPtr) return false;
        return !!this.pdfiumModule.EPDFBookmark_SetAction(docPtr, bmPtr, actPtr);
      }
      case PdfActionType.LaunchAppOrOpenFile: {
        const actPtr = this.withWString(
          action.path,
          (wptr) => this.pdfiumModule.EPDFAction_CreateLaunch(docPtr, wptr)
        );
        if (!actPtr) return false;
        return !!this.pdfiumModule.EPDFBookmark_SetAction(docPtr, bmPtr, actPtr);
      }
      case PdfActionType.RemoteGoto:
        return false;
      case PdfActionType.Unsupported:
      default:
        return false;
    }
  }
  /**
   * Apply a link target (action or destination) to a link annotation
   * @param docPtr - pointer to pdf document
   * @param annotationPtr - pointer to the link annotation
   * @param target - the link target to apply
   * @returns true if successful
   *
   * @private
   */
  applyLinkTarget(docPtr, annotationPtr, target) {
    if (target.type === "destination") {
      const destPtr = this.createLocalDestPtr(docPtr, target.destination);
      if (!destPtr) return false;
      const actPtr = this.pdfiumModule.EPDFAction_CreateGoTo(docPtr, destPtr);
      if (!actPtr) return false;
      return !!this.pdfiumModule.EPDFAnnot_SetAction(annotationPtr, actPtr);
    }
    const action = target.action;
    switch (action.type) {
      case PdfActionType.Goto: {
        const destPtr = this.createLocalDestPtr(docPtr, action.destination);
        if (!destPtr) return false;
        const actPtr = this.pdfiumModule.EPDFAction_CreateGoTo(docPtr, destPtr);
        if (!actPtr) return false;
        return !!this.pdfiumModule.EPDFAnnot_SetAction(annotationPtr, actPtr);
      }
      case PdfActionType.URI: {
        const actPtr = this.pdfiumModule.EPDFAction_CreateURI(docPtr, action.uri);
        if (!actPtr) return false;
        return !!this.pdfiumModule.EPDFAnnot_SetAction(annotationPtr, actPtr);
      }
      case PdfActionType.LaunchAppOrOpenFile: {
        const actPtr = this.withWString(
          action.path,
          (wptr) => this.pdfiumModule.EPDFAction_CreateLaunch(docPtr, wptr)
        );
        if (!actPtr) return false;
        return !!this.pdfiumModule.EPDFAnnot_SetAction(annotationPtr, actPtr);
      }
      case PdfActionType.RemoteGoto:
      case PdfActionType.Unsupported:
      default:
        return false;
    }
  }
  /**
   * Read pdf action from pdf document
   * @param docPtr - pointer to pdf document object
   * @param actionPtr - pointer to pdf action object
   * @returns pdf action object
   *
   * @private
   */
  readPdfAction(docPtr, actionPtr) {
    const actionType = this.pdfiumModule.FPDFAction_GetType(actionPtr);
    let action;
    switch (actionType) {
      case PdfActionType.Unsupported:
        action = {
          type: PdfActionType.Unsupported
        };
        break;
      case PdfActionType.Goto:
        {
          const destinationPtr = this.pdfiumModule.FPDFAction_GetDest(docPtr, actionPtr);
          if (destinationPtr) {
            const destination = this.readPdfDestination(docPtr, destinationPtr);
            action = {
              type: PdfActionType.Goto,
              destination
            };
          } else {
            action = {
              type: PdfActionType.Unsupported
            };
          }
        }
        break;
      case PdfActionType.RemoteGoto:
        {
          action = {
            type: PdfActionType.Unsupported
          };
        }
        break;
      case PdfActionType.URI:
        {
          const uri = readString(
            this.pdfiumModule.pdfium,
            (buffer, bufferLength) => {
              return this.pdfiumModule.FPDFAction_GetURIPath(
                docPtr,
                actionPtr,
                buffer,
                bufferLength
              );
            },
            this.pdfiumModule.pdfium.UTF8ToString
          );
          action = {
            type: PdfActionType.URI,
            uri
          };
        }
        break;
      case PdfActionType.LaunchAppOrOpenFile:
        {
          const path = readString(
            this.pdfiumModule.pdfium,
            (buffer, bufferLength) => {
              return this.pdfiumModule.FPDFAction_GetFilePath(actionPtr, buffer, bufferLength);
            },
            this.pdfiumModule.pdfium.UTF8ToString
          );
          action = {
            type: PdfActionType.LaunchAppOrOpenFile,
            path
          };
        }
        break;
    }
    return action;
  }
  /**
   * Read pdf destination object
   * @param docPtr - pointer to pdf document object
   * @param destinationPtr - pointer to pdf destination
   * @returns pdf destination object
   *
   * @private
   */
  readPdfDestination(docPtr, destinationPtr) {
    const pageIndex = this.pdfiumModule.FPDFDest_GetDestPageIndex(docPtr, destinationPtr);
    const maxParmamsCount = 4;
    const paramsCountPtr = this.memoryManager.malloc(maxParmamsCount);
    const paramsPtr = this.memoryManager.malloc(maxParmamsCount * 4);
    const zoomMode = this.pdfiumModule.FPDFDest_GetView(
      destinationPtr,
      paramsCountPtr,
      paramsPtr
    );
    const paramsCount = this.pdfiumModule.pdfium.getValue(paramsCountPtr, "i32");
    const view = [];
    for (let i = 0; i < paramsCount; i++) {
      const paramPtr = paramsPtr + i * 4;
      view.push(this.pdfiumModule.pdfium.getValue(paramPtr, "float"));
    }
    this.memoryManager.free(paramsCountPtr);
    this.memoryManager.free(paramsPtr);
    if (zoomMode === PdfZoomMode.XYZ) {
      const hasXPtr = this.memoryManager.malloc(1);
      const hasYPtr = this.memoryManager.malloc(1);
      const hasZPtr = this.memoryManager.malloc(1);
      const xPtr = this.memoryManager.malloc(4);
      const yPtr = this.memoryManager.malloc(4);
      const zPtr = this.memoryManager.malloc(4);
      const isSucceed = this.pdfiumModule.FPDFDest_GetLocationInPage(
        destinationPtr,
        hasXPtr,
        hasYPtr,
        hasZPtr,
        xPtr,
        yPtr,
        zPtr
      );
      if (isSucceed) {
        const hasX = this.pdfiumModule.pdfium.getValue(hasXPtr, "i8");
        const hasY = this.pdfiumModule.pdfium.getValue(hasYPtr, "i8");
        const hasZ = this.pdfiumModule.pdfium.getValue(hasZPtr, "i8");
        const x = hasX ? this.pdfiumModule.pdfium.getValue(xPtr, "float") : 0;
        const y = hasY ? this.pdfiumModule.pdfium.getValue(yPtr, "float") : 0;
        const zoom = hasZ ? this.pdfiumModule.pdfium.getValue(zPtr, "float") : 0;
        this.memoryManager.free(hasXPtr);
        this.memoryManager.free(hasYPtr);
        this.memoryManager.free(hasZPtr);
        this.memoryManager.free(xPtr);
        this.memoryManager.free(yPtr);
        this.memoryManager.free(zPtr);
        return {
          pageIndex,
          zoom: {
            mode: zoomMode,
            params: {
              x,
              y,
              zoom
            }
          },
          view
        };
      }
      this.memoryManager.free(hasXPtr);
      this.memoryManager.free(hasYPtr);
      this.memoryManager.free(hasZPtr);
      this.memoryManager.free(xPtr);
      this.memoryManager.free(yPtr);
      this.memoryManager.free(zPtr);
      return {
        pageIndex,
        zoom: {
          mode: zoomMode,
          params: {
            x: 0,
            y: 0,
            zoom: 0
          }
        },
        view
      };
    }
    return {
      pageIndex,
      zoom: {
        mode: zoomMode
      },
      view
    };
  }
  /**
   * Read attachmet from pdf document
   * @param docPtr - pointer to pdf document object
   * @param index - index of attachment
   * @returns attachment content
   *
   * @private
   */
  readPdfAttachment(docPtr, index) {
    const attachmentPtr = this.pdfiumModule.FPDFDoc_GetAttachment(docPtr, index);
    const name = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.FPDFAttachment_GetName(attachmentPtr, buffer, bufferLength);
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const description = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.EPDFAttachment_GetDescription(attachmentPtr, buffer, bufferLength);
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const mimeType = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.FPDFAttachment_GetSubtype(attachmentPtr, buffer, bufferLength);
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const creationDate = this.getAttachmentDate(attachmentPtr, "CreationDate");
    const checksum = readString(
      this.pdfiumModule.pdfium,
      (buffer, bufferLength) => {
        return this.pdfiumModule.FPDFAttachment_GetStringValue(
          attachmentPtr,
          "Checksum",
          buffer,
          bufferLength
        );
      },
      this.pdfiumModule.pdfium.UTF16ToString
    );
    const size = this.getAttachmentNumber(attachmentPtr, "Size");
    return {
      index,
      name,
      description,
      mimeType,
      size,
      creationDate,
      checksum
    };
  }
  /**
   * Convert coordinate of point from device coordinate to page coordinate
   * @param doc - pdf document object
   * @param page  - pdf page infor
   * @param position - position of point
   * @returns converted position
   *
   * @private
   */
  convertDevicePointToPagePoint(doc, page, position) {
    const DW = page.size.width;
    const DH = page.size.height;
    const r = doc.normalizedRotation ? 0 : page.rotation & 3;
    if (r === 0) {
      return { x: position.x, y: DH - position.y };
    }
    if (r === 1) {
      return { x: position.y, y: position.x };
    }
    if (r === 2) {
      return { x: DW - position.x, y: position.y };
    }
    {
      return { x: DH - position.y, y: DW - position.x };
    }
  }
  /**
   * Convert coordinate of point from page coordinate to device coordinate
   * @param doc - pdf document object
   * @param page  - pdf page infor
   * @param position - position of point
   * @returns converted position
   *
   * @private
   */
  convertPagePointToDevicePoint(doc, page, position) {
    const DW = page.size.width;
    const DH = page.size.height;
    const r = doc.normalizedRotation ? 0 : page.rotation & 3;
    if (r === 0) {
      return { x: position.x, y: DH - position.y };
    }
    if (r === 1) {
      return { x: position.y, y: position.x };
    }
    if (r === 2) {
      return { x: DW - position.x, y: position.y };
    }
    {
      return { x: DW - position.y, y: DH - position.x };
    }
  }
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
  convertPageRectToDeviceRect(doc, page, pageRect) {
    const { x, y } = this.convertPagePointToDevicePoint(doc, page, {
      x: pageRect.left,
      y: pageRect.top
    });
    const rect = {
      origin: {
        x,
        y
      },
      size: {
        width: Math.abs(pageRect.right - pageRect.left),
        height: Math.abs(pageRect.top - pageRect.bottom)
      }
    };
    return rect;
  }
  /**
   * Read the appearance stream of annotation
   * @param annotationPtr - pointer to pdf annotation
   * @param mode - appearance mode
   * @returns appearance stream
   *
   * @private
   */
  readPageAnnoAppearanceStreams(annotationPtr) {
    return {
      normal: this.readPageAnnoAppearanceStream(annotationPtr, AppearanceMode.Normal),
      rollover: this.readPageAnnoAppearanceStream(annotationPtr, AppearanceMode.Rollover),
      down: this.readPageAnnoAppearanceStream(annotationPtr, AppearanceMode.Down)
    };
  }
  /**
   * Read the appearance stream of annotation
   * @param annotationPtr - pointer to pdf annotation
   * @param mode - appearance mode
   * @returns appearance stream
   *
   * @private
   */
  readPageAnnoAppearanceStream(annotationPtr, mode = AppearanceMode.Normal) {
    const utf16Length = this.pdfiumModule.FPDFAnnot_GetAP(annotationPtr, mode, 0, 0);
    const bytesCount = (utf16Length + 1) * 2;
    const bufferPtr = this.memoryManager.malloc(bytesCount);
    this.pdfiumModule.FPDFAnnot_GetAP(annotationPtr, mode, bufferPtr, bytesCount);
    const ap = this.pdfiumModule.pdfium.UTF16ToString(bufferPtr);
    this.memoryManager.free(bufferPtr);
    return ap;
  }
  /**
   * Set the appearance stream of annotation
   * @param annotationPtr - pointer to pdf annotation
   * @param mode - appearance mode
   * @param apContent - appearance stream content (null to remove)
   * @returns whether the appearance stream was set successfully
   *
   * @private
   */
  setPageAnnoAppearanceStream(annotationPtr, mode = AppearanceMode.Normal, apContent) {
    const bytes = 2 * (apContent.length + 1);
    const ptr = this.memoryManager.malloc(bytes);
    try {
      this.pdfiumModule.pdfium.stringToUTF16(apContent, ptr, bytes);
      const ok = this.pdfiumModule.FPDFAnnot_SetAP(annotationPtr, mode, ptr);
      return !!ok;
    } finally {
      this.memoryManager.free(ptr);
    }
  }
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
  setPageAnnoRect(doc, page, annotPtr, rect) {
    const x0d = Math.floor(rect.origin.x);
    const y0d = Math.floor(rect.origin.y);
    const x1d = Math.floor(rect.origin.x + rect.size.width);
    const y1d = Math.floor(rect.origin.y + rect.size.height);
    const TL = this.convertDevicePointToPagePoint(doc, page, { x: x0d, y: y0d });
    const TR = this.convertDevicePointToPagePoint(doc, page, { x: x1d, y: y0d });
    const BR = this.convertDevicePointToPagePoint(doc, page, { x: x1d, y: y1d });
    const BL = this.convertDevicePointToPagePoint(doc, page, { x: x0d, y: y1d });
    let left = Math.min(TL.x, TR.x, BR.x, BL.x);
    let right = Math.max(TL.x, TR.x, BR.x, BL.x);
    let bottom = Math.min(TL.y, TR.y, BR.y, BL.y);
    let top = Math.max(TL.y, TR.y, BR.y, BL.y);
    if (left > right) [left, right] = [right, left];
    if (bottom > top) [bottom, top] = [top, bottom];
    const ptr = this.memoryManager.malloc(16);
    const pdf = this.pdfiumModule.pdfium;
    pdf.setValue(ptr + 0, left, "float");
    pdf.setValue(ptr + 4, top, "float");
    pdf.setValue(ptr + 8, right, "float");
    pdf.setValue(ptr + 12, bottom, "float");
    const ok = this.pdfiumModule.FPDFAnnot_SetRect(annotPtr, ptr);
    this.memoryManager.free(ptr);
    return !!ok;
  }
  /**
   * Read the rectangle of annotation
   * @param annotationPtr - pointer to pdf annotation
   * @returns rectangle of annotation
   *
   * @private
   */
  readPageAnnoRect(annotationPtr) {
    const pageRectPtr = this.memoryManager.malloc(4 * 4);
    const pageRect = {
      left: 0,
      top: 0,
      right: 0,
      bottom: 0
    };
    if (this.pdfiumModule.EPDFAnnot_GetRect(annotationPtr, pageRectPtr)) {
      pageRect.left = this.pdfiumModule.pdfium.getValue(pageRectPtr, "float");
      pageRect.top = this.pdfiumModule.pdfium.getValue(pageRectPtr + 4, "float");
      pageRect.right = this.pdfiumModule.pdfium.getValue(pageRectPtr + 8, "float");
      pageRect.bottom = this.pdfiumModule.pdfium.getValue(pageRectPtr + 12, "float");
    }
    this.memoryManager.free(pageRectPtr);
    return pageRect;
  }
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
  getHighlightRects(doc, page, textPagePtr, startIndex, charCount) {
    const rectsCount = this.pdfiumModule.FPDFText_CountRects(textPagePtr, startIndex, charCount);
    const highlightRects = [];
    const l = this.memoryManager.malloc(8);
    const t = this.memoryManager.malloc(8);
    const r = this.memoryManager.malloc(8);
    const b = this.memoryManager.malloc(8);
    for (let i = 0; i < rectsCount; i++) {
      const ok = this.pdfiumModule.FPDFText_GetRect(textPagePtr, i, l, t, r, b);
      if (!ok) continue;
      const left = this.pdfiumModule.pdfium.getValue(l, "double");
      const top = this.pdfiumModule.pdfium.getValue(t, "double");
      const right = this.pdfiumModule.pdfium.getValue(r, "double");
      const bottom = this.pdfiumModule.pdfium.getValue(b, "double");
      const p1 = this.convertPagePointToDevicePoint(doc, page, { x: left, y: top });
      const p2 = this.convertPagePointToDevicePoint(doc, page, { x: right, y: top });
      const p3 = this.convertPagePointToDevicePoint(doc, page, { x: right, y: bottom });
      const p4 = this.convertPagePointToDevicePoint(doc, page, { x: left, y: bottom });
      const xs = [p1.x, p2.x, p3.x, p4.x];
      const ys = [p1.y, p2.y, p3.y, p4.y];
      const x = Math.min(...xs);
      const y = Math.min(...ys);
      const width = Math.max(...xs) - x;
      const height = Math.max(...ys) - y;
      highlightRects.push({
        origin: { x, y },
        size: { width: Math.ceil(width), height: Math.ceil(height) }
      });
    }
    this.memoryManager.free(l);
    this.memoryManager.free(t);
    this.memoryManager.free(r);
    this.memoryManager.free(b);
    return highlightRects;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.searchAllPages}
   *
   * Runs inside the worker.
   * Emits per-page progress: { page, results }
   *
   * @public
   */
  searchInPage(doc, page, keyword, flags) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "searchInPage", doc, page, keyword, flags);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `SearchInPage`, "Begin", `${doc.id}-${page.index}`);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "Document is not open"
      });
    }
    const length = 2 * (keyword.length + 1);
    const keywordPtr = this.memoryManager.malloc(length);
    this.pdfiumModule.pdfium.stringToUTF16(keyword, keywordPtr, length);
    try {
      const results = this.searchAllInPage(doc, ctx, page, keywordPtr, flags);
      return PdfTaskHelper.resolve(results);
    } finally {
      this.memoryManager.free(keywordPtr);
    }
  }
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
  getAnnotationsBatch(doc, pages) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getAnnotationsBatch", doc.id, pages.length);
    const task = new Task();
    queueMicrotask(() => {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "GetAnnotationsBatch", "Begin", doc.id);
      const ctx = this.cache.getContext(doc.id);
      if (!ctx) {
        task.reject({ code: PdfErrorCode.DocNotOpen, message: "Document is not open" });
        return;
      }
      const results = {};
      const total = pages.length;
      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];
        const annotations = this.readPageAnnotationsRaw(doc, ctx, page);
        results[page.index] = annotations;
        task.progress({
          pageIndex: page.index,
          result: annotations,
          completed: i + 1,
          total
        });
      }
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "GetAnnotationsBatch", "End", doc.id);
      task.resolve(results);
    });
    return task;
  }
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
  searchBatch(doc, pages, keyword, flags) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "searchBatch", doc.id, pages.length, keyword);
    const task = new Task();
    queueMicrotask(() => {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "SearchBatch", "Begin", doc.id);
      const ctx = this.cache.getContext(doc.id);
      if (!ctx) {
        task.reject({ code: PdfErrorCode.DocNotOpen, message: "Document is not open" });
        return;
      }
      const length = 2 * (keyword.length + 1);
      const keywordPtr = this.memoryManager.malloc(length);
      this.pdfiumModule.pdfium.stringToUTF16(keyword, keywordPtr, length);
      try {
        const results = {};
        const total = pages.length;
        for (let i = 0; i < pages.length; i++) {
          const page = pages[i];
          const pageResults = this.searchAllInPage(doc, ctx, page, keywordPtr, flags);
          results[page.index] = pageResults;
          task.progress({
            pageIndex: page.index,
            result: pageResults,
            completed: i + 1,
            total
          });
        }
        this.logger.perf(LOG_SOURCE, LOG_CATEGORY, "SearchBatch", "End", doc.id);
        task.resolve(results);
      } finally {
        this.memoryManager.free(keywordPtr);
      }
    });
    return task;
  }
  /**
   * Extract word-aligned context for a search hit.
   *
   * @param fullText      full UTF-16 page text (fetch this once per page!)
   * @param start         index of 1st char that matched
   * @param count         number of chars in the match
   * @param windowChars   minimum context chars to keep left & right
   */
  buildContext(fullText, start, count, windowChars = 30) {
    const WORD_BREAK = /[\s\u00A0.,;:!?()\[\]{}<>/\\\-"'`"”\u2013\u2014]/;
    const findWordStart = (index) => {
      while (index > 0 && !WORD_BREAK.test(fullText[index - 1])) index--;
      return index;
    };
    const findWordEnd = (index) => {
      while (index < fullText.length && !WORD_BREAK.test(fullText[index])) index++;
      return index;
    };
    let left = start;
    while (left > 0 && WORD_BREAK.test(fullText[left - 1])) left--;
    let collected = 0;
    while (left > 0 && collected < windowChars) {
      left--;
      if (!WORD_BREAK.test(fullText[left])) collected++;
    }
    left = findWordStart(left);
    let right = start + count;
    while (right < fullText.length && WORD_BREAK.test(fullText[right])) right++;
    collected = 0;
    while (right < fullText.length && collected < windowChars) {
      if (!WORD_BREAK.test(fullText[right])) collected++;
      right++;
    }
    right = findWordEnd(right);
    const before = fullText.slice(left, start).replace(/\s+/g, " ").trimStart();
    const match = fullText.slice(start, start + count);
    const after = fullText.slice(start + count, right).replace(/\s+/g, " ").trimEnd();
    return {
      before: this.tidy(before),
      match: this.tidy(match),
      after: this.tidy(after),
      truncatedLeft: left > 0,
      truncatedRight: right < fullText.length
    };
  }
  /**
   * Tidy the text to remove any non-printable characters and whitespace
   * @param s - text to tidy
   * @returns tidied text
   *
   * @private
   */
  tidy(s) {
    return s.replace(/-\uFFFE\s*/g, "").replace(/[\uFFFE\u00AD\u200B\u2060\uFEFF]/g, "").replace(/\s+/g, " ");
  }
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
  searchAllInPage(doc, ctx, page, keywordPtr, flag) {
    return ctx.borrowPage(page.index, (pageCtx) => {
      const textPagePtr = pageCtx.getTextPage();
      const total = this.pdfiumModule.FPDFText_CountChars(textPagePtr);
      const bufPtr = this.memoryManager.malloc(2 * (total + 1));
      this.pdfiumModule.FPDFText_GetText(textPagePtr, 0, total, bufPtr);
      const fullText = this.pdfiumModule.pdfium.UTF16ToString(bufPtr);
      this.memoryManager.free(bufPtr);
      const pageResults = [];
      const searchHandle = this.pdfiumModule.FPDFText_FindStart(
        textPagePtr,
        keywordPtr,
        flag,
        0
        // Start from the beginning of the page
      );
      while (this.pdfiumModule.FPDFText_FindNext(searchHandle)) {
        const charIndex = this.pdfiumModule.FPDFText_GetSchResultIndex(searchHandle);
        const charCount = this.pdfiumModule.FPDFText_GetSchCount(searchHandle);
        const rects = this.getHighlightRects(doc, page, textPagePtr, charIndex, charCount);
        const context = this.buildContext(fullText, charIndex, charCount);
        pageResults.push({
          pageIndex: page.index,
          charIndex,
          charCount,
          rects,
          context
        });
      }
      this.pdfiumModule.FPDFText_FindClose(searchHandle);
      return pageResults;
    });
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.preparePrintDocument}
   *
   * Prepares a PDF document for printing with specified options.
   * Creates a new document with selected pages and optionally removes annotations
   * for optimal printing performance.
   *
   * @public
   */
  preparePrintDocument(doc, options) {
    const { includeAnnotations = true, pageRange = null } = options ?? {};
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "preparePrintDocument", doc, options);
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "Begin", doc.id);
    const ctx = this.cache.getContext(doc.id);
    if (!ctx) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.DocNotOpen,
        message: "Document is not open"
      });
    }
    const printDocPtr = this.pdfiumModule.FPDF_CreateNewDocument();
    if (!printDocPtr) {
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.CantCreateNewDoc,
        message: "Cannot create print document"
      });
    }
    try {
      const sanitizedPageRange = this.sanitizePageRange(pageRange, doc.pageCount);
      if (!this.pdfiumModule.FPDF_ImportPages(
        printDocPtr,
        ctx.docPtr,
        sanitizedPageRange ?? "",
        0
        // Insert at beginning
      )) {
        this.pdfiumModule.FPDF_CloseDocument(printDocPtr);
        this.logger.error(LOG_SOURCE, LOG_CATEGORY, "Failed to import pages for printing");
        this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "End", doc.id);
        return PdfTaskHelper.reject({
          code: PdfErrorCode.CantImportPages,
          message: "Failed to import pages for printing"
        });
      }
      if (!includeAnnotations) {
        const removalResult = this.removeAnnotationsFromPrintDocument(printDocPtr);
        if (!removalResult.success) {
          this.pdfiumModule.FPDF_CloseDocument(printDocPtr);
          this.logger.error(
            LOG_SOURCE,
            LOG_CATEGORY,
            `Failed to remove annotations: ${removalResult.error}`
          );
          this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "End", doc.id);
          return PdfTaskHelper.reject({
            code: PdfErrorCode.Unknown,
            message: `Failed to prepare print document: ${removalResult.error}`
          });
        }
        this.logger.debug(
          LOG_SOURCE,
          LOG_CATEGORY,
          `Removed ${removalResult.annotationsRemoved} annotations from ${removalResult.pagesProcessed} pages`
        );
      }
      const buffer = this.saveDocument(printDocPtr);
      this.pdfiumModule.FPDF_CloseDocument(printDocPtr);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "End", doc.id);
      return PdfTaskHelper.resolve(buffer);
    } catch (error) {
      if (printDocPtr) {
        this.pdfiumModule.FPDF_CloseDocument(printDocPtr);
      }
      this.logger.error(LOG_SOURCE, LOG_CATEGORY, "preparePrintDocument failed", error);
      this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `PreparePrintDocument`, "End", doc.id);
      return PdfTaskHelper.reject({
        code: PdfErrorCode.Unknown,
        message: error instanceof Error ? error.message : "Failed to prepare print document"
      });
    }
  }
  /**
   * Removes all annotations from a print document using fast raw annotation functions.
   * This method is optimized for performance by avoiding full page loading.
   *
   * @param printDocPtr - Pointer to the print document
   * @returns Result object with success status and statistics
   *
   * @private
   */
  removeAnnotationsFromPrintDocument(printDocPtr) {
    let totalAnnotationsRemoved = 0;
    let pagesProcessed = 0;
    try {
      const pageCount = this.pdfiumModule.FPDF_GetPageCount(printDocPtr);
      for (let pageIndex = 0; pageIndex < pageCount; pageIndex++) {
        const annotCount = this.pdfiumModule.EPDFPage_GetAnnotCountRaw(printDocPtr, pageIndex);
        if (annotCount <= 0) {
          pagesProcessed++;
          continue;
        }
        let annotationsRemovedFromPage = 0;
        for (let annotIndex = annotCount - 1; annotIndex >= 0; annotIndex--) {
          const removed = this.pdfiumModule.EPDFPage_RemoveAnnotRaw(
            printDocPtr,
            pageIndex,
            annotIndex
          );
          if (removed) {
            annotationsRemovedFromPage++;
            totalAnnotationsRemoved++;
          } else {
            this.logger.warn(
              LOG_SOURCE,
              LOG_CATEGORY,
              `Failed to remove annotation ${annotIndex} from page ${pageIndex}`
            );
          }
        }
        if (annotationsRemovedFromPage > 0) {
          const pagePtr = this.pdfiumModule.FPDF_LoadPage(printDocPtr, pageIndex);
          if (pagePtr) {
            this.pdfiumModule.FPDFPage_GenerateContent(pagePtr);
            this.pdfiumModule.FPDF_ClosePage(pagePtr);
          }
        }
        pagesProcessed++;
      }
      return {
        success: true,
        annotationsRemoved: totalAnnotationsRemoved,
        pagesProcessed
      };
    } catch (error) {
      return {
        success: false,
        annotationsRemoved: totalAnnotationsRemoved,
        pagesProcessed,
        error: error instanceof Error ? error.message : "Unknown error during annotation removal"
      };
    }
  }
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
  sanitizePageRange(pageRange, totalPages) {
    if (!pageRange || pageRange.trim() === "") {
      return null;
    }
    try {
      const sanitized = [];
      const parts = pageRange.split(",");
      for (const part of parts) {
        const trimmed = part.trim();
        if (trimmed.includes("-")) {
          const [startStr, endStr] = trimmed.split("-").map((s) => s.trim());
          const start = parseInt(startStr, 10);
          const end = parseInt(endStr, 10);
          if (isNaN(start) || isNaN(end)) {
            this.logger.warn(LOG_SOURCE, LOG_CATEGORY, `Invalid range: ${trimmed}`);
            continue;
          }
          const validStart = Math.max(1, Math.min(start, totalPages));
          const validEnd = Math.max(1, Math.min(end, totalPages));
          for (let i = validStart; i <= validEnd; i++) {
            if (!sanitized.includes(i)) {
              sanitized.push(i);
            }
          }
        } else {
          const pageNum = parseInt(trimmed, 10);
          if (isNaN(pageNum)) {
            this.logger.warn(LOG_SOURCE, LOG_CATEGORY, `Invalid page number: ${trimmed}`);
            continue;
          }
          const validPageNum = Math.max(1, Math.min(pageNum, totalPages));
          if (!sanitized.includes(validPageNum)) {
            sanitized.push(validPageNum);
          }
        }
      }
      if (sanitized.length === 0) {
        this.logger.warn(LOG_SOURCE, LOG_CATEGORY, "No valid pages in range, using all pages");
        return null;
      }
      sanitized.sort((a, b) => a - b);
      const optimized = [];
      let rangeStart = sanitized[0];
      let rangeEnd = sanitized[0];
      for (let i = 1; i < sanitized.length; i++) {
        if (sanitized[i] === rangeEnd + 1) {
          rangeEnd = sanitized[i];
        } else {
          if (rangeStart === rangeEnd) {
            optimized.push(rangeStart.toString());
          } else if (rangeEnd - rangeStart === 1) {
            optimized.push(rangeStart.toString());
            optimized.push(rangeEnd.toString());
          } else {
            optimized.push(`${rangeStart}-${rangeEnd}`);
          }
          rangeStart = sanitized[i];
          rangeEnd = sanitized[i];
        }
      }
      if (rangeStart === rangeEnd) {
        optimized.push(rangeStart.toString());
      } else if (rangeEnd - rangeStart === 1) {
        optimized.push(rangeStart.toString());
        optimized.push(rangeEnd.toString());
      } else {
        optimized.push(`${rangeStart}-${rangeEnd}`);
      }
      const result = optimized.join(",");
      this.logger.debug(
        LOG_SOURCE,
        LOG_CATEGORY,
        `Sanitized page range: "${pageRange}" -> "${result}"`
      );
      return result;
    } catch (error) {
      this.logger.error(LOG_SOURCE, LOG_CATEGORY, `Error sanitizing page range: ${error}`);
      return null;
    }
  }
}
async function createPdfiumEngine(wasmUrl, options) {
  const response = await fetch(wasmUrl);
  const wasmBinary = await response.arrayBuffer();
  const wasmModule = await init({ wasmBinary });
  const native = new PdfiumNative(wasmModule, {
    logger: options == null ? void 0 : options.logger,
    fontFallback: options == null ? void 0 : options.fontFallback
  });
  return new PdfEngine(native, {
    imageConverter: browserImageDataToBlobConverter,
    logger: options == null ? void 0 : options.logger
  });
}
export {
  BitmapFormat as B,
  FontFallbackManager as F,
  PdfiumErrorCode as P,
  RenderFlag as R,
  PdfiumNative as a,
  createNodeFontLoader as b,
  computeFormDrawParams as c,
  createPdfiumEngine as d,
  readString as e,
  isValidCustomKey as i,
  readArrayBuffer as r
};
//# sourceMappingURL=direct-engine-D-Jf9yyY.js.map
