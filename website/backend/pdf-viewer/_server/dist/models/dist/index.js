var Rotation = /* @__PURE__ */ ((Rotation2) => {
  Rotation2[Rotation2["Degree0"] = 0] = "Degree0";
  Rotation2[Rotation2["Degree90"] = 1] = "Degree90";
  Rotation2[Rotation2["Degree180"] = 2] = "Degree180";
  Rotation2[Rotation2["Degree270"] = 3] = "Degree270";
  return Rotation2;
})(Rotation || {});
function toIntPos(p) {
  return { x: Math.floor(p.x), y: Math.floor(p.y) };
}
function toIntSize(s) {
  return { width: Math.ceil(s.width), height: Math.ceil(s.height) };
}
function toIntRect(r) {
  return {
    origin: toIntPos(r.origin),
    size: toIntSize(r.size)
  };
}
function calculateDegree(rotation) {
  switch (rotation) {
    case 0:
      return 0;
    case 1:
      return 90;
    case 2:
      return 180;
    case 3:
      return 270;
  }
}
function calculateAngle(rotation) {
  return calculateDegree(rotation) * Math.PI / 180;
}
function swap(size) {
  const { width, height } = size;
  return {
    width: height,
    height: width
  };
}
function transformSize(size, rotation, scaleFactor) {
  size = rotation % 2 === 0 ? size : swap(size);
  return {
    width: size.width * scaleFactor,
    height: size.height * scaleFactor
  };
}
function quadToRect(q) {
  const xs = [q.p1.x, q.p2.x, q.p3.x, q.p4.x];
  const ys = [q.p1.y, q.p2.y, q.p3.y, q.p4.y];
  return {
    origin: { x: Math.min(...xs), y: Math.min(...ys) },
    size: {
      width: Math.max(...xs) - Math.min(...xs),
      height: Math.max(...ys) - Math.min(...ys)
    }
  };
}
function rectToQuad(r) {
  return {
    p1: { x: r.origin.x, y: r.origin.y },
    p2: { x: r.origin.x + r.size.width, y: r.origin.y },
    p3: { x: r.origin.x + r.size.width, y: r.origin.y + r.size.height },
    p4: { x: r.origin.x, y: r.origin.y + r.size.height }
  };
}
function rotatePosition(containerSize, position, rotation) {
  let x = position.x;
  let y = position.y;
  switch (rotation) {
    case 0:
      x = position.x;
      y = position.y;
      break;
    case 1:
      x = containerSize.height - position.y;
      y = position.x;
      break;
    case 2:
      x = containerSize.width - position.x;
      y = containerSize.height - position.y;
      break;
    case 3:
      x = position.y;
      y = containerSize.width - position.x;
      break;
  }
  return {
    x,
    y
  };
}
function scalePosition(position, scaleFactor) {
  return {
    x: position.x * scaleFactor,
    y: position.y * scaleFactor
  };
}
function transformPosition(containerSize, position, rotation, scaleFactor) {
  return scalePosition(rotatePosition(containerSize, position, rotation), scaleFactor);
}
function restorePosition(containerSize, position, rotation, scaleFactor) {
  return scalePosition(
    rotatePosition(containerSize, position, (4 - rotation) % 4),
    1 / scaleFactor
  );
}
function rectEquals(a, b) {
  return a.origin.x === b.origin.x && a.origin.y === b.origin.y && a.size.width === b.size.width && a.size.height === b.size.height;
}
function rectFromPoints(positions) {
  if (positions.length === 0) {
    return { origin: { x: 0, y: 0 }, size: { width: 0, height: 0 } };
  }
  const xs = positions.map((p) => p.x);
  const ys = positions.map((p) => p.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  return {
    origin: { x: minX, y: minY },
    size: {
      width: Math.max(...xs) - minX,
      height: Math.max(...ys) - minY
    }
  };
}
function rotateAndTranslatePoint(pos, angleRad, translate) {
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);
  const newX = pos.x * cos - pos.y * sin;
  const newY = pos.x * sin + pos.y * cos;
  return {
    x: newX + translate.x,
    y: newY + translate.y
  };
}
function expandRect(rect, padding) {
  return {
    origin: { x: rect.origin.x - padding, y: rect.origin.y - padding },
    size: { width: rect.size.width + padding * 2, height: rect.size.height + padding * 2 }
  };
}
function rotateRect(containerSize, rect, rotation) {
  let x = rect.origin.x;
  let y = rect.origin.y;
  let size = rect.size;
  switch (rotation) {
    case 0:
      break;
    case 1:
      x = containerSize.height - rect.origin.y - rect.size.height;
      y = rect.origin.x;
      size = swap(rect.size);
      break;
    case 2:
      x = containerSize.width - rect.origin.x - rect.size.width;
      y = containerSize.height - rect.origin.y - rect.size.height;
      break;
    case 3:
      x = rect.origin.y;
      y = containerSize.width - rect.origin.x - rect.size.width;
      size = swap(rect.size);
      break;
  }
  return {
    origin: {
      x,
      y
    },
    size: {
      width: size.width,
      height: size.height
    }
  };
}
function scaleRect(rect, scaleFactor) {
  return {
    origin: {
      x: rect.origin.x * scaleFactor,
      y: rect.origin.y * scaleFactor
    },
    size: {
      width: rect.size.width * scaleFactor,
      height: rect.size.height * scaleFactor
    }
  };
}
function transformRect(containerSize, rect, rotation, scaleFactor) {
  return scaleRect(rotateRect(containerSize, rect, rotation), scaleFactor);
}
function restoreRect(containerSize, rect, rotation, scaleFactor) {
  return scaleRect(rotateRect(containerSize, rect, (4 - rotation) % 4), 1 / scaleFactor);
}
function restoreOffset(offset, rotation, scaleFactor) {
  let offsetX = offset.x;
  let offsetY = offset.y;
  switch (rotation) {
    case 0:
      offsetX = offset.x / scaleFactor;
      offsetY = offset.y / scaleFactor;
      break;
    case 1:
      offsetX = offset.y / scaleFactor;
      offsetY = -offset.x / scaleFactor;
      break;
    case 2:
      offsetX = -offset.x / scaleFactor;
      offsetY = -offset.y / scaleFactor;
      break;
    case 3:
      offsetX = -offset.y / scaleFactor;
      offsetY = offset.x / scaleFactor;
      break;
  }
  return {
    x: offsetX,
    y: offsetY
  };
}
const EMPTY_RECT = { origin: { x: 0, y: 0 }, size: { width: 0, height: 0 } };
function boundingRect(rects) {
  if (rects.length === 0) return null;
  let minX = rects[0].origin.x, minY = rects[0].origin.y, maxX = rects[0].origin.x + rects[0].size.width, maxY = rects[0].origin.y + rects[0].size.height;
  for (const r of rects) {
    minX = Math.min(minX, r.origin.x);
    minY = Math.min(minY, r.origin.y);
    maxX = Math.max(maxX, r.origin.x + r.size.width);
    maxY = Math.max(maxY, r.origin.y + r.size.height);
  }
  return {
    origin: {
      x: minX,
      y: minY
    },
    size: {
      width: maxX - minX,
      height: maxY - minY
    }
  };
}
function boundingRectOrEmpty(rects) {
  return boundingRect(rects) ?? EMPTY_RECT;
}
function normalizeAngle(degrees) {
  const normalized = degrees % 360;
  return normalized < 0 ? normalized + 360 : normalized;
}
function getRectCenter(rect) {
  return {
    x: rect.origin.x + rect.size.width / 2,
    y: rect.origin.y + rect.size.height / 2
  };
}
function rotatePointAround(point, center, angleDegrees) {
  const angleRad = angleDegrees * Math.PI / 180;
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);
  const dx = point.x - center.x;
  const dy = point.y - center.y;
  return {
    x: center.x + dx * cos - dy * sin,
    y: center.y + dx * sin + dy * cos
  };
}
function rotateVertices(points, center, angleDegrees) {
  return points.map((v) => rotatePointAround(v, center, angleDegrees));
}
function calculateRotatedRectAABBAroundPoint(rect, angleDegrees, center) {
  const corners = [
    { x: rect.origin.x, y: rect.origin.y },
    { x: rect.origin.x + rect.size.width, y: rect.origin.y },
    { x: rect.origin.x + rect.size.width, y: rect.origin.y + rect.size.height },
    { x: rect.origin.x, y: rect.origin.y + rect.size.height }
  ];
  const rotated = rotateVertices(corners, center, angleDegrees);
  return rectFromPoints(rotated);
}
function calculateRotatedRectAABB(unrotatedRect, angleDegrees) {
  return calculateRotatedRectAABBAroundPoint(
    unrotatedRect,
    angleDegrees,
    getRectCenter(unrotatedRect)
  );
}
function inferRotationCenterFromRects(unrotatedRect, rotatedAabb, angleDegrees) {
  const angleRad = angleDegrees * Math.PI / 180;
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);
  const m00 = 1 - cos;
  const m01 = sin;
  const m10 = -sin;
  const m11 = 1 - cos;
  const det = m00 * m11 - m01 * m10;
  const unrotatedCenter = getRectCenter(unrotatedRect);
  if (Math.abs(det) < 1e-10) return unrotatedCenter;
  const rotatedCenter = getRectCenter(rotatedAabb);
  const rhsX = rotatedCenter.x - (cos * unrotatedCenter.x - sin * unrotatedCenter.y);
  const rhsY = rotatedCenter.y - (sin * unrotatedCenter.x + cos * unrotatedCenter.y);
  return {
    x: (m11 * rhsX - m01 * rhsY) / det,
    y: (-m10 * rhsX + m00 * rhsY) / det
  };
}
function buildUserToDeviceMatrix(rect, rotation, outW, outH) {
  const L = rect.origin.x;
  const B = rect.origin.y;
  const W = rect.size.width;
  const H = rect.size.height;
  const sx0 = outW / W;
  const sy0 = outH / H;
  const sx90 = outW / H;
  const sy90 = outH / W;
  switch (rotation) {
    case 0:
      return { a: sx0, b: 0, c: 0, d: sy0, e: -sx0 * L, f: -sy0 * B };
    case 3:
      return { a: 0, b: -sy90, c: sx90, d: 0, e: -sx90 * B, f: sy90 * (L + W) };
    case 2:
      return { a: -sx0, b: 0, c: 0, d: -sy0, e: sx0 * (L + W), f: sy0 * (B + H) };
    case 1:
      return { a: 0, b: sy90, c: -sx90, d: 0, e: sx90 * (B + H), f: -sy90 * L };
  }
}
class NoopLogger {
  /** {@inheritDoc Logger.isEnabled} */
  isEnabled() {
    return false;
  }
  /** {@inheritDoc Logger.debug} */
  debug() {
  }
  /** {@inheritDoc Logger.info} */
  info() {
  }
  /** {@inheritDoc Logger.warn} */
  warn() {
  }
  /** {@inheritDoc Logger.error} */
  error() {
  }
  /** {@inheritDoc Logger.perf} */
  perf() {
  }
}
class ConsoleLogger {
  /** {@inheritDoc Logger.isEnabled} */
  isEnabled() {
    return true;
  }
  /** {@inheritDoc Logger.debug} */
  debug(source, category, ...args) {
    console.debug(`${source}.${category}`, ...args);
  }
  /** {@inheritDoc Logger.info} */
  info(source, category, ...args) {
    console.info(`${source}.${category}`, ...args);
  }
  /** {@inheritDoc Logger.warn} */
  warn(source, category, ...args) {
    console.warn(`${source}.${category}`, ...args);
  }
  /** {@inheritDoc Logger.error} */
  error(source, category, ...args) {
    console.error(`${source}.${category}`, ...args);
  }
  /** {@inheritDoc Logger.perf} */
  perf(source, category, event, phase, ...args) {
    console.info(`${source}.${category}.${event}.${phase}`, ...args);
  }
}
var LogLevel = /* @__PURE__ */ ((LogLevel2) => {
  LogLevel2[LogLevel2["Debug"] = 0] = "Debug";
  LogLevel2[LogLevel2["Info"] = 1] = "Info";
  LogLevel2[LogLevel2["Warn"] = 2] = "Warn";
  LogLevel2[LogLevel2["Error"] = 3] = "Error";
  return LogLevel2;
})(LogLevel || {});
class LevelLogger {
  /**
   * create new LevelLogger
   * @param logger - the original logger
   * @param level - log level that used for filtering, all logs lower than this level will be filtered out
   */
  constructor(logger, level) {
    this.logger = logger;
    this.level = level;
  }
  /** {@inheritDoc Logger.isEnabled} */
  isEnabled(level) {
    const levelMap = {
      debug: 0,
      info: 1,
      warn: 2,
      error: 3
      /* Error */
    };
    return this.level <= levelMap[level];
  }
  /** {@inheritDoc Logger.debug} */
  debug(source, category, ...args) {
    if (this.level <= 0) {
      this.logger.debug(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.info} */
  info(source, category, ...args) {
    if (this.level <= 1) {
      this.logger.info(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.warn} */
  warn(source, category, ...args) {
    if (this.level <= 2) {
      this.logger.warn(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.error} */
  error(source, category, ...args) {
    if (this.level <= 3) {
      this.logger.error(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.perf} */
  perf(source, category, event, phase, ...args) {
    this.logger.perf(source, category, event, phase, ...args);
  }
}
class PerfLogger {
  /**
   * create new PerfLogger
   */
  constructor() {
    this.marks = /* @__PURE__ */ new Map();
  }
  /** {@inheritDoc Logger.isEnabled} */
  isEnabled() {
    return false;
  }
  /** {@inheritDoc Logger.debug} */
  debug(source, category, ...args) {
  }
  /** {@inheritDoc Logger.info} */
  info(source, category, ...args) {
  }
  /** {@inheritDoc Logger.warn} */
  warn(source, category, ...args) {
  }
  /** {@inheritDoc Logger.error} */
  error(source, category, ...args) {
  }
  /** {@inheritDoc Logger.perf} */
  perf(source, category, event, phase, identifier, ...args) {
    const markName = `${source}.${category}.${event}.${phase}.${identifier}`;
    switch (phase) {
      case "Begin":
        globalThis.performance.mark(markName, { detail: args });
        this.marks.set(`${source}.${category}.${event}.${identifier}`, Date.now());
        break;
      case "End":
        globalThis.performance.mark(markName, { detail: args });
        const measureName = `${source}.${category}.${event}.Measure.${identifier}`;
        const beginMark = `${source}.${category}.${event}.Begin.${identifier}`;
        globalThis.performance.measure(measureName, beginMark, markName);
        const startTime = this.marks.get(`${source}.${category}.${event}.${identifier}`);
        if (startTime) {
          const duration = Date.now() - startTime;
          console.info(`⏱️ ${source}.${category}.${event}.${identifier}: ${duration}ms`);
          this.marks.delete(`${source}.${category}.${event}.${identifier}`);
        }
        break;
    }
  }
}
class AllLogger {
  /**
   * create new PerfLogger
   */
  constructor(loggers) {
    this.loggers = loggers;
  }
  /** {@inheritDoc Logger.isEnabled} */
  isEnabled(level) {
    return this.loggers.some((logger) => logger.isEnabled(level));
  }
  /** {@inheritDoc Logger.debug} */
  debug(source, category, ...args) {
    for (const logger of this.loggers) {
      logger.debug(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.info} */
  info(source, category, ...args) {
    for (const logger of this.loggers) {
      logger.info(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.warn} */
  warn(source, category, ...args) {
    for (const logger of this.loggers) {
      logger.warn(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.error} */
  error(source, category, ...args) {
    for (const logger of this.loggers) {
      logger.error(source, category, ...args);
    }
  }
  /** {@inheritDoc Logger.perf} */
  perf(source, category, event, phase, ...args) {
    for (const logger of this.loggers) {
      logger.perf(source, category, event, phase, ...args);
    }
  }
}
var TaskStage = /* @__PURE__ */ ((TaskStage2) => {
  TaskStage2[TaskStage2["Pending"] = 0] = "Pending";
  TaskStage2[TaskStage2["Resolved"] = 1] = "Resolved";
  TaskStage2[TaskStage2["Rejected"] = 2] = "Rejected";
  TaskStage2[TaskStage2["Aborted"] = 3] = "Aborted";
  return TaskStage2;
})(TaskStage || {});
class TaskAbortedError extends Error {
  constructor(reason) {
    super(`Task aborted: ${JSON.stringify(reason)}`);
    this.name = "TaskAbortedError";
    this.reason = reason;
  }
}
class TaskRejectedError extends Error {
  constructor(reason) {
    super(`Task rejected: ${JSON.stringify(reason)}`);
    this.name = "TaskRejectedError";
    this.reason = reason;
  }
}
class Task {
  constructor() {
    this.state = {
      stage: 0
      /* Pending */
    };
    this.resolvedCallbacks = [];
    this.rejectedCallbacks = [];
    this._promise = null;
    this.progressCbs = [];
  }
  /**
   * Convert task to promise
   * @returns promise that will be resolved when task is settled
   */
  toPromise() {
    if (!this._promise) {
      this._promise = new Promise((resolve, reject) => {
        this.wait(
          (result) => resolve(result),
          (error) => {
            if (error.type === "abort") {
              reject(new TaskAbortedError(error.reason));
            } else {
              reject(new TaskRejectedError(error.reason));
            }
          }
        );
      });
    }
    return this._promise;
  }
  /**
   * wait for task to be settled
   * @param resolvedCallback - callback for resolved value
   * @param rejectedCallback - callback for rejected value
   */
  wait(resolvedCallback, rejectedCallback) {
    switch (this.state.stage) {
      case 0:
        this.resolvedCallbacks.push(resolvedCallback);
        this.rejectedCallbacks.push(rejectedCallback);
        break;
      case 1:
        resolvedCallback(this.state.result);
        break;
      case 2:
        rejectedCallback({
          type: "reject",
          reason: this.state.reason
        });
        break;
      case 3:
        rejectedCallback({
          type: "abort",
          reason: this.state.reason
        });
        break;
    }
  }
  /**
   * resolve task with specific result
   * @param result - result value
   */
  resolve(result) {
    if (this.state.stage === 0) {
      this.state = {
        stage: 1,
        result
      };
      for (const resolvedCallback of this.resolvedCallbacks) {
        try {
          resolvedCallback(result);
        } catch (e) {
        }
      }
      this.resolvedCallbacks = [];
      this.rejectedCallbacks = [];
    }
  }
  /**
   * reject task with specific reason
   * @param reason - abort reason
   *
   */
  reject(reason) {
    if (this.state.stage === 0) {
      this.state = {
        stage: 2,
        reason
      };
      for (const rejectedCallback of this.rejectedCallbacks) {
        try {
          rejectedCallback({
            type: "reject",
            reason
          });
        } catch (e) {
        }
      }
      this.resolvedCallbacks = [];
      this.rejectedCallbacks = [];
    }
  }
  /**
   * abort task with specific reason
   * @param reason - abort reason
   */
  abort(reason) {
    if (this.state.stage === 0) {
      this.state = {
        stage: 3,
        reason
      };
      for (const rejectedCallback of this.rejectedCallbacks) {
        try {
          rejectedCallback({
            type: "abort",
            reason
          });
        } catch (e) {
        }
      }
      this.resolvedCallbacks = [];
      this.rejectedCallbacks = [];
    }
  }
  /**
   * fail task with a TaskError from another task
   * This is a convenience method for error propagation between tasks
   * @param error - TaskError from another task
   */
  fail(error) {
    if (error.type === "abort") {
      this.abort(error.reason);
    } else {
      this.reject(error.reason);
    }
  }
  /**
   * add a progress callback
   * @param cb - progress callback
   */
  onProgress(cb) {
    this.progressCbs.push(cb);
  }
  /**
   * call progress callback
   * @param p - progress value
   */
  progress(p) {
    for (const cb of this.progressCbs) cb(p);
  }
  /**
   * Static method to wait for all tasks to resolve
   * Returns a new task that resolves with an array of all results
   * Rejects immediately if any task fails
   *
   * @param tasks - array of tasks to wait for
   * @returns new task that resolves when all input tasks resolve
   * @public
   */
  static all(tasks) {
    const combinedTask = new Task();
    if (tasks.length === 0) {
      combinedTask.resolve([]);
      return combinedTask;
    }
    const results = new Array(tasks.length);
    let resolvedCount = 0;
    let isSettled = false;
    tasks.forEach((task, index) => {
      task.wait(
        (result) => {
          if (isSettled) return;
          results[index] = result;
          resolvedCount++;
          if (resolvedCount === tasks.length) {
            isSettled = true;
            combinedTask.resolve(results);
          }
        },
        (error) => {
          if (isSettled) return;
          isSettled = true;
          if (error.type === "abort") {
            combinedTask.abort(error.reason);
          } else {
            combinedTask.reject(error.reason);
          }
        }
      );
    });
    return combinedTask;
  }
  /**
   * Static method to wait for all tasks to settle (resolve, reject, or abort)
   * Always resolves with an array of settlement results
   *
   * @param tasks - array of tasks to wait for
   * @returns new task that resolves when all input tasks settle
   * @public
   */
  static allSettled(tasks) {
    const combinedTask = new Task();
    if (tasks.length === 0) {
      combinedTask.resolve([]);
      return combinedTask;
    }
    const results = new Array(tasks.length);
    let settledCount = 0;
    tasks.forEach((task, index) => {
      task.wait(
        (result) => {
          results[index] = { status: "resolved", value: result };
          settledCount++;
          if (settledCount === tasks.length) {
            combinedTask.resolve(results);
          }
        },
        (error) => {
          results[index] = {
            status: error.type === "abort" ? "aborted" : "rejected",
            reason: error.reason
          };
          settledCount++;
          if (settledCount === tasks.length) {
            combinedTask.resolve(results);
          }
        }
      );
    });
    return combinedTask;
  }
  /**
   * Static method that resolves/rejects with the first task that settles
   *
   * @param tasks - array of tasks to race
   * @returns new task that settles with the first input task that settles
   * @public
   */
  static race(tasks) {
    const combinedTask = new Task();
    if (tasks.length === 0) {
      combinedTask.reject("No tasks provided");
      return combinedTask;
    }
    let isSettled = false;
    tasks.forEach((task) => {
      task.wait(
        (result) => {
          if (isSettled) return;
          isSettled = true;
          combinedTask.resolve(result);
        },
        (error) => {
          if (isSettled) return;
          isSettled = true;
          if (error.type === "abort") {
            combinedTask.abort(error.reason);
          } else {
            combinedTask.reject(error.reason);
          }
        }
      );
    });
    return combinedTask;
  }
  /**
   * Utility to track progress of multiple tasks
   *
   * @param tasks - array of tasks to track
   * @param onProgress - callback called when any task completes
   * @returns new task that resolves when all input tasks resolve
   * @public
   */
  static withProgress(tasks, onProgress) {
    const combinedTask = Task.all(tasks);
    if (onProgress) {
      let completedCount = 0;
      tasks.forEach((task) => {
        task.wait(
          () => {
            completedCount++;
            onProgress(completedCount, tasks.length);
          },
          () => {
            completedCount++;
            onProgress(completedCount, tasks.length);
          }
        );
      });
    }
    return combinedTask;
  }
}
const PdfSoftHyphenMarker = "­";
const PdfZeroWidthSpace = "​";
const PdfWordJoiner = "⁠";
const PdfBomOrZwnbsp = "\uFEFF";
const PdfNonCharacterFFFE = "￾";
const PdfNonCharacterFFFF = "￿";
const PdfUnwantedTextMarkers = Object.freeze([
  PdfSoftHyphenMarker,
  PdfZeroWidthSpace,
  PdfWordJoiner,
  PdfBomOrZwnbsp,
  PdfNonCharacterFFFE,
  PdfNonCharacterFFFF
]);
const PdfUnwantedTextRegex = new RegExp(`[${PdfUnwantedTextMarkers.join("")}]`, "g");
function stripPdfUnwantedMarkers(text) {
  return text.replace(PdfUnwantedTextRegex, "");
}
var PdfZoomMode = /* @__PURE__ */ ((PdfZoomMode2) => {
  PdfZoomMode2[PdfZoomMode2["Unknown"] = 0] = "Unknown";
  PdfZoomMode2[PdfZoomMode2["XYZ"] = 1] = "XYZ";
  PdfZoomMode2[PdfZoomMode2["FitPage"] = 2] = "FitPage";
  PdfZoomMode2[PdfZoomMode2["FitHorizontal"] = 3] = "FitHorizontal";
  PdfZoomMode2[PdfZoomMode2["FitVertical"] = 4] = "FitVertical";
  PdfZoomMode2[PdfZoomMode2["FitRectangle"] = 5] = "FitRectangle";
  PdfZoomMode2[PdfZoomMode2["FitBoundingBox"] = 6] = "FitBoundingBox";
  PdfZoomMode2[PdfZoomMode2["FitBoundingBoxHorizontal"] = 7] = "FitBoundingBoxHorizontal";
  PdfZoomMode2[PdfZoomMode2["FitBoundingBoxVertical"] = 8] = "FitBoundingBoxVertical";
  return PdfZoomMode2;
})(PdfZoomMode || {});
var PdfTrappedStatus = /* @__PURE__ */ ((PdfTrappedStatus2) => {
  PdfTrappedStatus2[PdfTrappedStatus2["NotSet"] = 0] = "NotSet";
  PdfTrappedStatus2[PdfTrappedStatus2["True"] = 1] = "True";
  PdfTrappedStatus2[PdfTrappedStatus2["False"] = 2] = "False";
  PdfTrappedStatus2[PdfTrappedStatus2["Unknown"] = 3] = "Unknown";
  return PdfTrappedStatus2;
})(PdfTrappedStatus || {});
var PdfStandardFont = /* @__PURE__ */ ((PdfStandardFont2) => {
  PdfStandardFont2[PdfStandardFont2["Unknown"] = -1] = "Unknown";
  PdfStandardFont2[PdfStandardFont2["Courier"] = 0] = "Courier";
  PdfStandardFont2[PdfStandardFont2["Courier_Bold"] = 1] = "Courier_Bold";
  PdfStandardFont2[PdfStandardFont2["Courier_BoldOblique"] = 2] = "Courier_BoldOblique";
  PdfStandardFont2[PdfStandardFont2["Courier_Oblique"] = 3] = "Courier_Oblique";
  PdfStandardFont2[PdfStandardFont2["Helvetica"] = 4] = "Helvetica";
  PdfStandardFont2[PdfStandardFont2["Helvetica_Bold"] = 5] = "Helvetica_Bold";
  PdfStandardFont2[PdfStandardFont2["Helvetica_BoldOblique"] = 6] = "Helvetica_BoldOblique";
  PdfStandardFont2[PdfStandardFont2["Helvetica_Oblique"] = 7] = "Helvetica_Oblique";
  PdfStandardFont2[PdfStandardFont2["Times_Roman"] = 8] = "Times_Roman";
  PdfStandardFont2[PdfStandardFont2["Times_Bold"] = 9] = "Times_Bold";
  PdfStandardFont2[PdfStandardFont2["Times_BoldItalic"] = 10] = "Times_BoldItalic";
  PdfStandardFont2[PdfStandardFont2["Times_Italic"] = 11] = "Times_Italic";
  PdfStandardFont2[PdfStandardFont2["Symbol"] = 12] = "Symbol";
  PdfStandardFont2[PdfStandardFont2["ZapfDingbats"] = 13] = "ZapfDingbats";
  return PdfStandardFont2;
})(PdfStandardFont || {});
var PdfTextAlignment = /* @__PURE__ */ ((PdfTextAlignment2) => {
  PdfTextAlignment2[PdfTextAlignment2["Left"] = 0] = "Left";
  PdfTextAlignment2[PdfTextAlignment2["Center"] = 1] = "Center";
  PdfTextAlignment2[PdfTextAlignment2["Right"] = 2] = "Right";
  return PdfTextAlignment2;
})(PdfTextAlignment || {});
var PdfVerticalAlignment = /* @__PURE__ */ ((PdfVerticalAlignment2) => {
  PdfVerticalAlignment2[PdfVerticalAlignment2["Top"] = 0] = "Top";
  PdfVerticalAlignment2[PdfVerticalAlignment2["Middle"] = 1] = "Middle";
  PdfVerticalAlignment2[PdfVerticalAlignment2["Bottom"] = 2] = "Bottom";
  return PdfVerticalAlignment2;
})(PdfVerticalAlignment || {});
var PdfBlendMode = /* @__PURE__ */ ((PdfBlendMode2) => {
  PdfBlendMode2[PdfBlendMode2["Normal"] = 0] = "Normal";
  PdfBlendMode2[PdfBlendMode2["Multiply"] = 1] = "Multiply";
  PdfBlendMode2[PdfBlendMode2["Screen"] = 2] = "Screen";
  PdfBlendMode2[PdfBlendMode2["Overlay"] = 3] = "Overlay";
  PdfBlendMode2[PdfBlendMode2["Darken"] = 4] = "Darken";
  PdfBlendMode2[PdfBlendMode2["Lighten"] = 5] = "Lighten";
  PdfBlendMode2[PdfBlendMode2["ColorDodge"] = 6] = "ColorDodge";
  PdfBlendMode2[PdfBlendMode2["ColorBurn"] = 7] = "ColorBurn";
  PdfBlendMode2[PdfBlendMode2["HardLight"] = 8] = "HardLight";
  PdfBlendMode2[PdfBlendMode2["SoftLight"] = 9] = "SoftLight";
  PdfBlendMode2[PdfBlendMode2["Difference"] = 10] = "Difference";
  PdfBlendMode2[PdfBlendMode2["Exclusion"] = 11] = "Exclusion";
  PdfBlendMode2[PdfBlendMode2["Hue"] = 12] = "Hue";
  PdfBlendMode2[PdfBlendMode2["Saturation"] = 13] = "Saturation";
  PdfBlendMode2[PdfBlendMode2["Color"] = 14] = "Color";
  PdfBlendMode2[PdfBlendMode2["Luminosity"] = 15] = "Luminosity";
  return PdfBlendMode2;
})(PdfBlendMode || {});
var PdfStampFit = /* @__PURE__ */ ((PdfStampFit2) => {
  PdfStampFit2[PdfStampFit2["Contain"] = 0] = "Contain";
  PdfStampFit2[PdfStampFit2["Cover"] = 1] = "Cover";
  PdfStampFit2[PdfStampFit2["Stretch"] = 2] = "Stretch";
  return PdfStampFit2;
})(PdfStampFit || {});
var PdfActionType = /* @__PURE__ */ ((PdfActionType2) => {
  PdfActionType2[PdfActionType2["Unsupported"] = 0] = "Unsupported";
  PdfActionType2[PdfActionType2["Goto"] = 1] = "Goto";
  PdfActionType2[PdfActionType2["RemoteGoto"] = 2] = "RemoteGoto";
  PdfActionType2[PdfActionType2["URI"] = 3] = "URI";
  PdfActionType2[PdfActionType2["LaunchAppOrOpenFile"] = 4] = "LaunchAppOrOpenFile";
  return PdfActionType2;
})(PdfActionType || {});
const AP_MODE_NORMAL = 1;
const AP_MODE_ROLLOVER = 2;
const AP_MODE_DOWN = 4;
var PdfAnnotationSubtype = /* @__PURE__ */ ((PdfAnnotationSubtype2) => {
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["UNKNOWN"] = 0] = "UNKNOWN";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["TEXT"] = 1] = "TEXT";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["LINK"] = 2] = "LINK";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["FREETEXT"] = 3] = "FREETEXT";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["LINE"] = 4] = "LINE";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["SQUARE"] = 5] = "SQUARE";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["CIRCLE"] = 6] = "CIRCLE";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["POLYGON"] = 7] = "POLYGON";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["POLYLINE"] = 8] = "POLYLINE";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["HIGHLIGHT"] = 9] = "HIGHLIGHT";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["UNDERLINE"] = 10] = "UNDERLINE";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["SQUIGGLY"] = 11] = "SQUIGGLY";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["STRIKEOUT"] = 12] = "STRIKEOUT";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["STAMP"] = 13] = "STAMP";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["CARET"] = 14] = "CARET";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["INK"] = 15] = "INK";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["POPUP"] = 16] = "POPUP";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["FILEATTACHMENT"] = 17] = "FILEATTACHMENT";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["SOUND"] = 18] = "SOUND";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["MOVIE"] = 19] = "MOVIE";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["WIDGET"] = 20] = "WIDGET";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["SCREEN"] = 21] = "SCREEN";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["PRINTERMARK"] = 22] = "PRINTERMARK";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["TRAPNET"] = 23] = "TRAPNET";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["WATERMARK"] = 24] = "WATERMARK";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["THREED"] = 25] = "THREED";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["RICHMEDIA"] = 26] = "RICHMEDIA";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["XFAWIDGET"] = 27] = "XFAWIDGET";
  PdfAnnotationSubtype2[PdfAnnotationSubtype2["REDACT"] = 28] = "REDACT";
  return PdfAnnotationSubtype2;
})(PdfAnnotationSubtype || {});
const PdfAnnotationSubtypeName = {
  [
    0
    /* UNKNOWN */
  ]: "unknow",
  [
    1
    /* TEXT */
  ]: "text",
  [
    2
    /* LINK */
  ]: "link",
  [
    3
    /* FREETEXT */
  ]: "freetext",
  [
    4
    /* LINE */
  ]: "line",
  [
    5
    /* SQUARE */
  ]: "square",
  [
    6
    /* CIRCLE */
  ]: "circle",
  [
    7
    /* POLYGON */
  ]: "polygon",
  [
    8
    /* POLYLINE */
  ]: "polyline",
  [
    9
    /* HIGHLIGHT */
  ]: "highlight",
  [
    10
    /* UNDERLINE */
  ]: "underline",
  [
    11
    /* SQUIGGLY */
  ]: "squiggly",
  [
    12
    /* STRIKEOUT */
  ]: "strikeout",
  [
    13
    /* STAMP */
  ]: "stamp",
  [
    14
    /* CARET */
  ]: "caret",
  [
    15
    /* INK */
  ]: "ink",
  [
    16
    /* POPUP */
  ]: "popup",
  [
    17
    /* FILEATTACHMENT */
  ]: "fileattachment",
  [
    18
    /* SOUND */
  ]: "sound",
  [
    19
    /* MOVIE */
  ]: "movie",
  [
    20
    /* WIDGET */
  ]: "widget",
  [
    21
    /* SCREEN */
  ]: "screen",
  [
    22
    /* PRINTERMARK */
  ]: "printermark",
  [
    23
    /* TRAPNET */
  ]: "trapnet",
  [
    24
    /* WATERMARK */
  ]: "watermark",
  [
    25
    /* THREED */
  ]: "threed",
  [
    26
    /* RICHMEDIA */
  ]: "richmedia",
  [
    27
    /* XFAWIDGET */
  ]: "xfawidget",
  [
    28
    /* REDACT */
  ]: "redact"
};
var PdfAnnotationObjectStatus = /* @__PURE__ */ ((PdfAnnotationObjectStatus2) => {
  PdfAnnotationObjectStatus2[PdfAnnotationObjectStatus2["Created"] = 0] = "Created";
  PdfAnnotationObjectStatus2[PdfAnnotationObjectStatus2["Committed"] = 1] = "Committed";
  return PdfAnnotationObjectStatus2;
})(PdfAnnotationObjectStatus || {});
var AppearanceMode = /* @__PURE__ */ ((AppearanceMode2) => {
  AppearanceMode2[AppearanceMode2["Normal"] = 0] = "Normal";
  AppearanceMode2[AppearanceMode2["Rollover"] = 1] = "Rollover";
  AppearanceMode2[AppearanceMode2["Down"] = 2] = "Down";
  return AppearanceMode2;
})(AppearanceMode || {});
var PdfAnnotationState = /* @__PURE__ */ ((PdfAnnotationState2) => {
  PdfAnnotationState2["Marked"] = "Marked";
  PdfAnnotationState2["Unmarked"] = "Unmarked";
  PdfAnnotationState2["Accepted"] = "Accepted";
  PdfAnnotationState2["Rejected"] = "Rejected";
  PdfAnnotationState2["Completed"] = "Completed";
  PdfAnnotationState2["Cancelled"] = "Cancelled";
  PdfAnnotationState2["None"] = "None";
  return PdfAnnotationState2;
})(PdfAnnotationState || {});
var PdfAnnotationStateModel = /* @__PURE__ */ ((PdfAnnotationStateModel2) => {
  PdfAnnotationStateModel2["Marked"] = "Marked";
  PdfAnnotationStateModel2["Review"] = "Review";
  return PdfAnnotationStateModel2;
})(PdfAnnotationStateModel || {});
var PdfAnnotationIcon = /* @__PURE__ */ ((PdfAnnotationIcon2) => {
  PdfAnnotationIcon2[PdfAnnotationIcon2["Unknown"] = -1] = "Unknown";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Comment"] = 0] = "Comment";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Key"] = 1] = "Key";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Note"] = 2] = "Note";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Help"] = 3] = "Help";
  PdfAnnotationIcon2[PdfAnnotationIcon2["NewParagraph"] = 4] = "NewParagraph";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Paragraph"] = 5] = "Paragraph";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Insert"] = 6] = "Insert";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Graph"] = 7] = "Graph";
  PdfAnnotationIcon2[PdfAnnotationIcon2["PushPin"] = 8] = "PushPin";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Paperclip"] = 9] = "Paperclip";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Tag"] = 10] = "Tag";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Speaker"] = 11] = "Speaker";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Mic"] = 12] = "Mic";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Approved"] = 13] = "Approved";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Experimental"] = 14] = "Experimental";
  PdfAnnotationIcon2[PdfAnnotationIcon2["NotApproved"] = 15] = "NotApproved";
  PdfAnnotationIcon2[PdfAnnotationIcon2["AsIs"] = 16] = "AsIs";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Expired"] = 17] = "Expired";
  PdfAnnotationIcon2[PdfAnnotationIcon2["NotForPublicRelease"] = 18] = "NotForPublicRelease";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Confidential"] = 19] = "Confidential";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Final"] = 20] = "Final";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Sold"] = 21] = "Sold";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Departmental"] = 22] = "Departmental";
  PdfAnnotationIcon2[PdfAnnotationIcon2["ForComment"] = 23] = "ForComment";
  PdfAnnotationIcon2[PdfAnnotationIcon2["TopSecret"] = 24] = "TopSecret";
  PdfAnnotationIcon2[PdfAnnotationIcon2["Draft"] = 25] = "Draft";
  PdfAnnotationIcon2[PdfAnnotationIcon2["ForPublicRelease"] = 26] = "ForPublicRelease";
  return PdfAnnotationIcon2;
})(PdfAnnotationIcon || {});
var PdfAnnotationLineEnding = /* @__PURE__ */ ((PdfAnnotationLineEnding2) => {
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["None"] = 0] = "None";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["Square"] = 1] = "Square";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["Circle"] = 2] = "Circle";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["Diamond"] = 3] = "Diamond";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["OpenArrow"] = 4] = "OpenArrow";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["ClosedArrow"] = 5] = "ClosedArrow";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["Butt"] = 6] = "Butt";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["ROpenArrow"] = 7] = "ROpenArrow";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["RClosedArrow"] = 8] = "RClosedArrow";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["Slash"] = 9] = "Slash";
  PdfAnnotationLineEnding2[PdfAnnotationLineEnding2["Unknown"] = 10] = "Unknown";
  return PdfAnnotationLineEnding2;
})(PdfAnnotationLineEnding || {});
var PdfAnnotationReplyType = /* @__PURE__ */ ((PdfAnnotationReplyType2) => {
  PdfAnnotationReplyType2[PdfAnnotationReplyType2["Unknown"] = 0] = "Unknown";
  PdfAnnotationReplyType2[PdfAnnotationReplyType2["Reply"] = 1] = "Reply";
  PdfAnnotationReplyType2[PdfAnnotationReplyType2["Group"] = 2] = "Group";
  return PdfAnnotationReplyType2;
})(PdfAnnotationReplyType || {});
var PDF_FORM_FIELD_TYPE = /* @__PURE__ */ ((PDF_FORM_FIELD_TYPE2) => {
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["UNKNOWN"] = 0] = "UNKNOWN";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["PUSHBUTTON"] = 1] = "PUSHBUTTON";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["CHECKBOX"] = 2] = "CHECKBOX";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["RADIOBUTTON"] = 3] = "RADIOBUTTON";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["COMBOBOX"] = 4] = "COMBOBOX";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["LISTBOX"] = 5] = "LISTBOX";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["TEXTFIELD"] = 6] = "TEXTFIELD";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["SIGNATURE"] = 7] = "SIGNATURE";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA"] = 8] = "XFA";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA_CHECKBOX"] = 9] = "XFA_CHECKBOX";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA_COMBOBOX"] = 10] = "XFA_COMBOBOX";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA_IMAGEFIELD"] = 11] = "XFA_IMAGEFIELD";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA_LISTBOX"] = 12] = "XFA_LISTBOX";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA_PUSHBUTTON"] = 13] = "XFA_PUSHBUTTON";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA_SIGNATURE"] = 14] = "XFA_SIGNATURE";
  PDF_FORM_FIELD_TYPE2[PDF_FORM_FIELD_TYPE2["XFA_TEXTFIELD"] = 15] = "XFA_TEXTFIELD";
  return PDF_FORM_FIELD_TYPE2;
})(PDF_FORM_FIELD_TYPE || {});
var PdfAnnotationColorType = /* @__PURE__ */ ((PdfAnnotationColorType2) => {
  PdfAnnotationColorType2[PdfAnnotationColorType2["Color"] = 0] = "Color";
  PdfAnnotationColorType2[PdfAnnotationColorType2["InteriorColor"] = 1] = "InteriorColor";
  PdfAnnotationColorType2[PdfAnnotationColorType2["OverlayColor"] = 2] = "OverlayColor";
  return PdfAnnotationColorType2;
})(PdfAnnotationColorType || {});
var PdfAnnotationBorderStyle = /* @__PURE__ */ ((PdfAnnotationBorderStyle2) => {
  PdfAnnotationBorderStyle2[PdfAnnotationBorderStyle2["UNKNOWN"] = 0] = "UNKNOWN";
  PdfAnnotationBorderStyle2[PdfAnnotationBorderStyle2["SOLID"] = 1] = "SOLID";
  PdfAnnotationBorderStyle2[PdfAnnotationBorderStyle2["DASHED"] = 2] = "DASHED";
  PdfAnnotationBorderStyle2[PdfAnnotationBorderStyle2["BEVELED"] = 3] = "BEVELED";
  PdfAnnotationBorderStyle2[PdfAnnotationBorderStyle2["INSET"] = 4] = "INSET";
  PdfAnnotationBorderStyle2[PdfAnnotationBorderStyle2["UNDERLINE"] = 5] = "UNDERLINE";
  PdfAnnotationBorderStyle2[PdfAnnotationBorderStyle2["CLOUDY"] = 6] = "CLOUDY";
  return PdfAnnotationBorderStyle2;
})(PdfAnnotationBorderStyle || {});
var PdfAnnotationFlags = /* @__PURE__ */ ((PdfAnnotationFlags2) => {
  PdfAnnotationFlags2[PdfAnnotationFlags2["NONE"] = 0] = "NONE";
  PdfAnnotationFlags2[PdfAnnotationFlags2["INVISIBLE"] = 1] = "INVISIBLE";
  PdfAnnotationFlags2[PdfAnnotationFlags2["HIDDEN"] = 2] = "HIDDEN";
  PdfAnnotationFlags2[PdfAnnotationFlags2["PRINT"] = 4] = "PRINT";
  PdfAnnotationFlags2[PdfAnnotationFlags2["NO_ZOOM"] = 8] = "NO_ZOOM";
  PdfAnnotationFlags2[PdfAnnotationFlags2["NO_ROTATE"] = 16] = "NO_ROTATE";
  PdfAnnotationFlags2[PdfAnnotationFlags2["NO_VIEW"] = 32] = "NO_VIEW";
  PdfAnnotationFlags2[PdfAnnotationFlags2["READ_ONLY"] = 64] = "READ_ONLY";
  PdfAnnotationFlags2[PdfAnnotationFlags2["LOCKED"] = 128] = "LOCKED";
  PdfAnnotationFlags2[PdfAnnotationFlags2["TOGGLE_NOVIEW"] = 256] = "TOGGLE_NOVIEW";
  return PdfAnnotationFlags2;
})(PdfAnnotationFlags || {});
var PDF_FORM_FIELD_FLAG = /* @__PURE__ */ ((PDF_FORM_FIELD_FLAG2) => {
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["NONE"] = 0] = "NONE";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["READONLY"] = 1] = "READONLY";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["REQUIRED"] = 2] = "REQUIRED";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["NOEXPORT"] = 4] = "NOEXPORT";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["TEXT_MULTIPLINE"] = 4096] = "TEXT_MULTIPLINE";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["TEXT_PASSWORD"] = 8192] = "TEXT_PASSWORD";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["CHOICE_COMBO"] = 131072] = "CHOICE_COMBO";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["CHOICE_EDIT"] = 262144] = "CHOICE_EDIT";
  PDF_FORM_FIELD_FLAG2[PDF_FORM_FIELD_FLAG2["CHOICE_MULTL_SELECT"] = 2097152] = "CHOICE_MULTL_SELECT";
  return PDF_FORM_FIELD_FLAG2;
})(PDF_FORM_FIELD_FLAG || {});
var PdfPageObjectType = /* @__PURE__ */ ((PdfPageObjectType2) => {
  PdfPageObjectType2[PdfPageObjectType2["UNKNOWN"] = 0] = "UNKNOWN";
  PdfPageObjectType2[PdfPageObjectType2["TEXT"] = 1] = "TEXT";
  PdfPageObjectType2[PdfPageObjectType2["PATH"] = 2] = "PATH";
  PdfPageObjectType2[PdfPageObjectType2["IMAGE"] = 3] = "IMAGE";
  PdfPageObjectType2[PdfPageObjectType2["SHADING"] = 4] = "SHADING";
  PdfPageObjectType2[PdfPageObjectType2["FORM"] = 5] = "FORM";
  return PdfPageObjectType2;
})(PdfPageObjectType || {});
const PdfAnnotationFlagName = Object.freeze({
  [
    1
    /* INVISIBLE */
  ]: "invisible",
  [
    2
    /* HIDDEN */
  ]: "hidden",
  [
    4
    /* PRINT */
  ]: "print",
  [
    8
    /* NO_ZOOM */
  ]: "noZoom",
  [
    16
    /* NO_ROTATE */
  ]: "noRotate",
  [
    32
    /* NO_VIEW */
  ]: "noView",
  [
    64
    /* READ_ONLY */
  ]: "readOnly",
  [
    128
    /* LOCKED */
  ]: "locked",
  [
    256
    /* TOGGLE_NOVIEW */
  ]: "toggleNoView"
});
const PdfAnnotationFlagValue = Object.entries(
  PdfAnnotationFlagName
).reduce(
  (acc, [bit, name]) => {
    acc[name] = Number(bit);
    return acc;
  },
  {}
);
function flagsToNames(raw) {
  return Object.keys(PdfAnnotationFlagName).filter((flag) => (raw & flag) !== 0).map((flag) => PdfAnnotationFlagName[flag]);
}
function namesToFlags(names) {
  return names.reduce(
    (mask, name) => mask | PdfAnnotationFlagValue[name],
    0
    /* NONE */
  );
}
var PdfSegmentObjectType = /* @__PURE__ */ ((PdfSegmentObjectType2) => {
  PdfSegmentObjectType2[PdfSegmentObjectType2["UNKNOWN"] = -1] = "UNKNOWN";
  PdfSegmentObjectType2[PdfSegmentObjectType2["LINETO"] = 0] = "LINETO";
  PdfSegmentObjectType2[PdfSegmentObjectType2["BEZIERTO"] = 1] = "BEZIERTO";
  PdfSegmentObjectType2[PdfSegmentObjectType2["MOVETO"] = 2] = "MOVETO";
  return PdfSegmentObjectType2;
})(PdfSegmentObjectType || {});
var FontCharset = /* @__PURE__ */ ((FontCharset2) => {
  FontCharset2[FontCharset2["ANSI"] = 0] = "ANSI";
  FontCharset2[FontCharset2["DEFAULT"] = 1] = "DEFAULT";
  FontCharset2[FontCharset2["SYMBOL"] = 2] = "SYMBOL";
  FontCharset2[FontCharset2["SHIFTJIS"] = 128] = "SHIFTJIS";
  FontCharset2[FontCharset2["HANGEUL"] = 129] = "HANGEUL";
  FontCharset2[FontCharset2["GB2312"] = 134] = "GB2312";
  FontCharset2[FontCharset2["CHINESEBIG5"] = 136] = "CHINESEBIG5";
  FontCharset2[FontCharset2["GREEK"] = 161] = "GREEK";
  FontCharset2[FontCharset2["VIETNAMESE"] = 163] = "VIETNAMESE";
  FontCharset2[FontCharset2["HEBREW"] = 177] = "HEBREW";
  FontCharset2[FontCharset2["ARABIC"] = 178] = "ARABIC";
  FontCharset2[FontCharset2["CYRILLIC"] = 204] = "CYRILLIC";
  FontCharset2[FontCharset2["THAI"] = 222] = "THAI";
  FontCharset2[FontCharset2["EASTERNEUROPEAN"] = 238] = "EASTERNEUROPEAN";
  return FontCharset2;
})(FontCharset || {});
var PdfEngineFeature = /* @__PURE__ */ ((PdfEngineFeature2) => {
  PdfEngineFeature2[PdfEngineFeature2["RenderPage"] = 0] = "RenderPage";
  PdfEngineFeature2[PdfEngineFeature2["RenderPageRect"] = 1] = "RenderPageRect";
  PdfEngineFeature2[PdfEngineFeature2["Thumbnails"] = 2] = "Thumbnails";
  PdfEngineFeature2[PdfEngineFeature2["Bookmarks"] = 3] = "Bookmarks";
  PdfEngineFeature2[PdfEngineFeature2["Annotations"] = 4] = "Annotations";
  return PdfEngineFeature2;
})(PdfEngineFeature || {});
var PdfEngineOperation = /* @__PURE__ */ ((PdfEngineOperation2) => {
  PdfEngineOperation2[PdfEngineOperation2["Create"] = 0] = "Create";
  PdfEngineOperation2[PdfEngineOperation2["Read"] = 1] = "Read";
  PdfEngineOperation2[PdfEngineOperation2["Update"] = 2] = "Update";
  PdfEngineOperation2[PdfEngineOperation2["Delete"] = 3] = "Delete";
  return PdfEngineOperation2;
})(PdfEngineOperation || {});
var MatchFlag = /* @__PURE__ */ ((MatchFlag2) => {
  MatchFlag2[MatchFlag2["None"] = 0] = "None";
  MatchFlag2[MatchFlag2["MatchCase"] = 1] = "MatchCase";
  MatchFlag2[MatchFlag2["MatchWholeWord"] = 2] = "MatchWholeWord";
  MatchFlag2[MatchFlag2["MatchConsecutive"] = 4] = "MatchConsecutive";
  return MatchFlag2;
})(MatchFlag || {});
function unionFlags(flags) {
  return flags.reduce(
    (flag, currFlag) => {
      return flag | currFlag;
    },
    0
    /* None */
  );
}
function compareSearchTarget(targetA, targetB) {
  const flagA = unionFlags(targetA.flags);
  const flagB = unionFlags(targetB.flags);
  return flagA === flagB && targetA.keyword === targetB.keyword;
}
var PdfPermissionFlag = /* @__PURE__ */ ((PdfPermissionFlag2) => {
  PdfPermissionFlag2[PdfPermissionFlag2["Print"] = 4] = "Print";
  PdfPermissionFlag2[PdfPermissionFlag2["ModifyContents"] = 8] = "ModifyContents";
  PdfPermissionFlag2[PdfPermissionFlag2["CopyContents"] = 16] = "CopyContents";
  PdfPermissionFlag2[PdfPermissionFlag2["ModifyAnnotations"] = 32] = "ModifyAnnotations";
  PdfPermissionFlag2[PdfPermissionFlag2["FillForms"] = 256] = "FillForms";
  PdfPermissionFlag2[PdfPermissionFlag2["ExtractForAccessibility"] = 512] = "ExtractForAccessibility";
  PdfPermissionFlag2[PdfPermissionFlag2["AssembleDocument"] = 1024] = "AssembleDocument";
  PdfPermissionFlag2[PdfPermissionFlag2["PrintHighQuality"] = 2048] = "PrintHighQuality";
  PdfPermissionFlag2[PdfPermissionFlag2["AllowAll"] = 3900] = "AllowAll";
  return PdfPermissionFlag2;
})(PdfPermissionFlag || {});
function buildPermissions(...flags) {
  let result = flags.reduce((acc, flag) => acc | flag, 0);
  if (result & 2048) {
    result |= 4;
  }
  return result;
}
class PermissionDeniedError extends Error {
  constructor(requiredFlags, currentPermissions) {
    const flagNames = requiredFlags.map((f) => PdfPermissionFlag[f]).join(", ");
    super(`Permission denied. Required: ${flagNames}`);
    this.requiredFlags = requiredFlags;
    this.currentPermissions = currentPermissions;
    this.name = "PermissionDeniedError";
  }
}
var PdfPageFlattenFlag = /* @__PURE__ */ ((PdfPageFlattenFlag2) => {
  PdfPageFlattenFlag2[PdfPageFlattenFlag2["Display"] = 0] = "Display";
  PdfPageFlattenFlag2[PdfPageFlattenFlag2["Print"] = 1] = "Print";
  return PdfPageFlattenFlag2;
})(PdfPageFlattenFlag || {});
var PdfPageFlattenResult = /* @__PURE__ */ ((PdfPageFlattenResult2) => {
  PdfPageFlattenResult2[PdfPageFlattenResult2["Fail"] = 0] = "Fail";
  PdfPageFlattenResult2[PdfPageFlattenResult2["Success"] = 1] = "Success";
  PdfPageFlattenResult2[PdfPageFlattenResult2["NothingToDo"] = 2] = "NothingToDo";
  return PdfPageFlattenResult2;
})(PdfPageFlattenResult || {});
var PdfErrorCode = /* @__PURE__ */ ((PdfErrorCode2) => {
  PdfErrorCode2[PdfErrorCode2["Ok"] = 0] = "Ok";
  PdfErrorCode2[PdfErrorCode2["Unknown"] = 1] = "Unknown";
  PdfErrorCode2[PdfErrorCode2["NotFound"] = 2] = "NotFound";
  PdfErrorCode2[PdfErrorCode2["WrongFormat"] = 3] = "WrongFormat";
  PdfErrorCode2[PdfErrorCode2["Password"] = 4] = "Password";
  PdfErrorCode2[PdfErrorCode2["Security"] = 5] = "Security";
  PdfErrorCode2[PdfErrorCode2["PageError"] = 6] = "PageError";
  PdfErrorCode2[PdfErrorCode2["XFALoad"] = 7] = "XFALoad";
  PdfErrorCode2[PdfErrorCode2["XFALayout"] = 8] = "XFALayout";
  PdfErrorCode2[PdfErrorCode2["Cancelled"] = 9] = "Cancelled";
  PdfErrorCode2[PdfErrorCode2["Initialization"] = 10] = "Initialization";
  PdfErrorCode2[PdfErrorCode2["NotReady"] = 11] = "NotReady";
  PdfErrorCode2[PdfErrorCode2["NotSupport"] = 12] = "NotSupport";
  PdfErrorCode2[PdfErrorCode2["LoadDoc"] = 13] = "LoadDoc";
  PdfErrorCode2[PdfErrorCode2["DocNotOpen"] = 14] = "DocNotOpen";
  PdfErrorCode2[PdfErrorCode2["CantCloseDoc"] = 15] = "CantCloseDoc";
  PdfErrorCode2[PdfErrorCode2["CantCreateNewDoc"] = 16] = "CantCreateNewDoc";
  PdfErrorCode2[PdfErrorCode2["CantImportPages"] = 17] = "CantImportPages";
  PdfErrorCode2[PdfErrorCode2["CantCreateAnnot"] = 18] = "CantCreateAnnot";
  PdfErrorCode2[PdfErrorCode2["CantSetAnnotRect"] = 19] = "CantSetAnnotRect";
  PdfErrorCode2[PdfErrorCode2["CantSetAnnotContent"] = 20] = "CantSetAnnotContent";
  PdfErrorCode2[PdfErrorCode2["CantRemoveInkList"] = 21] = "CantRemoveInkList";
  PdfErrorCode2[PdfErrorCode2["CantAddInkStoke"] = 22] = "CantAddInkStoke";
  PdfErrorCode2[PdfErrorCode2["CantReadAttachmentSize"] = 23] = "CantReadAttachmentSize";
  PdfErrorCode2[PdfErrorCode2["CantReadAttachmentContent"] = 24] = "CantReadAttachmentContent";
  PdfErrorCode2[PdfErrorCode2["CantFocusAnnot"] = 25] = "CantFocusAnnot";
  PdfErrorCode2[PdfErrorCode2["CantSelectText"] = 26] = "CantSelectText";
  PdfErrorCode2[PdfErrorCode2["CantSelectOption"] = 27] = "CantSelectOption";
  PdfErrorCode2[PdfErrorCode2["CantCheckField"] = 28] = "CantCheckField";
  PdfErrorCode2[PdfErrorCode2["CantSetAnnotString"] = 29] = "CantSetAnnotString";
  return PdfErrorCode2;
})(PdfErrorCode || {});
class PdfTaskHelper {
  /**
   * Create a task
   * @returns new task
   */
  static create() {
    return new Task();
  }
  /**
   * Create a task that has been resolved with value
   * @param result - resolved value
   * @returns resolved task
   */
  static resolve(result) {
    const task = new Task();
    task.resolve(result);
    return task;
  }
  /**
   * Create a task that has been rejected with error
   * @param reason - rejected error
   * @returns rejected task
   */
  static reject(reason) {
    const task = new Task();
    task.reject(reason);
    return task;
  }
  /**
   * Create a task that has been aborted with error
   * @param reason - aborted error
   * @returns aborted task
   */
  static abort(reason) {
    const task = new Task();
    task.reject(reason);
    return task;
  }
}
function pdfColorToWebColor(c) {
  const clamp = (n) => Math.max(0, Math.min(255, n));
  const toHex = (n) => clamp(n).toString(16).padStart(2, "0");
  return `#${toHex(c.red)}${toHex(c.green)}${toHex(c.blue)}`;
}
function webColorToPdfColor(color) {
  if (/^#?[0-9a-f]{3}$/i.test(color)) {
    color = color.replace(/^#?([0-9a-f])([0-9a-f])([0-9a-f])$/i, "#$1$1$2$2$3$3").toLowerCase();
  }
  const [, r, g, b] = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color) ?? (() => {
    throw new Error(`Invalid hex colour: "${color}"`);
  })();
  return {
    red: parseInt(r, 16),
    green: parseInt(g, 16),
    blue: parseInt(b, 16)
  };
}
function getContrastStrokeColor(fillColor) {
  try {
    const { red, green, blue } = webColorToPdfColor(fillColor);
    const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
    return luminance < 0.45 ? "#fff" : "#000";
  } catch {
    return "#000";
  }
}
function pdfAlphaToWebOpacity(alpha) {
  const clamp = (n) => Math.max(0, Math.min(255, n));
  return clamp(alpha) / 255;
}
function webOpacityToPdfAlpha(opacity) {
  const clamp = (n, hi = 255) => Math.max(0, Math.min(hi, n));
  return clamp(Math.round(opacity * 255));
}
function extractPdfColor(c) {
  return { red: c.red, green: c.green, blue: c.blue };
}
function extractWebOpacity(c) {
  return pdfAlphaToWebOpacity(c.alpha);
}
function combinePdfColorWithAlpha(color, alpha) {
  return { ...color, alpha };
}
function combineWebColorWithOpacity(color, opacity) {
  return { color, opacity };
}
function pdfAlphaColorToWebAlphaColor(c) {
  const color = pdfColorToWebColor(extractPdfColor(c));
  const opacity = extractWebOpacity(c);
  return { color, opacity };
}
function webAlphaColorToPdfAlphaColor({ color, opacity }) {
  const pdfColor = webColorToPdfColor(color);
  const alpha = webOpacityToPdfAlpha(opacity);
  return combinePdfColorWithAlpha(pdfColor, alpha);
}
function pdfDateToDate(pdf) {
  if (!(pdf == null ? void 0 : pdf.startsWith("D:")) || pdf.length < 16) return;
  const y = +pdf.slice(2, 6);
  const mo = +pdf.slice(6, 8) - 1;
  const d = +pdf.slice(8, 10);
  const H = +pdf.slice(10, 12);
  const M = +pdf.slice(12, 14);
  const S = +pdf.slice(14, 16);
  return new Date(Date.UTC(y, mo, d, H, M, S));
}
function dateToPdfDate(date = /* @__PURE__ */ new Date()) {
  const z = (n, len = 2) => n.toString().padStart(len, "0");
  const YYYY = date.getUTCFullYear();
  const MM = z(date.getUTCMonth() + 1);
  const DD = z(date.getUTCDate());
  const HH = z(date.getUTCHours());
  const mm = z(date.getUTCMinutes());
  const SS = z(date.getUTCSeconds());
  return `D:${YYYY}${MM}${DD}${HH}${mm}${SS}`;
}
const MixedTextAlignment = Symbol("mixed");
const TEXT_ALIGNMENT_INFOS = Object.freeze([
  { id: PdfTextAlignment.Left, label: "Left", css: "left" },
  { id: PdfTextAlignment.Center, label: "Center", css: "center" },
  { id: PdfTextAlignment.Right, label: "Right", css: "right" }
]);
const enumToTextInfo = TEXT_ALIGNMENT_INFOS.reduce(
  (m, info) => {
    m[info.id] = info;
    return m;
  },
  {}
);
const cssToTextEnum = TEXT_ALIGNMENT_INFOS.reduce(
  (m, info) => {
    m[info.css] = info.id;
    return m;
  },
  {}
);
function getTextAlignmentInfo(alignment) {
  return enumToTextInfo[alignment] ?? enumToTextInfo[PdfTextAlignment.Left];
}
function textAlignmentToCss(alignment) {
  return getTextAlignmentInfo(alignment).css;
}
function cssToTextAlignment(value) {
  return cssToTextEnum[value];
}
function textAlignmentLabel(alignment) {
  return getTextAlignmentInfo(alignment).label;
}
function reduceTextAlignments(values) {
  if (!values.length) return PdfTextAlignment.Left;
  const first = values[0];
  return values.every((a) => a === first) ? first : MixedTextAlignment;
}
const textAlignmentSelectOptions = TEXT_ALIGNMENT_INFOS.map((info) => ({
  value: info.id,
  label: info.label
}));
var PdfStandardFontFamily = /* @__PURE__ */ ((PdfStandardFontFamily2) => {
  PdfStandardFontFamily2["Courier"] = "Courier";
  PdfStandardFontFamily2["Helvetica"] = "Helvetica";
  PdfStandardFontFamily2["Times"] = "Times";
  PdfStandardFontFamily2["Symbol"] = "Symbol";
  PdfStandardFontFamily2["ZapfDingbats"] = "ZapfDingbats";
  PdfStandardFontFamily2["Unknown"] = "Unknown";
  return PdfStandardFontFamily2;
})(PdfStandardFontFamily || {});
const DEFAULT_FALLBACK_FONT = PdfStandardFont.Helvetica;
const MixedStandardFont = Symbol("mixed");
const HELVETICA_DESC = {
  id: PdfStandardFont.Helvetica,
  family: "Helvetica",
  bold: false,
  italic: false,
  label: "Helvetica",
  css: "Helvetica, Arial, sans-serif"
};
const STANDARD_FONT_DESCRIPTORS = Object.freeze([
  {
    id: PdfStandardFont.Courier,
    family: "Courier",
    bold: false,
    italic: false,
    label: "Courier",
    css: "Courier, monospace"
  },
  {
    id: PdfStandardFont.Courier_Bold,
    family: "Courier",
    bold: true,
    italic: false,
    label: "Courier Bold",
    css: "Courier, monospace"
  },
  {
    id: PdfStandardFont.Courier_BoldOblique,
    family: "Courier",
    bold: true,
    italic: true,
    label: "Courier Bold Oblique",
    css: "Courier, monospace"
  },
  {
    id: PdfStandardFont.Courier_Oblique,
    family: "Courier",
    bold: false,
    italic: true,
    label: "Courier Oblique",
    css: "Courier, monospace"
  },
  HELVETICA_DESC,
  {
    id: PdfStandardFont.Helvetica_Bold,
    family: "Helvetica",
    bold: true,
    italic: false,
    label: "Helvetica Bold",
    css: "Helvetica, Arial, sans-serif"
  },
  {
    id: PdfStandardFont.Helvetica_BoldOblique,
    family: "Helvetica",
    bold: true,
    italic: true,
    label: "Helvetica Bold Oblique",
    css: "Helvetica, Arial, sans-serif"
  },
  {
    id: PdfStandardFont.Helvetica_Oblique,
    family: "Helvetica",
    bold: false,
    italic: true,
    label: "Helvetica Oblique",
    css: "Helvetica, Arial, sans-serif"
  },
  {
    id: PdfStandardFont.Times_Roman,
    family: "Times",
    bold: false,
    italic: false,
    label: "Times Roman",
    css: '"Times New Roman", Times, serif'
  },
  {
    id: PdfStandardFont.Times_Bold,
    family: "Times",
    bold: true,
    italic: false,
    label: "Times Bold",
    css: '"Times New Roman", Times, serif'
  },
  {
    id: PdfStandardFont.Times_BoldItalic,
    family: "Times",
    bold: true,
    italic: true,
    label: "Times Bold Italic",
    css: '"Times New Roman", Times, serif'
  },
  {
    id: PdfStandardFont.Times_Italic,
    family: "Times",
    bold: false,
    italic: true,
    label: "Times Italic",
    css: '"Times New Roman", Times, serif'
  },
  {
    id: PdfStandardFont.Symbol,
    family: "Symbol",
    bold: false,
    italic: false,
    label: "Symbol",
    css: "Symbol, serif"
  },
  {
    id: PdfStandardFont.ZapfDingbats,
    family: "ZapfDingbats",
    bold: false,
    italic: false,
    label: "Zapf Dingbats",
    css: "ZapfDingbats, serif"
  }
]);
const idToDescriptor = STANDARD_FONT_DESCRIPTORS.reduce((m, d) => (m[d.id] = d, m), {});
const familyStyleToId = /* @__PURE__ */ new Map();
for (const d of STANDARD_FONT_DESCRIPTORS) {
  familyStyleToId.set(`${d.family}_${d.bold}_${d.italic}`, d.id);
}
function unknownDescriptor() {
  return HELVETICA_DESC;
}
function getStandardFontDescriptor(font) {
  return idToDescriptor[font] ?? unknownDescriptor();
}
function standardFontFamily(font) {
  return getStandardFontDescriptor(font).family;
}
function standardFontIsBold(font) {
  return getStandardFontDescriptor(font).bold;
}
function standardFontIsItalic(font) {
  return getStandardFontDescriptor(font).italic;
}
function makeStandardFont(family, { bold, italic }) {
  return familyStyleToId.get(`${family}_${bold}_${italic}`) ?? DEFAULT_FALLBACK_FONT;
}
function standardFontLabel(font) {
  return getStandardFontDescriptor(font).label;
}
function standardFontCss(font) {
  return getStandardFontDescriptor(font).css;
}
function standardFontCssProperties(font) {
  const desc = getStandardFontDescriptor(font);
  return {
    fontFamily: desc.css,
    fontWeight: desc.bold ? "bold" : "normal",
    fontStyle: desc.italic ? "italic" : "normal"
  };
}
const standardFontFamilySelectOptions = Object.values(PdfStandardFontFamily).filter(
  (f) => f !== "Unknown"
  /* Unknown */
).map((family) => ({ value: family, label: family }));
function reduceStandardFonts(fonts) {
  if (!fonts.length) return PdfStandardFont.Unknown;
  const first = fonts[0];
  return fonts.every((f) => f === first) ? first : MixedStandardFont;
}
const STANDARD_FONT_FAMILIES = [
  ...new Set(STANDARD_FONT_DESCRIPTORS.map((d) => d.family))
];
function standardFontFamilyLabel(fam) {
  switch (fam) {
    case "Courier":
      return "Courier";
    case "Helvetica":
      return "Helvetica";
    case "Times":
      return "Times";
    case "Symbol":
      return "Symbol";
    case "ZapfDingbats":
      return "ZapfDingbats";
    /* fallback */
    default:
      return "Helvetica";
  }
}
const MixedBlendMode = Symbol("mixed");
const BLEND_MODE_INFOS = Object.freeze([
  { id: PdfBlendMode.Normal, label: "Normal", css: "normal" },
  { id: PdfBlendMode.Multiply, label: "Multiply", css: "multiply" },
  { id: PdfBlendMode.Screen, label: "Screen", css: "screen" },
  { id: PdfBlendMode.Overlay, label: "Overlay", css: "overlay" },
  { id: PdfBlendMode.Darken, label: "Darken", css: "darken" },
  { id: PdfBlendMode.Lighten, label: "Lighten", css: "lighten" },
  { id: PdfBlendMode.ColorDodge, label: "Color Dodge", css: "color-dodge" },
  { id: PdfBlendMode.ColorBurn, label: "Color Burn", css: "color-burn" },
  { id: PdfBlendMode.HardLight, label: "Hard Light", css: "hard-light" },
  { id: PdfBlendMode.SoftLight, label: "Soft Light", css: "soft-light" },
  { id: PdfBlendMode.Difference, label: "Difference", css: "difference" },
  { id: PdfBlendMode.Exclusion, label: "Exclusion", css: "exclusion" },
  { id: PdfBlendMode.Hue, label: "Hue", css: "hue" },
  { id: PdfBlendMode.Saturation, label: "Saturation", css: "saturation" },
  { id: PdfBlendMode.Color, label: "Color", css: "color" },
  { id: PdfBlendMode.Luminosity, label: "Luminosity", css: "luminosity" }
]);
const enumToInfo = BLEND_MODE_INFOS.reduce(
  (m, info) => {
    m[info.id] = info;
    return m;
  },
  {}
);
const cssToEnum = BLEND_MODE_INFOS.reduce(
  (m, info) => {
    m[info.css] = info.id;
    return m;
  },
  {}
);
function getBlendModeInfo(mode) {
  return enumToInfo[mode] ?? enumToInfo[PdfBlendMode.Normal];
}
function blendModeToCss(mode) {
  return getBlendModeInfo(mode).css;
}
function cssToBlendMode(value) {
  return cssToEnum[value];
}
function blendModeLabel(mode) {
  return getBlendModeInfo(mode).label;
}
function reduceBlendModes(modes) {
  if (!modes.length) return PdfBlendMode.Normal;
  const first = modes[0];
  return modes.every((m) => m === first) ? first : MixedBlendMode;
}
const blendModeSelectOptions = BLEND_MODE_INFOS.map((info) => ({
  value: info.id,
  label: info.label
}));
const blendModeValues = BLEND_MODE_INFOS.map((info) => info.id);
function uiBlendModeDisplay(value) {
  return value === MixedBlendMode ? "(mixed)" : blendModeLabel(value);
}
function serializeLogger(logger) {
  if (logger instanceof NoopLogger) {
    return { type: "noop" };
  }
  if (logger instanceof ConsoleLogger) {
    return { type: "console" };
  }
  if (logger instanceof PerfLogger) {
    return { type: "perf" };
  }
  if (logger instanceof LevelLogger) {
    const levelLogger = logger;
    return {
      type: "level",
      config: {
        level: levelLogger.level,
        logger: serializeLogger(levelLogger.logger)
      }
    };
  }
  if (logger instanceof AllLogger) {
    const allLogger = logger;
    return {
      type: "all",
      config: {
        loggers: allLogger.loggers.map(serializeLogger)
      }
    };
  }
  return { type: "noop" };
}
function deserializeLogger(serialized) {
  var _a, _b, _c;
  switch (serialized.type) {
    case "noop":
      return new NoopLogger();
    case "console":
      return new ConsoleLogger();
    case "perf":
      return new PerfLogger();
    case "level":
      if (!((_a = serialized.config) == null ? void 0 : _a.logger) || ((_b = serialized.config) == null ? void 0 : _b.level) === void 0) {
        throw new Error("LevelLogger requires logger and level in config");
      }
      return new LevelLogger(deserializeLogger(serialized.config.logger), serialized.config.level);
    case "all":
      if (!((_c = serialized.config) == null ? void 0 : _c.loggers)) {
        throw new Error("AllLogger requires loggers array in config");
      }
      return new AllLogger(serialized.config.loggers.map(deserializeLogger));
    default:
      return new NoopLogger();
  }
}
const V4_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function isUuidV4(str) {
  return V4_REGEX.test(str);
}
function getRandomBytes(len) {
  var _a;
  if (typeof ((_a = globalThis.crypto) == null ? void 0 : _a.getRandomValues) === "function") {
    return globalThis.crypto.getRandomValues(new Uint8Array(len));
  }
  if (typeof require === "function") {
    try {
      const { randomBytes } = require("crypto");
      return randomBytes(len);
    } catch {
    }
  }
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = Math.floor(Math.random() * 256);
  return bytes;
}
function uuidV4() {
  var _a;
  if (typeof ((_a = globalThis.crypto) == null ? void 0 : _a.randomUUID) === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = getRandomBytes(16);
  bytes[6] = bytes[6] & 15 | 64;
  bytes[8] = bytes[8] & 63 | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
class CompoundTask extends Task {
  constructor(config = {}) {
    super();
    this.children = /* @__PURE__ */ new Map();
    this.childResults = [];
    this.completedCount = 0;
    this.expectedCount = 0;
    this.isFinalized = false;
    this.config = {
      aggregate: config.aggregate ?? ((results) => results),
      onChildComplete: config.onChildComplete ?? (() => {
      }),
      failFast: config.failFast ?? true
    };
  }
  /**
   * Add a child task - automatically wires up completion handling
   */
  addChild(child, index) {
    if (this.state.stage !== TaskStage.Pending) {
      if (this.state.stage === TaskStage.Aborted) {
        child.abort(this.state.reason);
      }
      return this;
    }
    const childIndex = index ?? this.expectedCount;
    this.expectedCount = Math.max(this.expectedCount, childIndex + 1);
    this.children.set(child, childIndex);
    child.wait(
      (result) => this.handleChildSuccess(child, result, childIndex),
      (error) => this.handleChildError(child, error, childIndex)
    );
    return this;
  }
  /**
   * Finalize - signals that no more children will be added
   * If no children were added, resolves immediately
   */
  finalize() {
    if (this.isFinalized) return this;
    this.isFinalized = true;
    if (this.expectedCount === 0) {
      this.resolve(this.config.aggregate([]));
    }
    return this;
  }
  handleChildSuccess(child, result, index) {
    if (this.state.stage !== TaskStage.Pending) return;
    this.childResults[index] = result;
    this.completedCount++;
    this.children.delete(child);
    const progressValue = this.config.onChildComplete(
      this.completedCount,
      this.expectedCount,
      result,
      index
    );
    if (progressValue !== void 0) {
      this.progress(progressValue);
    }
    if (this.completedCount === this.expectedCount) {
      const finalResult = this.config.aggregate(this.childResults);
      this.resolve(finalResult);
    }
  }
  handleChildError(child, error, index) {
    if (this.state.stage !== TaskStage.Pending) return;
    this.children.delete(child);
    if (this.config.failFast) {
      for (const [otherChild] of this.children) {
        otherChild.abort("Sibling task failed");
      }
      this.children.clear();
      this.fail(error);
    } else {
      this.childResults[index] = void 0;
      this.completedCount++;
      if (this.completedCount === this.expectedCount) {
        const finalResult = this.config.aggregate(this.childResults);
        this.resolve(finalResult);
      }
    }
  }
  /**
   * Override abort to propagate to all children
   */
  abort(reason) {
    for (const [child] of this.children) {
      child.abort(reason);
    }
    this.children.clear();
    super.abort(reason);
  }
  /**
   * Override reject to abort all children
   */
  reject(reason) {
    for (const [child] of this.children) {
      child.abort(reason);
    }
    this.children.clear();
    super.reject(reason);
  }
  /**
   * Get count of pending children
   */
  getPendingCount() {
    return this.children.size;
  }
  /**
   * Get count of completed children
   */
  getCompletedCount() {
    return this.completedCount;
  }
  // ============================================================================
  // Static Factory Methods
  // ============================================================================
  /**
   * Gather results from an array of tasks (progress-friendly).
   * (Formerly: all)
   */
  static gather(tasks) {
    const compound = new CompoundTask({
      aggregate: (results) => results,
      onChildComplete: (completed, total) => ({ completed, total })
    });
    tasks.forEach((task, index) => compound.addChild(task, index));
    compound.finalize();
    return compound;
  }
  /**
   * Gather into a Record indexed by number.
   * (Formerly: allIndexed)
   */
  static gatherIndexed(tasks) {
    const compound = new CompoundTask({
      aggregate: (results) => {
        const record = {};
        results.forEach((result, index) => {
          record[index] = result;
        });
        return record;
      },
      onChildComplete: (_completed, _total, result, index) => ({ page: index, result })
    });
    tasks.forEach((task, index) => compound.addChild(task, index));
    compound.finalize();
    return compound;
  }
  /**
   * Gather with custom aggregation config.
   * (Formerly: from)
   */
  static gatherFrom(tasks, config) {
    const compound = new CompoundTask(config);
    tasks.forEach((task, index) => compound.addChild(task, index));
    compound.finalize();
    return compound;
  }
  /**
   * Resolve with the first successful child; abort the rest.
   * (Formerly: race)
   */
  static first(tasks) {
    let resolved = false;
    const compound = new CompoundTask({
      aggregate: (results) => results[0],
      failFast: false
    });
    compound["handleChildSuccess"] = (child, result) => {
      if (!resolved) {
        resolved = true;
        for (const [otherChild] of compound["children"]) {
          if (otherChild !== child) otherChild.abort("Race won by sibling");
        }
        compound.resolve(result);
      }
    };
    tasks.forEach((task, index) => compound.addChild(task, index));
    compound.finalize();
    return compound;
  }
}
class TaskSequence {
  constructor(parentTask) {
    this.parentTask = parentTask;
    this.activeChild = null;
    this.disposed = false;
    const origAbort = parentTask.abort.bind(parentTask);
    parentTask.abort = (reason) => {
      var _a;
      this.disposed = true;
      (_a = this.activeChild) == null ? void 0 : _a.abort(reason);
      origAbort(reason);
    };
  }
  /**
   * Execute a child Task and return its result as a Promise.
   *
   * If the parent task has been aborted, throws `TaskAbortedError` immediately.
   * If the parent task is aborted while the child is running, the child is aborted too.
   */
  run(factory) {
    return new Promise((resolve, reject) => {
      if (this.disposed || this.parentTask.state.stage !== TaskStage.Pending) {
        reject(new TaskAbortedError("Sequence aborted"));
        return;
      }
      const child = factory();
      this.activeChild = child;
      child.wait(
        (result) => {
          this.activeChild = null;
          resolve(result);
        },
        (error) => {
          this.activeChild = null;
          if (error.type === "abort") {
            reject(new TaskAbortedError(error.reason));
          } else {
            reject(new TaskRejectedError(error.reason));
          }
        }
      );
    });
  }
  /**
   * Execute a child Task and return its result as a Promise,
   * forwarding the child's progress events to the parent task
   * through the provided mapper function.
   *
   * If the parent task has been aborted, throws `TaskAbortedError` immediately.
   * If the parent task is aborted while the child is running, the child is aborted too.
   */
  runWithProgress(factory, mapProgress) {
    return new Promise((resolve, reject) => {
      if (this.disposed || this.parentTask.state.stage !== TaskStage.Pending) {
        reject(new TaskAbortedError("Sequence aborted"));
        return;
      }
      const child = factory();
      this.activeChild = child;
      child.onProgress((p) => {
        this.parentTask.progress(mapProgress(p));
      });
      child.wait(
        (result) => {
          this.activeChild = null;
          resolve(result);
        },
        (error) => {
          this.activeChild = null;
          if (error.type === "abort") {
            reject(new TaskAbortedError(error.reason));
          } else {
            reject(new TaskRejectedError(error.reason));
          }
        }
      );
    });
  }
  /**
   * Execute an async function body that uses `run()` / `runWithProgress()`,
   * automatically handling abort and error routing to the parent task.
   *
   * - If the body throws `TaskAbortedError`, it is silently ignored
   *   (the parent task was already aborted via the abort override).
   * - If the body throws `TaskRejectedError` (from a child task rejection
   *   via `run()` / `runWithProgress()`), its `.reason` is forwarded directly
   *   to the parent task, bypassing `mapError`.
   * - Any other thrown error is mapped through `mapError` and used to
   *   reject the parent task. This handles unexpected runtime exceptions
   *   in the async body itself.
   * - On success, the body is responsible for calling `parentTask.resolve()`.
   */
  execute(fn, mapError) {
    fn().catch((err) => {
      if (err instanceof TaskAbortedError) return;
      if (err instanceof TaskRejectedError) {
        this.parentTask.reject(err.reason);
        return;
      }
      this.parentTask.reject(mapError(err));
    });
  }
}
function ignore() {
}
export {
  AP_MODE_DOWN,
  AP_MODE_NORMAL,
  AP_MODE_ROLLOVER,
  AllLogger,
  AppearanceMode,
  CompoundTask,
  ConsoleLogger,
  FontCharset,
  LevelLogger,
  LogLevel,
  MatchFlag,
  MixedBlendMode,
  MixedStandardFont,
  MixedTextAlignment,
  NoopLogger,
  PDF_FORM_FIELD_FLAG,
  PDF_FORM_FIELD_TYPE,
  PdfActionType,
  PdfAnnotationBorderStyle,
  PdfAnnotationColorType,
  PdfAnnotationFlagName,
  PdfAnnotationFlags,
  PdfAnnotationIcon,
  PdfAnnotationLineEnding,
  PdfAnnotationObjectStatus,
  PdfAnnotationReplyType,
  PdfAnnotationState,
  PdfAnnotationStateModel,
  PdfAnnotationSubtype,
  PdfAnnotationSubtypeName,
  PdfBlendMode,
  PdfBomOrZwnbsp,
  PdfEngineFeature,
  PdfEngineOperation,
  PdfErrorCode,
  PdfNonCharacterFFFE,
  PdfNonCharacterFFFF,
  PdfPageFlattenFlag,
  PdfPageFlattenResult,
  PdfPageObjectType,
  PdfPermissionFlag,
  PdfSegmentObjectType,
  PdfSoftHyphenMarker,
  PdfStampFit,
  PdfStandardFont,
  PdfStandardFontFamily,
  PdfTaskHelper,
  PdfTextAlignment,
  PdfTrappedStatus,
  PdfUnwantedTextMarkers,
  PdfUnwantedTextRegex,
  PdfVerticalAlignment,
  PdfWordJoiner,
  PdfZeroWidthSpace,
  PdfZoomMode,
  PerfLogger,
  PermissionDeniedError,
  Rotation,
  STANDARD_FONT_FAMILIES,
  Task,
  TaskAbortedError,
  TaskRejectedError,
  TaskSequence,
  TaskStage,
  blendModeLabel,
  blendModeSelectOptions,
  blendModeToCss,
  blendModeValues,
  boundingRect,
  boundingRectOrEmpty,
  buildPermissions,
  buildUserToDeviceMatrix,
  calculateAngle,
  calculateDegree,
  calculateRotatedRectAABB,
  calculateRotatedRectAABBAroundPoint,
  combinePdfColorWithAlpha,
  combineWebColorWithOpacity,
  compareSearchTarget,
  cssToBlendMode,
  cssToTextAlignment,
  dateToPdfDate,
  deserializeLogger,
  expandRect,
  extractPdfColor,
  extractWebOpacity,
  flagsToNames,
  getBlendModeInfo,
  getContrastStrokeColor,
  getRectCenter,
  getStandardFontDescriptor,
  getTextAlignmentInfo,
  ignore,
  inferRotationCenterFromRects,
  isUuidV4,
  makeStandardFont,
  namesToFlags,
  normalizeAngle,
  pdfAlphaColorToWebAlphaColor,
  pdfAlphaToWebOpacity,
  pdfColorToWebColor,
  pdfDateToDate,
  quadToRect,
  rectEquals,
  rectFromPoints,
  rectToQuad,
  reduceBlendModes,
  reduceStandardFonts,
  reduceTextAlignments,
  restoreOffset,
  restorePosition,
  restoreRect,
  rotateAndTranslatePoint,
  rotatePointAround,
  rotatePosition,
  rotateRect,
  rotateVertices,
  scalePosition,
  scaleRect,
  serializeLogger,
  standardFontCss,
  standardFontCssProperties,
  standardFontFamily,
  standardFontFamilyLabel,
  standardFontFamilySelectOptions,
  standardFontIsBold,
  standardFontIsItalic,
  standardFontLabel,
  stripPdfUnwantedMarkers,
  swap,
  textAlignmentLabel,
  textAlignmentSelectOptions,
  textAlignmentToCss,
  toIntPos,
  toIntRect,
  toIntSize,
  transformPosition,
  transformRect,
  transformSize,
  uiBlendModeDisplay,
  unionFlags,
  uuidV4,
  webAlphaColorToPdfAlphaColor,
  webColorToPdfColor,
  webOpacityToPdfAlpha
};
//# sourceMappingURL=index.js.map
