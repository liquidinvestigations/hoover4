import { DEFAULT_PDFIUM_WASM_URL, FONT_CDN_URLS, cdnFontConfig, createCdnFontConfig } from "./lib/pdfium/index.js";
import { WebWorkerEngine, WorkerTask } from "./lib/webworker/engine.js";
import { NoopLogger, PdfErrorCode } from "@embedpdf/models";
import { FontCharset } from "@embedpdf/models";
import { B, F, P, a, R, c, b, d, i, r, e } from "./direct-engine-D-Jf9yyY.js";
import { I, b as b2, c as c2, a as a2 } from "./browser-BISJ9naB.js";
import { P as P2 } from "./pdf-engine-ZvReuoDb.js";
import { createPdfiumEngine } from "./lib/pdfium/web/worker-engine.js";
const LOG_SOURCE = "WebWorkerEngineRunner";
const LOG_CATEGORY = "Engine";
class EngineRunner {
  /**
   * Create instance of EngineRunnder
   * @param logger - logger instance
   */
  constructor(logger = new NoopLogger()) {
    this.logger = logger;
    this.execute = async (request) => {
      this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "runner start exeucte request");
      if (!this.engine) {
        const error = {
          type: "reject",
          reason: {
            code: PdfErrorCode.NotReady,
            message: "engine has not started yet"
          }
        };
        const response = {
          id: request.id,
          type: "ExecuteResponse",
          data: {
            type: "error",
            value: error
          }
        };
        this.respond(response);
        return;
      }
      const engine = this.engine;
      const { name, args } = request.data;
      if (!engine[name]) {
        const error = {
          type: "reject",
          reason: {
            code: PdfErrorCode.NotSupport,
            message: `engine method ${name} is not supported yet`
          }
        };
        const response = {
          id: request.id,
          type: "ExecuteResponse",
          data: {
            type: "error",
            value: error
          }
        };
        this.respond(response);
        return;
      }
      let task;
      switch (name) {
        case "isSupport":
          task = engine.isSupport(...args);
          break;
        case "destroy":
          task = engine.destroy(...args);
          break;
        case "openDocumentUrl":
          task = engine.openDocumentUrl(...args);
          break;
        case "openDocumentBuffer":
          task = engine.openDocumentBuffer(...args);
          break;
        case "getDocPermissions":
          task = engine.getDocPermissions(...args);
          break;
        case "getDocUserPermissions":
          task = engine.getDocUserPermissions(...args);
          break;
        case "getMetadata":
          task = engine.getMetadata(...args);
          break;
        case "setMetadata":
          task = engine.setMetadata(...args);
          break;
        case "getBookmarks":
          task = engine.getBookmarks(...args);
          break;
        case "setBookmarks":
          task = engine.setBookmarks(...args);
          break;
        case "deleteBookmarks":
          task = engine.deleteBookmarks(...args);
          break;
        case "getSignatures":
          task = engine.getSignatures(...args);
          break;
        case "renderPage":
          task = engine.renderPage(...args);
          break;
        case "renderPageRect":
          task = engine.renderPageRect(...args);
          break;
        case "renderPageRaw":
          task = engine.renderPageRaw(...args);
          break;
        case "renderPageRectRaw":
          task = engine.renderPageRectRaw(...args);
          break;
        case "renderPageAnnotation":
          task = engine.renderPageAnnotation(...args);
          break;
        case "renderPageAnnotations":
          task = engine.renderPageAnnotations(...args);
          break;
        case "renderPageAnnotationsRaw":
          task = engine.renderPageAnnotationsRaw(...args);
          break;
        case "renderThumbnail":
          task = engine.renderThumbnail(...args);
          break;
        case "getAllAnnotations":
          task = engine.getAllAnnotations(...args);
          break;
        case "getPageAnnotations":
          task = engine.getPageAnnotations(...args);
          break;
        case "createPageAnnotation":
          task = engine.createPageAnnotation(...args);
          break;
        case "updatePageAnnotation":
          task = engine.updatePageAnnotation(...args);
          break;
        case "removePageAnnotation":
          task = engine.removePageAnnotation(...args);
          break;
        case "getPageTextRects":
          task = engine.getPageTextRects(...args);
          break;
        case "searchAllPages":
          task = engine.searchAllPages(...args);
          break;
        case "closeDocument":
          task = engine.closeDocument(...args);
          break;
        case "closeAllDocuments":
          task = engine.closeAllDocuments(...args);
          break;
        case "saveAsCopy":
          task = engine.saveAsCopy(...args);
          break;
        case "getAttachments":
          task = engine.getAttachments(...args);
          break;
        case "addAttachment":
          task = engine.addAttachment(...args);
          break;
        case "removeAttachment":
          task = engine.removeAttachment(...args);
          break;
        case "readAttachmentContent":
          task = engine.readAttachmentContent(...args);
          break;
        case "setFormFieldValue":
          task = engine.setFormFieldValue(...args);
          break;
        case "flattenPage":
          task = engine.flattenPage(...args);
          break;
        case "extractPages":
          task = engine.extractPages(...args);
          break;
        case "extractText":
          task = engine.extractText(...args);
          break;
        case "redactTextInRects":
          task = engine.redactTextInRects(...args);
          break;
        case "applyRedaction":
          task = engine.applyRedaction(...args);
          break;
        case "applyAllRedactions":
          task = engine.applyAllRedactions(...args);
          break;
        case "flattenAnnotation":
          task = engine.flattenAnnotation(...args);
          break;
        case "getTextSlices":
          task = engine.getTextSlices(...args);
          break;
        case "getPageGlyphs":
          task = engine.getPageGlyphs(...args);
          break;
        case "getPageGeometry":
          task = engine.getPageGeometry(...args);
          break;
        case "getPageTextRuns":
          task = engine.getPageTextRuns(...args);
          break;
        case "merge":
          task = engine.merge(...args);
          break;
        case "mergePages":
          task = engine.mergePages(...args);
          break;
        case "preparePrintDocument":
          task = engine.preparePrintDocument(...args);
          break;
        case "setDocumentEncryption":
          task = engine.setDocumentEncryption(...args);
          break;
        case "removeEncryption":
          task = engine.removeEncryption(...args);
          break;
        case "unlockOwnerPermissions":
          task = engine.unlockOwnerPermissions(...args);
          break;
        case "isEncrypted":
          task = engine.isEncrypted(...args);
          break;
        case "isOwnerUnlocked":
          task = engine.isOwnerUnlocked(...args);
          break;
        default:
          const error = {
            type: "reject",
            reason: {
              code: PdfErrorCode.NotSupport,
              message: `engine method ${name} is not supported`
            }
          };
          const response = {
            id: request.id,
            type: "ExecuteResponse",
            data: {
              type: "error",
              value: error
            }
          };
          this.respond(response);
          return;
      }
      task.onProgress((progress) => {
        const response = {
          id: request.id,
          type: "ExecuteProgress",
          data: progress
        };
        this.respond(response);
      });
      task.wait(
        (result) => {
          const response = {
            id: request.id,
            type: "ExecuteResponse",
            data: {
              type: "result",
              value: result
            }
          };
          this.respond(response);
        },
        (error) => {
          const response = {
            id: request.id,
            type: "ExecuteResponse",
            data: {
              type: "error",
              value: error
            }
          };
          this.respond(response);
        }
      );
    };
  }
  /**
   * Listening on post message
   */
  listen() {
    self.onmessage = (evt) => {
      return this.handle(evt);
    };
  }
  /**
   * Handle post message
   */
  handle(evt) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "webworker receive message event: ", evt.data);
    try {
      const request = evt.data;
      switch (request.type) {
        case "ExecuteRequest":
          this.execute(request);
          break;
      }
    } catch (e2) {
      this.logger.info(
        LOG_SOURCE,
        LOG_CATEGORY,
        "webworker met error when processing message event:",
        e2
      );
    }
  }
  /**
   * Send the ready response when pdf engine is ready
   * @returns
   *
   * @protected
   */
  ready() {
    this.listen();
    this.respond({
      id: "0",
      type: "ReadyResponse"
    });
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "runner is ready");
  }
  /**
   * Send back the response
   * @param response - response that needs sent back
   *
   * @protected
   */
  respond(response) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "runner respond: ", response);
    self.postMessage(response);
  }
}
export {
  B as BitmapFormat,
  DEFAULT_PDFIUM_WASM_URL,
  EngineRunner,
  FONT_CDN_URLS,
  FontCharset,
  F as FontFallbackManager,
  I as ImageConverterError,
  P2 as PdfEngine,
  P as PdfiumErrorCode,
  a as PdfiumNative,
  R as RenderFlag,
  WebWorkerEngine,
  WorkerTask,
  b2 as browserImageDataToBlobConverter,
  cdnFontConfig,
  c as computeFormDrawParams,
  createCdnFontConfig,
  c2 as createHybridImageConverter,
  b as createNodeFontLoader,
  d as createPdfiumDirectEngine,
  createPdfiumEngine as createPdfiumWorkerEngine,
  a2 as createWorkerPoolImageConverter,
  i as isValidCustomKey,
  r as readArrayBuffer,
  e as readString
};
//# sourceMappingURL=index.js.map
