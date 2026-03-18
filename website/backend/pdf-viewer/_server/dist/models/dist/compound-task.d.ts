import { Task } from './task';
/**
 * Configuration for how CompoundTask should aggregate results
 */
export interface CompoundTaskConfig<R, CR, P> {
    /**
     * How to aggregate child results into final result
     * Default: returns array of child results
     */
    aggregate?: (childResults: CR[]) => R;
    /**
     * Called when each child completes (for progress tracking)
     * Return progress value to emit
     */
    onChildComplete?: (completed: number, total: number, result: CR, index: number) => P | void;
    /**
     * Whether to fail immediately on first error
     * Default: true (like Promise.all)
     */
    failFast?: boolean;
}
/**
 * A task that manages multiple child tasks with automatic completion.
 *
 * Key features:
 * - Auto-resolves when all children complete
 * - Auto-aggregates results
 * - Auto-tracks progress
 * - Auto-cleans up completed children
 * - Propagates abort to all children
 */
export declare class CompoundTask<R, D, P = unknown> extends Task<R, D, P> {
    private children;
    private childResults;
    private completedCount;
    private expectedCount;
    private config;
    private isFinalized;
    constructor(config?: CompoundTaskConfig<R, any, P>);
    /**
     * Add a child task - automatically wires up completion handling
     */
    addChild<CR>(child: Task<CR, any, any>, index?: number): this;
    /**
     * Finalize - signals that no more children will be added
     * If no children were added, resolves immediately
     */
    finalize(): this;
    private handleChildSuccess;
    private handleChildError;
    /**
     * Override abort to propagate to all children
     */
    abort(reason: D): void;
    /**
     * Override reject to abort all children
     */
    reject(reason: D): void;
    /**
     * Get count of pending children
     */
    getPendingCount(): number;
    /**
     * Get count of completed children
     */
    getCompletedCount(): number;
    /**
     * Gather results from an array of tasks (progress-friendly).
     * (Formerly: all)
     */
    static gather<T extends Task<any, any, any>>(tasks: T[]): CompoundTask<{
        [K in keyof T]: T[K] extends Task<infer R, any, any> ? R : never;
    }[], any, {
        completed: number;
        total: number;
    }>;
    /**
     * Gather into a Record indexed by number.
     * (Formerly: allIndexed)
     */
    static gatherIndexed<R, D>(tasks: Task<R, D, any>[]): CompoundTask<Record<number, R>, D, {
        page: number;
        result: R;
    }>;
    /**
     * Gather with custom aggregation config.
     * (Formerly: from)
     */
    static gatherFrom<R, CR, D, P>(tasks: Task<CR, D, any>[], config: CompoundTaskConfig<R, CR, P>): CompoundTask<R, D, P>;
    /**
     * Resolve with the first successful child; abort the rest.
     * (Formerly: race)
     */
    static first<T extends Task<any, any, any>>(tasks: T[]): CompoundTask<T extends Task<infer R, any, any> ? R : never, T extends Task<any, infer D, any> ? D : never, unknown>;
}
