import { Logger, PdfEngine, PdfEngineMethodArgs, PdfEngineMethodName, PdfEngineMethodReturnType, TaskReturn } from '@embedpdf/models';
/**
 * Request body that represent method calls of PdfEngine, it contains the
 * method name and arguments
 */
export type PdfEngineMethodRequestBody = {
    [P in PdfEngineMethodName]: {
        name: P;
        args: PdfEngineMethodArgs<P>;
    };
}[PdfEngineMethodName];
/**
 * Request body that represent method calls of PdfEngine, it contains the
 * method name and arguments
 */
export type SpecificExecuteRequest<M extends PdfEngineMethodName> = {
    id: string;
    type: 'ExecuteRequest';
    data: {
        name: M;
        args: PdfEngineMethodArgs<M>;
    };
};
/**
 * Response body that represent return value of PdfEngine
 */
export type PdfEngineMethodResponseBody = {
    [P in PdfEngineMethodName]: TaskReturn<PdfEngineMethodReturnType<P>>;
}[PdfEngineMethodName];
/**
 * Request that abort the specified task
 */
export interface AbortRequest {
    /**
     * message id
     */
    id: string;
    /**
     * request type
     */
    type: 'AbortRequest';
}
/**
 * Request that execute pdf engine method
 */
export interface ExecuteRequest {
    /**
     * message id
     */
    id: string;
    /**
     * request type
     */
    type: 'ExecuteRequest';
    /**
     * request body
     */
    data: PdfEngineMethodRequestBody;
}
/**
 * Response that execute pdf engine method
 */
export interface ExecuteResponse {
    /**
     * message id
     */
    id: string;
    /**
     * response type
     */
    type: 'ExecuteResponse';
    /**
     * response body
     */
    data: PdfEngineMethodResponseBody;
}
/**
 * Response that indicate progress of the task
 */
export interface ExecuteProgress<T = unknown> {
    /**
     * message id
     */
    id: string;
    /**
     * response type
     */
    type: 'ExecuteProgress';
    /**
     * response body
     */
    data: T;
}
/**
 * Response that indicate engine is ready
 */
export interface ReadyResponse {
    /**
     * message id
     */
    id: string;
    /**
     * response type
     */
    type: 'ReadyResponse';
}
/**
 * Request type
 */
export type Request = ExecuteRequest | AbortRequest;
/**
 * Response type
 */
export type Response = ExecuteResponse | ReadyResponse | ExecuteProgress;
/**
 * Pdf engine runner, it will execute pdf engine based on the request it received and
 * send back the response with post message
 */
export declare class EngineRunner {
    logger: Logger;
    engine: PdfEngine | undefined;
    /**
     * Create instance of EngineRunnder
     * @param logger - logger instance
     */
    constructor(logger?: Logger);
    /**
     * Listening on post message
     */
    listen(): void;
    /**
     * Handle post message
     */
    handle(evt: MessageEvent<Request>): void;
    /**
     * Send the ready response when pdf engine is ready
     * @returns
     *
     * @protected
     */
    ready(): void;
    /**
     * Execute the request
     * @param request - request that represent the pdf engine call
     * @returns
     *
     * @protected
     */
    execute: (request: ExecuteRequest) => Promise<void>;
    /**
     * Send back the response
     * @param response - response that needs sent back
     *
     * @protected
     */
    respond(response: Response): void;
}
