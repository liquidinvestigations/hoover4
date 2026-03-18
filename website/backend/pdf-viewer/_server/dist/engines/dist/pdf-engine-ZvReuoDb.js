import { NoopLogger, Task, PdfEngineOperation, PdfErrorCode, CompoundTask } from "@embedpdf/models";
const LOG_SOURCE$1 = "TaskQueue";
const LOG_CATEGORY$1 = "Queue";
var Priority = /* @__PURE__ */ ((Priority2) => {
  Priority2[Priority2["CRITICAL"] = 3] = "CRITICAL";
  Priority2[Priority2["HIGH"] = 2] = "HIGH";
  Priority2[Priority2["MEDIUM"] = 1] = "MEDIUM";
  Priority2[Priority2["LOW"] = 0] = "LOW";
  return Priority2;
})(Priority || {});
class WorkerTaskQueue {
  constructor(options = {}) {
    this.queue = [];
    this.running = 0;
    this.resultTasks = /* @__PURE__ */ new Map();
    this.idleListeners = /* @__PURE__ */ new Set();
    const {
      concurrency = 1,
      comparator,
      ranker,
      onIdle,
      maxQueueSize,
      autoStart = true,
      logger
    } = options;
    this.logger = logger ?? new NoopLogger();
    this.opts = {
      concurrency: Math.max(1, concurrency),
      comparator,
      ranker,
      onIdle: onIdle ?? (() => {
      }),
      maxQueueSize: maxQueueSize ?? Number.POSITIVE_INFINITY,
      autoStart
    };
  }
  setComparator(comparator) {
    this.opts.comparator = comparator;
  }
  setRanker(ranker) {
    this.opts.ranker = ranker;
  }
  size() {
    return this.queue.length;
  }
  inFlight() {
    return this.running;
  }
  isIdle() {
    return this.queue.length === 0 && this.running === 0;
  }
  async drain() {
    if (this.isIdle()) return;
    await new Promise((resolve) => {
      const check = () => {
        if (this.isIdle()) {
          this.offIdle(check);
          resolve();
        }
      };
      this.onIdle(check);
    });
  }
  notifyIdle() {
    if (this.isIdle()) {
      [...this.idleListeners].forEach((fn) => fn());
      this.idleListeners.clear();
      this.opts.onIdle();
    }
  }
  onIdle(fn) {
    this.idleListeners.add(fn);
  }
  offIdle(fn) {
    this.idleListeners.delete(fn);
  }
  /**
   * Enqueue a task factory - with automatic type inference!
   *
   * The factory function is ONLY called when it's the task's turn to execute.
   *
   * Usage:
   *   const task = queue.enqueue({
   *     execute: () => this.executor.getMetadata(doc),  // Factory - not called yet!
   *     meta: { operation: 'getMetadata' }
   *   }, { priority: Priority.LOW });
   *
   * The returned task has the SAME type as executor.getMetadata() would return!
   */
  enqueue(taskDef, options = {}) {
    const id = this.generateId();
    const priority = options.priority ?? 1;
    const resultTask = new Task();
    if (this.queue.length >= this.opts.maxQueueSize) {
      const error = new Error("Queue is full (maxQueueSize reached).");
      resultTask.reject(error);
      return resultTask;
    }
    this.resultTasks.set(id, resultTask);
    const queuedTask = {
      id,
      priority,
      meta: options.meta ?? taskDef.meta,
      executeFactory: taskDef.execute
      // Store factory, don't call it yet!
    };
    this.queue.push(queuedTask);
    this.logger.debug(
      LOG_SOURCE$1,
      LOG_CATEGORY$1,
      `Task enqueued: ${id} | Priority: ${priority} | Running: ${this.running} | Queued: ${this.queue.length}`
    );
    const originalAbort = resultTask.abort.bind(resultTask);
    resultTask.abort = (reason) => {
      this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, `Task aborted: ${id}`);
      this.cancel(id);
      originalAbort(reason);
    };
    if (this.opts.autoStart) this.process(options.fifo === true);
    return resultTask;
  }
  /**
   * Cancel/remove a task from the queue
   */
  cancel(taskId) {
    const before = this.queue.length;
    this.queue = this.queue.filter((t) => {
      if (t.id === taskId) {
        t.cancelled = true;
        return false;
      }
      return true;
    });
    this.resultTasks.delete(taskId);
    if (before !== this.queue.length) {
      this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, `Task cancelled and removed: ${taskId}`);
      this.kick();
    }
  }
  kick() {
    queueMicrotask(() => this.process());
  }
  async process(fifo = false) {
    this.logger.debug(
      LOG_SOURCE$1,
      LOG_CATEGORY$1,
      `process() called | Running: ${this.running} | Concurrency: ${this.opts.concurrency} | Queued: ${this.queue.length}`
    );
    while (this.running < this.opts.concurrency && this.queue.length > 0) {
      this.logger.debug(
        LOG_SOURCE$1,
        LOG_CATEGORY$1,
        `Starting new task | Running: ${this.running} | Queued: ${this.queue.length}`
      );
      if (!fifo) this.sortQueue();
      const queuedTask = this.queue.shift();
      if (queuedTask.cancelled) {
        this.logger.debug(LOG_SOURCE$1, LOG_CATEGORY$1, `Skipping cancelled task: ${queuedTask.id}`);
        continue;
      }
      const resultTask = this.resultTasks.get(queuedTask.id);
      if (!resultTask) continue;
      this.running++;
      (async () => {
        let realTask = null;
        try {
          realTask = queuedTask.executeFactory();
          if (!realTask) {
            throw new Error("Task factory returned null/undefined");
          }
          realTask.wait(
            (result) => {
              if (resultTask.state.stage === 0) {
                resultTask.resolve(result);
              }
            },
            (error) => {
              if (resultTask.state.stage === 0) {
                if (error.type === "abort") {
                  resultTask.abort(error.reason);
                } else {
                  resultTask.reject(error.reason);
                }
              }
            }
          );
          realTask.onProgress((progress) => {
            resultTask.progress(progress);
          });
          await realTask.toPromise();
        } catch (error) {
          if (resultTask.state.stage === 0) {
            resultTask.reject(error);
          }
        } finally {
          this.resultTasks.delete(queuedTask.id);
          this.running--;
          this.logger.debug(
            LOG_SOURCE$1,
            LOG_CATEGORY$1,
            `Task completed: ${queuedTask.id} | Running: ${this.running} | Queued: ${this.queue.length}`
          );
          if (this.isIdle()) {
            this.notifyIdle();
          } else if (this.queue.length > 0) {
            this.kick();
          }
        }
      })().catch((error) => {
        this.logger.error(
          LOG_SOURCE$1,
          LOG_CATEGORY$1,
          "Unhandled error in task execution wrapper:",
          error
        );
        this.running = Math.max(0, this.running - 1);
        if (this.isIdle()) {
          this.notifyIdle();
        } else if (this.queue.length > 0) {
          this.kick();
        }
      });
    }
  }
  sortQueue() {
    const { comparator, ranker } = this.opts;
    if (comparator) {
      this.queue.sort(comparator);
      return;
    }
    const rankCache = /* @__PURE__ */ new Map();
    const getRank = (t) => {
      if (!ranker) return this.defaultRank(t);
      if (!rankCache.has(t.id)) rankCache.set(t.id, ranker(t));
      return rankCache.get(t.id);
    };
    this.queue.sort((a, b) => {
      if (a.priority !== b.priority) return b.priority - a.priority;
      const ar = getRank(a);
      const br = getRank(b);
      if (ar !== br) return br - ar;
      return this.extractTime(a.id) - this.extractTime(b.id);
    });
  }
  defaultRank(_task) {
    return 0;
  }
  generateId() {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
  extractTime(id) {
    const t = Number(id.split("-")[0]);
    return Number.isFinite(t) ? t : 0;
  }
}
const LOG_SOURCE = "PdfEngine";
const LOG_CATEGORY = "Orchestrator";
class PdfEngine {
  constructor(executor, options) {
    this.executor = executor;
    this.logger = options.logger ?? new NoopLogger();
    this.options = {
      imageConverter: options.imageConverter,
      fetcher: options.fetcher ?? (typeof fetch !== "undefined" ? (url, init) => fetch(url, init) : void 0),
      logger: this.logger
    };
    this.workerQueue = new WorkerTaskQueue({
      concurrency: 1,
      autoStart: true,
      logger: this.logger
    });
    this.logger.debug(LOG_SOURCE, LOG_CATEGORY, "PdfEngine orchestrator created");
  }
  /**
   * Split an array into chunks of a given size
   */
  chunkArray(items, chunkSize) {
    const chunks = [];
    for (let i = 0; i < items.length; i += chunkSize) {
      chunks.push(items.slice(i, i + chunkSize));
    }
    return chunks;
  }
  // ========== IPdfEngine Implementation ==========
  isSupport(feature) {
    const task = new Task();
    task.resolve([
      PdfEngineOperation.Create,
      PdfEngineOperation.Read,
      PdfEngineOperation.Update,
      PdfEngineOperation.Delete
    ]);
    return task;
  }
  destroy() {
    var _a, _b;
    const task = new Task();
    try {
      this.executor.destroy();
      (_b = (_a = this.options.imageConverter).destroy) == null ? void 0 : _b.call(_a);
      task.resolve(true);
    } catch (error) {
      task.reject({ code: PdfErrorCode.Unknown, message: String(error) });
    }
    return task;
  }
  openDocumentUrl(file, options) {
    const task = new Task();
    (async () => {
      try {
        if (!this.options.fetcher) {
          throw new Error("Fetcher is not set");
        }
        const response = await this.options.fetcher(file.url, options == null ? void 0 : options.requestOptions);
        const arrayBuf = await response.arrayBuffer();
        const pdfFile = {
          id: file.id,
          content: arrayBuf
        };
        this.openDocumentBuffer(pdfFile, {
          password: options == null ? void 0 : options.password,
          normalizeRotation: options == null ? void 0 : options.normalizeRotation
        }).wait(
          (doc) => task.resolve(doc),
          (error) => task.fail(error)
        );
      } catch (error) {
        task.reject({ code: PdfErrorCode.Unknown, message: String(error) });
      }
    })();
    return task;
  }
  openDocumentBuffer(file, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.openDocumentBuffer(file, options),
        meta: { docId: file.id, operation: "openDocumentBuffer" }
      },
      { priority: Priority.CRITICAL }
    );
  }
  getMetadata(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getMetadata(doc),
        meta: { docId: doc.id, operation: "getMetadata" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  setMetadata(doc, metadata) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.setMetadata(doc, metadata),
        meta: { docId: doc.id, operation: "setMetadata" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getDocPermissions(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getDocPermissions(doc),
        meta: { docId: doc.id, operation: "getDocPermissions" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getDocUserPermissions(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getDocUserPermissions(doc),
        meta: { docId: doc.id, operation: "getDocUserPermissions" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getSignatures(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getSignatures(doc),
        meta: { docId: doc.id, operation: "getSignatures" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getBookmarks(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getBookmarks(doc),
        meta: { docId: doc.id, operation: "getBookmarks" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  setBookmarks(doc, bookmarks) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.setBookmarks(doc, bookmarks),
        meta: { docId: doc.id, operation: "setBookmarks" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  deleteBookmarks(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.deleteBookmarks(doc),
        meta: { docId: doc.id, operation: "deleteBookmarks" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  // ========== Rendering with Encoding ==========
  renderPage(doc, page, options) {
    return this.renderWithEncoding(
      () => this.executor.renderPageRaw(doc, page, options),
      options,
      doc.id,
      page.index,
      Priority.CRITICAL
    );
  }
  renderPageRect(doc, page, rect, options) {
    return this.renderWithEncoding(
      () => this.executor.renderPageRect(doc, page, rect, options),
      options,
      doc.id,
      page.index,
      Priority.HIGH
    );
  }
  // ========== Raw Rendering (no encoding) ==========
  renderPageRaw(doc, page, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.renderPageRaw(doc, page, options),
        meta: { docId: doc.id, pageIndex: page.index, operation: "renderPageRaw" }
      },
      { priority: Priority.HIGH }
    );
  }
  renderPageRectRaw(doc, page, rect, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.renderPageRect(doc, page, rect, options),
        meta: { docId: doc.id, pageIndex: page.index, operation: "renderPageRectRaw" }
      },
      { priority: Priority.HIGH }
    );
  }
  renderThumbnail(doc, page, options) {
    return this.renderWithEncoding(
      () => this.executor.renderThumbnailRaw(doc, page, options),
      options,
      doc.id,
      page.index,
      Priority.MEDIUM
    );
  }
  renderPageAnnotation(doc, page, annotation, options) {
    return this.renderWithEncoding(
      () => this.executor.renderPageAnnotationRaw(doc, page, annotation, options),
      options,
      doc.id,
      page.index,
      Priority.MEDIUM
    );
  }
  renderPageAnnotations(doc, page, options) {
    const resultTask = new Task();
    const renderHandle = this.workerQueue.enqueue(
      {
        execute: () => this.executor.renderPageAnnotationsRaw(doc, page, options),
        meta: { docId: doc.id, pageIndex: page.index, operation: "renderPageAnnotationsRaw" }
      },
      { priority: Priority.MEDIUM }
    );
    const originalAbort = resultTask.abort.bind(resultTask);
    resultTask.abort = (reason) => {
      renderHandle.abort(reason);
      originalAbort(reason);
    };
    renderHandle.wait(
      (rawMap) => {
        if (resultTask.state.stage !== 0) {
          return;
        }
        this.encodeAppearanceMap(rawMap, options, resultTask);
      },
      (error) => {
        if (resultTask.state.stage === 0) {
          resultTask.fail(error);
        }
      }
    );
    return resultTask;
  }
  renderPageAnnotationsRaw(doc, page, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.renderPageAnnotationsRaw(doc, page, options),
        meta: { docId: doc.id, pageIndex: page.index, operation: "renderPageAnnotationsRaw" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  /**
   * Helper to render and encode in two stages with priority queue
   */
  renderWithEncoding(renderFn, options, docId, pageIndex, priority = Priority.CRITICAL) {
    const resultTask = new Task();
    const renderHandle = this.workerQueue.enqueue(
      {
        execute: () => renderFn(),
        meta: { docId, pageIndex, operation: "render" }
      },
      { priority }
    );
    const originalAbort = resultTask.abort.bind(resultTask);
    resultTask.abort = (reason) => {
      renderHandle.abort(reason);
      originalAbort(reason);
    };
    renderHandle.wait(
      (rawImageData) => {
        if (resultTask.state.stage !== 0) {
          return;
        }
        this.encodeImage(rawImageData, options, resultTask);
      },
      (error) => {
        if (resultTask.state.stage === 0) {
          resultTask.fail(error);
        }
      }
    );
    return resultTask;
  }
  /**
   * Encode image using encoder pool or inline
   */
  encodeImage(rawImageData, options, resultTask) {
    const imageType = (options == null ? void 0 : options.imageType) ?? "image/webp";
    const quality = options == null ? void 0 : options.quality;
    const plainImageData = {
      data: new Uint8ClampedArray(rawImageData.data),
      width: rawImageData.width,
      height: rawImageData.height
    };
    this.options.imageConverter(() => plainImageData, imageType, quality).then((result) => resultTask.resolve(result)).catch((error) => resultTask.reject({ code: PdfErrorCode.Unknown, message: String(error) }));
  }
  /**
   * Encode a full annotation appearance map to the output type T.
   */
  encodeAppearanceMap(rawMap, options, resultTask) {
    const imageType = (options == null ? void 0 : options.imageType) ?? "image/webp";
    const quality = options == null ? void 0 : options.imageQuality;
    const convertImage = (rawImageData) => {
      const plainImageData = {
        data: new Uint8ClampedArray(rawImageData.data),
        width: rawImageData.width,
        height: rawImageData.height
      };
      return this.options.imageConverter(() => plainImageData, imageType, quality);
    };
    const jobs = [];
    const encodedMap = {};
    const modes = ["normal", "rollover", "down"];
    for (const [annotationId, appearances] of Object.entries(rawMap)) {
      const encodedAppearances = {};
      encodedMap[annotationId] = encodedAppearances;
      for (const mode of modes) {
        const appearance = appearances[mode];
        if (!appearance) continue;
        jobs.push(
          convertImage(appearance.data).then((encodedData) => {
            encodedAppearances[mode] = {
              data: encodedData,
              rect: appearance.rect
            };
          })
        );
      }
    }
    Promise.all(jobs).then(() => {
      if (resultTask.state.stage === 0) {
        resultTask.resolve(encodedMap);
      }
    }).catch((error) => {
      if (resultTask.state.stage === 0) {
        resultTask.reject({ code: PdfErrorCode.Unknown, message: String(error) });
      }
    });
  }
  // ========== Annotations ==========
  getPageAnnotations(doc, page) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getPageAnnotations(doc, page),
        meta: { docId: doc.id, pageIndex: page.index, operation: "getPageAnnotations" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  createPageAnnotation(doc, page, annotation, context) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.createPageAnnotation(doc, page, annotation, context),
        meta: { docId: doc.id, pageIndex: page.index, operation: "createPageAnnotation" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  updatePageAnnotation(doc, page, annotation, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.updatePageAnnotation(doc, page, annotation, options),
        meta: { docId: doc.id, pageIndex: page.index, operation: "updatePageAnnotation" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  removePageAnnotation(doc, page, annotation) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.removePageAnnotation(doc, page, annotation),
        meta: { docId: doc.id, pageIndex: page.index, operation: "removePageAnnotation" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  /**
   * Get all annotations across all pages
   * Uses batched operations to reduce queue overhead
   */
  getAllAnnotations(doc) {
    const chunks = this.chunkArray(doc.pages, 500);
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      `getAllAnnotations: ${doc.pages.length} pages in ${chunks.length} chunks`
    );
    const compound = new CompoundTask({
      aggregate: (results) => Object.assign({}, ...results)
    });
    chunks.forEach((chunkPages, chunkIndex) => {
      const batchTask = this.workerQueue.enqueue(
        {
          execute: () => this.executor.getAnnotationsBatch(doc, chunkPages),
          meta: { docId: doc.id, operation: "getAnnotationsBatch", chunkSize: chunkPages.length }
        },
        { priority: Priority.LOW }
      );
      batchTask.onProgress((batchProgress) => {
        compound.progress({
          page: batchProgress.pageIndex,
          result: batchProgress.result
        });
      });
      compound.addChild(batchTask, chunkIndex);
    });
    compound.finalize();
    return compound;
  }
  getPageTextRects(doc, page) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getPageTextRects(doc, page),
        meta: { docId: doc.id, pageIndex: page.index, operation: "getPageTextRects" }
      },
      {
        priority: Priority.MEDIUM
      }
    );
  }
  // ========== Search ==========
  /**
   * Search across all pages
   * Uses batched operations to reduce queue overhead
   */
  searchAllPages(doc, keyword, options) {
    const flags = Array.isArray(options == null ? void 0 : options.flags) ? options.flags.reduce((acc, flag) => acc | flag, 0) : (options == null ? void 0 : options.flags) ?? 0;
    const chunks = this.chunkArray(doc.pages, 25);
    this.logger.debug(
      LOG_SOURCE,
      LOG_CATEGORY,
      `searchAllPages: ${doc.pages.length} pages in ${chunks.length} chunks`
    );
    const compound = new CompoundTask({
      aggregate: (results) => {
        const allResults = results.flatMap(
          (batchResult) => Object.values(batchResult).flat()
        );
        return { results: allResults, total: allResults.length };
      }
    });
    chunks.forEach((chunkPages, chunkIndex) => {
      const batchTask = this.workerQueue.enqueue(
        {
          execute: () => this.executor.searchBatch(doc, chunkPages, keyword, flags),
          meta: { docId: doc.id, operation: "searchBatch", chunkSize: chunkPages.length }
        },
        { priority: Priority.LOW }
      );
      batchTask.onProgress((batchProgress) => {
        compound.progress({
          page: batchProgress.pageIndex,
          results: batchProgress.result
        });
      });
      compound.addChild(batchTask, chunkIndex);
    });
    compound.finalize();
    return compound;
  }
  // ========== Attachments ==========
  getAttachments(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getAttachments(doc),
        meta: { docId: doc.id, operation: "getAttachments" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  addAttachment(doc, params) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.addAttachment(doc, params),
        meta: { docId: doc.id, operation: "addAttachment" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  removeAttachment(doc, attachment) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.removeAttachment(doc, attachment),
        meta: { docId: doc.id, operation: "removeAttachment" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  readAttachmentContent(doc, attachment) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.readAttachmentContent(doc, attachment),
        meta: { docId: doc.id, operation: "readAttachmentContent" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  // ========== Forms ==========
  setFormFieldValue(doc, page, annotation, value) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.setFormFieldValue(doc, page, annotation, value),
        meta: { docId: doc.id, pageIndex: page.index, operation: "setFormFieldValue" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  flattenPage(doc, page, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.flattenPage(doc, page, options),
        meta: { docId: doc.id, pageIndex: page.index, operation: "flattenPage" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  // ========== Text Operations ==========
  extractPages(doc, pageIndexes) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.extractPages(doc, pageIndexes),
        meta: { docId: doc.id, pageIndexes, operation: "extractPages" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  extractText(doc, pageIndexes) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.extractText(doc, pageIndexes),
        meta: { docId: doc.id, pageIndexes, operation: "extractText" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  redactTextInRects(doc, page, rects, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.redactTextInRects(doc, page, rects, options),
        meta: { docId: doc.id, pageIndex: page.index, operation: "redactTextInRects" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  applyRedaction(doc, page, annotation) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.applyRedaction(doc, page, annotation),
        meta: { docId: doc.id, pageIndex: page.index, operation: "applyRedaction" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  applyAllRedactions(doc, page) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.applyAllRedactions(doc, page),
        meta: { docId: doc.id, pageIndex: page.index, operation: "applyAllRedactions" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  flattenAnnotation(doc, page, annotation) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.flattenAnnotation(doc, page, annotation),
        meta: { docId: doc.id, pageIndex: page.index, operation: "flattenAnnotation" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getTextSlices(doc, slices) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getTextSlices(doc, slices),
        meta: { docId: doc.id, slices, operation: "getTextSlices" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getPageGlyphs(doc, page) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getPageGlyphs(doc, page),
        meta: { docId: doc.id, pageIndex: page.index, operation: "getPageGlyphs" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getPageGeometry(doc, page) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getPageGeometry(doc, page),
        meta: { docId: doc.id, pageIndex: page.index, operation: "getPageGeometry" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  getPageTextRuns(doc, page) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.getPageTextRuns(doc, page),
        meta: { docId: doc.id, pageIndex: page.index, operation: "getPageTextRuns" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  // ========== Document Operations ==========
  merge(files) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.merge(files),
        meta: { docId: files.map((file) => file.id).join(","), operation: "merge" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  mergePages(mergeConfigs) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.mergePages(mergeConfigs),
        meta: {
          docId: mergeConfigs.map((config) => config.docId).join(","),
          operation: "mergePages"
        }
      },
      { priority: Priority.MEDIUM }
    );
  }
  preparePrintDocument(doc, options) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.preparePrintDocument(doc, options),
        meta: { docId: doc.id, operation: "preparePrintDocument" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  saveAsCopy(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.saveAsCopy(doc),
        meta: { docId: doc.id, operation: "saveAsCopy" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  closeDocument(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.closeDocument(doc),
        meta: { docId: doc.id, operation: "closeDocument" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  closeAllDocuments() {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.closeAllDocuments(),
        meta: { operation: "closeAllDocuments" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.setDocumentEncryption}
   */
  setDocumentEncryption(doc, userPassword, ownerPassword, allowedFlags) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.setDocumentEncryption(doc, userPassword, ownerPassword, allowedFlags),
        meta: { docId: doc.id, operation: "setDocumentEncryption" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.removeEncryption}
   */
  removeEncryption(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.removeEncryption(doc),
        meta: { docId: doc.id, operation: "removeEncryption" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.unlockOwnerPermissions}
   */
  unlockOwnerPermissions(doc, ownerPassword) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.unlockOwnerPermissions(doc, ownerPassword),
        meta: { docId: doc.id, operation: "unlockOwnerPermissions" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.isEncrypted}
   */
  isEncrypted(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.isEncrypted(doc),
        meta: { docId: doc.id, operation: "isEncrypted" }
      },
      { priority: Priority.MEDIUM }
    );
  }
  /**
   * {@inheritDoc @embedpdf/models!PdfEngine.isOwnerUnlocked}
   */
  isOwnerUnlocked(doc) {
    return this.workerQueue.enqueue(
      {
        execute: () => this.executor.isOwnerUnlocked(doc),
        meta: { docId: doc.id, operation: "isOwnerUnlocked" }
      },
      { priority: Priority.MEDIUM }
    );
  }
}
export {
  PdfEngine as P
};
//# sourceMappingURL=pdf-engine-ZvReuoDb.js.map
