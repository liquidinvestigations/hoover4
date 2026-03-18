import { NoopLogger, PdfErrorCode, Task } from "@embedpdf/models";
const LOG_SOURCE = "WebWorkerEngine";
const LOG_CATEGORY = "Engine";
function createRequest(id, name, args) {
  return {
    id,
    type: "ExecuteRequest",
    data: {
      name,
      args
    }
  };
}
class WorkerTask extends Task {
  /**
   * Create a task that bind to web worker with specified message id
   * @param worker - web worker instance
   * @param messageId - id of message
   *
   * @public
   */
  constructor(worker, messageId) {
    super();
    this.worker = worker;
    this.messageId = messageId;
  }
  /**
   * {@inheritDoc @embedpdf/models!Task.abort}
   *
   * @override
   */
  abort(e) {
    super.abort(e);
    this.worker.postMessage({
      id: this.messageId,
      type: "AbortRequest"
    });
  }
  /**
   * {@inheritDoc @embedpdf/models!Task.progress}
   *
   * @override
   */
  progress(p) {
    super.progress(p);
  }
}
const _WebWorkerEngine = class _WebWorkerEngine {
  /**
   * Create an instance of WebWorkerEngine, it will create a worker with
   * specified url.
   * @param worker - webworker instance, this worker needs to contains the running instance of {@link EngineRunner}
   * @param logger - logger instance
   *
   * @public
   */
  constructor(worker, logger = new NoopLogger()) {
    this.worker = worker;
    this.logger = logger;
    this.tasks = /* @__PURE__ */ new Map();
    this.handle = (evt) => {
      this.logger.debug(
        LOG_SOURCE,
        LOG_CATEGORY,
        "webworker engine start handling message: ",
        evt.data
      );
      try {
        const response = evt.data;
        const task = this.tasks.get(response.id);
        if (!task) {
          return;
        }
        switch (response.type) {
          case "ReadyResponse":
            this.readyTask.resolve(true);
            break;
          case "ExecuteProgress":
            task.progress(response.data);
            break;
          case "ExecuteResponse":
            {
              switch (response.data.type) {
                case "result":
                  task.resolve(response.data.value);
                  break;
                case "error":
                  task.reject(response.data.value.reason);
                  break;
              }
              this.tasks.delete(response.id);
            }
            break;
        }
      } catch (e) {
        this.logger.error(LOG_SOURCE, LOG_CATEGORY, "webworker met error when handling message: ", e);
      }
    };
    this.worker.addEventListener("message", this.handle);
    this.readyTask = new WorkerTask(this.worker, _WebWorkerEngine.readyTaskId);
    this.tasks.set(_WebWorkerEngine.readyTaskId, this.readyTask);
  }
  /**
   * Generate a unique message id
   * @returns message id
   *
   * @private
   */
  generateRequestId(id) {
    return `${id}.${Date.now()}.${Math.random()}`;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.destroy}
   *
   * @public
   */
  destroy() {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "destroy");
    const requestId = this.generateRequestId("General");
    const task = new WorkerTask(this.worker, requestId);
    const finish = () => {
      this.worker.removeEventListener("message", this.handle);
      this.worker.terminate();
    };
    task.wait(finish, finish);
    const request = createRequest(requestId, "destroy", []);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.openDocumentUrl}
   *
   * @public
   */
  openDocumentUrl(file, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "openDocumentUrl", file.url, options);
    const requestId = this.generateRequestId(file.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "openDocumentUrl", [file, options]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.openDocument}
   *
   * @public
   */
  openDocumentBuffer(file, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "openDocumentBuffer", file, options);
    const requestId = this.generateRequestId(file.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "openDocumentBuffer", [file, options]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getMetadata}
   *
   * @public
   */
  getMetadata(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getMetadata", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getMetadata", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setMetadata}
   *
   * @public
   */
  setMetadata(doc, metadata) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "setMetadata", doc, metadata);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "setMetadata", [doc, metadata]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getDocPermissions}
   *
   * @public
   */
  getDocPermissions(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getDocPermissions", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getDocPermissions", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getDocUserPermissions}
   *
   * @public
   */
  getDocUserPermissions(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getDocUserPermissions", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getDocUserPermissions", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getBookmarks}
   *
   * @public
   */
  getBookmarks(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getBookmarks", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getBookmarks", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setBookmarks}
   *
   * @public
   */
  setBookmarks(doc, payload) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "setBookmarks", doc, payload);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "setBookmarks", [doc, payload]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.deleteBookmarks}
   *
   * @public
   */
  deleteBookmarks(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "deleteBookmarks", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "deleteBookmarks", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getSignatures}
   *
   * @public
   */
  getSignatures(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getSignatures", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getSignatures", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderPage}
   *
   * @public
   */
  renderPage(doc, page, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPage", doc, page, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderPage", [doc, page, options]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRect}
   *
   * @public
   */
  renderPageRect(doc, page, rect, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPageRect", doc, page, rect, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderPageRect", [
      doc,
      page,
      rect,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRaw}
   *
   * @public
   */
  renderPageRaw(doc, page, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPageRaw", doc, page, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderPageRaw", [doc, page, options]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderPageRectRaw}
   *
   * @public
   */
  renderPageRectRaw(doc, page, rect, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPageRectRaw", doc, page, rect, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderPageRectRaw", [
      doc,
      page,
      rect,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderAnnotation}
   *
   * @public
   */
  renderPageAnnotation(doc, page, annotation, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderAnnotation", doc, page, annotation, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderPageAnnotation", [
      doc,
      page,
      annotation,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  renderPageAnnotations(doc, page, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPageAnnotations", doc, page, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderPageAnnotations", [
      doc,
      page,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  renderPageAnnotationsRaw(doc, page, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderPageAnnotationsRaw", doc, page, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderPageAnnotationsRaw", [
      doc,
      page,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getAllAnnotations}
   *
   * @public
   */
  getAllAnnotations(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getAllAnnotations", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(
      this.worker,
      requestId
    );
    const request = createRequest(requestId, "getAllAnnotations", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getPageAnnotations}
   *
   * @public
   */
  getPageAnnotations(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageAnnotations", doc, page);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getPageAnnotations", [doc, page]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.createPageAnnotation}
   *
   * @public
   */
  createPageAnnotation(doc, page, annotation, context) {
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      "createPageAnnotations",
      doc,
      page,
      annotation,
      context
    );
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "createPageAnnotation", [
      doc,
      page,
      annotation,
      context
    ]);
    this.proxy(task, request);
    return task;
  }
  updatePageAnnotation(doc, page, annotation, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "updatePageAnnotation", doc, page, annotation);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "updatePageAnnotation", [
      doc,
      page,
      annotation,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.removePageAnnotation}
   *
   * @public
   */
  removePageAnnotation(doc, page, annotation) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "removePageAnnotations", doc, page, annotation);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "removePageAnnotation", [
      doc,
      page,
      annotation
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getPageTextRects}
   *
   * @public
   */
  getPageTextRects(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageTextRects", doc, page);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getPageTextRects", [doc, page]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.renderThumbnail}
   *
   * @public
   */
  renderThumbnail(doc, page, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "renderThumbnail", doc, page, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "renderThumbnail", [
      doc,
      page,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.searchAllPages}
   *
   * @public
   */
  searchAllPages(doc, keyword, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "searchAllPages", doc, keyword, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(
      this.worker,
      requestId
    );
    const request = createRequest(requestId, "searchAllPages", [
      doc,
      keyword,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.saveAsCopy}
   *
   * @public
   */
  saveAsCopy(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "saveAsCopy", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "saveAsCopy", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getAttachments}
   *
   * @public
   */
  getAttachments(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getAttachments", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getAttachments", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.addAttachment}
   *
   * @public
   */
  addAttachment(doc, params) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "addAttachment", doc, params);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "addAttachment", [doc, params]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.removeAttachment}
   *
   * @public
   */
  removeAttachment(doc, attachment) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "removeAttachment", doc, attachment);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "removeAttachment", [doc, attachment]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.readAttachmentContent}
   *
   * @public
   */
  readAttachmentContent(doc, attachment) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "readAttachmentContent", doc, attachment);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "readAttachmentContent", [
      doc,
      attachment
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setFormFieldValue}
   *
   * @public
   */
  setFormFieldValue(doc, page, annotation, value) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "setFormFieldValue", doc, annotation, value);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "setFormFieldValue", [
      doc,
      page,
      annotation,
      value
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.flattenPage}
   *
   * @public
   */
  flattenPage(doc, page, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "flattenPage", doc, page, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "flattenPage", [doc, page, options]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.extractPages}
   *
   * @public
   */
  extractPages(doc, pageIndexes) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "extractPages", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "extractPages", [doc, pageIndexes]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.redactTextInQuads}
   *
   * @public
   */
  redactTextInRects(doc, page, rects, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "redactTextInRects", doc, page, rects, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "redactTextInRects", [
      doc,
      page,
      rects,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.applyRedaction}
   *
   * @public
   */
  applyRedaction(doc, page, annotation) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "applyRedaction", doc, page, annotation);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "applyRedaction", [
      doc,
      page,
      annotation
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.applyAllRedactions}
   *
   * @public
   */
  applyAllRedactions(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "applyAllRedactions", doc, page);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "applyAllRedactions", [doc, page]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.flattenAnnotation}
   *
   * @public
   */
  flattenAnnotation(doc, page, annotation) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "flattenAnnotation", doc, page, annotation);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "flattenAnnotation", [
      doc,
      page,
      annotation
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.extractText}
   *
   * @public
   */
  extractText(doc, pageIndexes) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "extractText", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "extractText", [doc, pageIndexes]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getTextSlices}
   *
   * @public
   */
  getTextSlices(doc, slices) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getTextSlices", doc, slices);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getTextSlices", [doc, slices]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getPageGlyphs}
   *
   * @public
   */
  getPageGlyphs(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageGlyphs", doc, page);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getPageGlyphs", [doc, page]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getPageGeometry}
   *
   * @public
   */
  getPageGeometry(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageGeometry", doc, page);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getPageGeometry", [doc, page]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.getPageTextRuns}
   *
   * @public
   */
  getPageTextRuns(doc, page) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "getPageTextRuns", doc, page);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "getPageTextRuns", [doc, page]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.merge}
   *
   * @public
   */
  merge(files) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "merge", files);
    const fileIds = files.map((file) => file.id).join(".");
    const requestId = this.generateRequestId(fileIds);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "merge", [files]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.mergePages}
   *
   * @public
   */
  mergePages(mergeConfigs) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "mergePages", mergeConfigs);
    const requestId = this.generateRequestId(mergeConfigs.map((config) => config.docId).join("."));
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "mergePages", [mergeConfigs]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.preparePrintDocument}
   *
   * @public
   */
  preparePrintDocument(doc, options) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "preparePrintDocument", doc, options);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "preparePrintDocument", [
      doc,
      options
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.closeDocument}
   *
   * @public
   */
  closeDocument(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "closeDocument", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "closeDocument", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.closeAllDocuments}
   *
   * @public
   */
  closeAllDocuments() {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "closeAllDocuments");
    const requestId = this.generateRequestId("closeAllDocuments");
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "closeAllDocuments", []);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setDocumentEncryption}
   *
   * @public
   */
  setDocumentEncryption(doc, userPassword, ownerPassword, allowedFlags) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "setDocumentEncryption", doc, allowedFlags);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "setDocumentEncryption", [
      doc,
      userPassword,
      ownerPassword,
      allowedFlags
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.removeEncryption}
   *
   * @public
   */
  removeEncryption(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "removeEncryption", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "removeEncryption", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.unlockOwnerPermissions}
   *
   * @public
   */
  unlockOwnerPermissions(doc, ownerPassword) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "unlockOwnerPermissions", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "unlockOwnerPermissions", [
      doc,
      ownerPassword
    ]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.isEncrypted}
   *
   * @public
   */
  isEncrypted(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "isEncrypted", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "isEncrypted", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.isOwnerUnlocked}
   *
   * @public
   */
  isOwnerUnlocked(doc) {
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "isOwnerUnlocked", doc);
    const requestId = this.generateRequestId(doc.id);
    const task = new WorkerTask(this.worker, requestId);
    const request = createRequest(requestId, "isOwnerUnlocked", [doc]);
    this.proxy(task, request);
    return task;
  }
  /**
   * Send the request to webworker inside and register the task
   * @param task - task that waiting for the response
   * @param request - request that needs send to web worker
   * @param transferables - transferables that need to transfer to webworker
   * @returns
   *
   * @internal
   */
  proxy(task, request, transferables = []) {
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      "send request to worker",
      task,
      request,
      transferables
    );
    this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `${request.data.name}`, "Begin", request.id);
    this.readyTask.wait(
      () => {
        this.worker.postMessage(request, transferables);
        task.wait(
          () => {
            this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `${request.data.name}`, "End", request.id);
          },
          () => {
            this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `${request.data.name}`, "End", request.id);
          }
        );
        this.tasks.set(request.id, task);
      },
      () => {
        this.logger.perf(LOG_SOURCE, LOG_CATEGORY, `${request.data.name}`, "End", request.id);
        task.reject({
          code: PdfErrorCode.Initialization,
          message: "worker initialization failed"
        });
      }
    );
  }
};
_WebWorkerEngine.readyTaskId = "0";
let WebWorkerEngine = _WebWorkerEngine;
export {
  WebWorkerEngine,
  WorkerTask
};
//# sourceMappingURL=engine.js.map
