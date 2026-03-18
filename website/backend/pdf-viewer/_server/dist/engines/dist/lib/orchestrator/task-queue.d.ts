import { Task, Logger } from '@embedpdf/models';
export declare enum Priority {
    CRITICAL = 3,
    HIGH = 2,
    MEDIUM = 1,
    LOW = 0
}
/**
 * Extract result type from Task
 */
export type ExtractTaskResult<T> = T extends Task<infer R, any, any> ? R : never;
/**
 * Extract error type from Task
 */
export type ExtractTaskError<T> = T extends Task<any, infer D, any> ? D : never;
/**
 * Extract progress type from Task
 */
export type ExtractTaskProgress<T> = T extends Task<any, any, infer P> ? P : never;
export interface QueuedTask<T extends Task<any, any, any>> {
    id: string;
    priority: Priority;
    meta?: Record<string, unknown>;
    executeFactory: () => T;
    cancelled?: boolean;
}
export interface EnqueueOptions {
    priority?: Priority;
    meta?: Record<string, unknown>;
    fifo?: boolean;
}
export type TaskComparator = (a: QueuedTask<any>, b: QueuedTask<any>) => number;
export type TaskRanker = (task: QueuedTask<any>) => number;
export interface WorkerTaskQueueOptions {
    concurrency?: number;
    comparator?: TaskComparator;
    ranker?: TaskRanker;
    onIdle?: () => void;
    maxQueueSize?: number;
    autoStart?: boolean;
    logger?: Logger;
}
export declare class WorkerTaskQueue {
    private queue;
    private running;
    private resultTasks;
    private logger;
    private opts;
    constructor(options?: WorkerTaskQueueOptions);
    setComparator(comparator?: TaskComparator): void;
    setRanker(ranker?: TaskRanker): void;
    size(): number;
    inFlight(): number;
    isIdle(): boolean;
    drain(): Promise<void>;
    private idleListeners;
    private notifyIdle;
    private onIdle;
    private offIdle;
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
    enqueue<T extends Task<any, any, any>>(taskDef: {
        execute: () => T;
        meta?: Record<string, unknown>;
    }, options?: EnqueueOptions): T;
    /**
     * Cancel/remove a task from the queue
     */
    private cancel;
    private kick;
    private process;
    private sortQueue;
    private defaultRank;
    private generateId;
    private extractTime;
}
