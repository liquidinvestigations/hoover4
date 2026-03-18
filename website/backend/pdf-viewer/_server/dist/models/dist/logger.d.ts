/**
 * logger for logging
 *
 * @public
 */
export interface Logger {
    /**
     * Check if a log level is enabled
     * @param level - log level to check
     * @returns true if the level is enabled
     *
     * @public
     */
    isEnabled: (level: 'debug' | 'info' | 'warn' | 'error') => boolean;
    /**
     * Log debug message
     * @param source - source of log
     * @param category - category of log
     * @param args - parameters of log
     * @returns
     *
     * @public
     */
    debug: (source: string, category: string, ...args: any) => void;
    /**
     * Log infor message
     * @param source - source of log
     * @param category - category of log
     * @param args - parameters of log
     * @returns
     *
     * @public
     */
    info: (source: string, category: string, ...args: any) => void;
    /**
     * Log warning message
     * @param source - source of log
     * @param category - category of log
     * @param args - parameters of log
     * @returns
     *
     * @public
     */
    warn: (source: string, category: string, ...args: any) => void;
    /**
     * Log error message
     * @param source - source of log
     * @param category - category of log
     * @param args - parameters of log
     * @returns
     *
     * @public
     */
    error: (source: string, category: string, ...args: any) => void;
    /**
     * Log performance log
     * @param source - source of log
     * @param category - category of log
     * @param event - event of log
     * @param phase - event phase of log
     * @param args - parameters of log
     * @returns
     *
     * @public
     */
    perf: (source: string, category: string, event: string, phase: 'Begin' | 'End', ...args: any) => void;
}
/**
 * Logger that log nothing, it will ignore all the logs
 *
 * @public
 */
export declare class NoopLogger implements Logger {
    /** {@inheritDoc Logger.isEnabled} */
    isEnabled(): boolean;
    /** {@inheritDoc Logger.debug} */
    debug(): void;
    /** {@inheritDoc Logger.info} */
    info(): void;
    /** {@inheritDoc Logger.warn} */
    warn(): void;
    /** {@inheritDoc Logger.error} */
    error(): void;
    /** {@inheritDoc Logger.perf} */
    perf(): void;
}
/**
 * Logger that use console as the output
 *
 * @public
 */
export declare class ConsoleLogger implements Logger {
    /** {@inheritDoc Logger.isEnabled} */
    isEnabled(): boolean;
    /** {@inheritDoc Logger.debug} */
    debug(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.info} */
    info(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.warn} */
    warn(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.error} */
    error(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.perf} */
    perf(source: string, category: string, event: string, phase: 'Begin' | 'End', ...args: any): void;
}
/**
 * Level of log
 *
 * @public
 */
export declare enum LogLevel {
    Debug = 0,
    Info = 1,
    Warn = 2,
    Error = 3
}
/**
 * Logger that support filtering by log level
 *
 * @public
 */
export declare class LevelLogger implements Logger {
    private logger;
    private level;
    /**
     * create new LevelLogger
     * @param logger - the original logger
     * @param level - log level that used for filtering, all logs lower than this level will be filtered out
     */
    constructor(logger: Logger, level: LogLevel);
    /** {@inheritDoc Logger.isEnabled} */
    isEnabled(level: 'debug' | 'info' | 'warn' | 'error'): boolean;
    /** {@inheritDoc Logger.debug} */
    debug(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.info} */
    info(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.warn} */
    warn(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.error} */
    error(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.perf} */
    perf(source: string, category: string, event: string, phase: 'Begin' | 'End', ...args: any): void;
}
/**
 * Logger for performance tracking
 *
 * @public
 */
export declare class PerfLogger implements Logger {
    private marks;
    /**
     * create new PerfLogger
     */
    constructor();
    /** {@inheritDoc Logger.isEnabled} */
    isEnabled(): boolean;
    /** {@inheritDoc Logger.debug} */
    debug(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.info} */
    info(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.warn} */
    warn(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.error} */
    error(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.perf} */
    perf(source: string, category: string, event: string, phase: 'Begin' | 'End', identifier: string, ...args: any): void;
}
/**
 * Logger that will track and call child loggers
 *
 * @public
 */
export declare class AllLogger implements Logger {
    private loggers;
    /**
     * create new PerfLogger
     */
    constructor(loggers: Logger[]);
    /** {@inheritDoc Logger.isEnabled} */
    isEnabled(level: 'debug' | 'info' | 'warn' | 'error'): boolean;
    /** {@inheritDoc Logger.debug} */
    debug(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.info} */
    info(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.warn} */
    warn(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.error} */
    error(source: string, category: string, ...args: any): void;
    /** {@inheritDoc Logger.perf} */
    perf(source: string, category: string, event: string, phase: 'Begin' | 'End', ...args: any): void;
}
