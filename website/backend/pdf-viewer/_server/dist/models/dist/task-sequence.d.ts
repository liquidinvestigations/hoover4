import { Task } from './task';
/**
 * Utility for composing sequential Task operations within an async function,
 * while preserving abort propagation and optional progress forwarding.
 *
 * Bridges the gap between the Task "push" model (callbacks, abort, progress)
 * and the async/await "pull" model, without losing Task benefits.
 *
 * @example
 * ```ts
 * function doWork(): Task<Result, MyError, MyProgress> {
 *   const task = new Task<Result, MyError, MyProgress>();
 *   const seq = new TaskSequence(task);
 *
 *   seq.execute(
 *     async () => {
 *       const data = await seq.run(() => fetchDataAsTask());
 *       const result = await seq.runWithProgress(
 *         () => processAsTask(data),
 *         (childProgress) => ({ stage: 'processing', ...childProgress }),
 *       );
 *       task.resolve(result);
 *     },
 *     (err) => ({ type: 'failed', message: String(err) }),
 *   );
 *
 *   return task;
 * }
 * ```
 *
 * @public
 */
export declare class TaskSequence<TError, TProgress> {
    private parentTask;
    private activeChild;
    private disposed;
    constructor(parentTask: Task<any, TError, TProgress>);
    /**
     * Execute a child Task and return its result as a Promise.
     *
     * If the parent task has been aborted, throws `TaskAbortedError` immediately.
     * If the parent task is aborted while the child is running, the child is aborted too.
     */
    run<R>(factory: () => Task<R, any, any>): Promise<R>;
    /**
     * Execute a child Task and return its result as a Promise,
     * forwarding the child's progress events to the parent task
     * through the provided mapper function.
     *
     * If the parent task has been aborted, throws `TaskAbortedError` immediately.
     * If the parent task is aborted while the child is running, the child is aborted too.
     */
    runWithProgress<R, CP>(factory: () => Task<R, any, CP>, mapProgress: (childProgress: CP) => TProgress): Promise<R>;
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
    execute(fn: () => Promise<void>, mapError: (err: unknown) => TError): void;
}
