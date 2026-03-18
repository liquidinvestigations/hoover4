import { FontCharset, Logger } from '@embedpdf/models';
import { WrappedPdfiumModule } from '@embedpdf/pdfium';
export { FontCharset };
/**
 * A single font variant with weight and italic information
 */
export interface FontVariant {
    url: string;
    weight?: number;
    italic?: boolean;
}
/**
 * Font entry can be:
 * - A simple string URL (uses weight 400, non-italic)
 * - A single FontVariant
 * - An array of FontVariants for multiple weights/styles
 */
export type FontEntry = string | FontVariant | FontVariant[];
/**
 * Custom font loader function type
 * Used to load font data from custom sources (e.g., file system in Node.js)
 *
 * @param fontPath - The font path/URL to load
 * @returns The font data as Uint8Array, or null if loading failed
 */
export type FontLoader = (fontPath: string) => Uint8Array | null;
/**
 * Configuration for fallback fonts
 * Maps charset values to font URLs or font variant configurations
 */
export interface FontFallbackConfig {
    /**
     * Map of charset to font entry
     * Can be a simple URL string, a FontVariant, or an array of FontVariants
     */
    fonts: Partial<Record<FontCharset, FontEntry>>;
    /**
     * Optional default font entry for unspecified charsets
     */
    defaultFont?: FontEntry;
    /**
     * Base URL to prepend to relative font URLs (browser)
     */
    baseUrl?: string;
    /**
     * Custom font loader function
     *
     * When provided, this function is called to load font data instead of
     * the default XMLHttpRequest-based loader. This is useful for:
     * - Node.js environments (use fs.readFileSync)
     * - Custom caching strategies
     * - Loading from alternative sources
     *
     * @example Node.js usage:
     * ```typescript
     * import { readFileSync } from 'fs';
     * import { join } from 'path';
     *
     * const fontFallback = {
     *   fonts: { [FontCharset.SHIFTJIS]: 'NotoSansJP-Regular.otf' },
     *   fontLoader: (fontPath) => {
     *     try {
     *       return new Uint8Array(readFileSync(join('/fonts', fontPath)));
     *     } catch {
     *       return null;
     *     }
     *   },
     * };
     * ```
     */
    fontLoader?: FontLoader;
}
/**
 * Font fallback manager for PDFium - Pure TypeScript Implementation
 *
 * This class handles on-demand font loading when PDFium encounters
 * text that requires fonts not embedded in the PDF.
 *
 * The implementation creates the FPDF_SYSFONTINFO struct entirely
 * in JavaScript using Emscripten's addFunction API.
 */
export declare class FontFallbackManager {
    private readonly fontConfig;
    private readonly logger;
    private readonly fontHandles;
    private readonly fontCache;
    private nextHandleId;
    private module;
    private enabled;
    private structPtr;
    private releaseFnPtr;
    private enumFontsFnPtr;
    private mapFontFnPtr;
    private getFontFnPtr;
    private getFontDataFnPtr;
    private getFaceNameFnPtr;
    private getFontCharsetFnPtr;
    private deleteFontFnPtr;
    constructor(config: FontFallbackConfig, logger?: Logger);
    /**
     * Initialize the font fallback system and attach to PDFium module
     */
    initialize(module: WrappedPdfiumModule): void;
    /**
     * Disable the font fallback system and clean up resources
     */
    disable(): void;
    /**
     * Clean up allocated resources
     */
    private cleanup;
    /**
     * Check if font fallback is enabled
     */
    isEnabled(): boolean;
    /**
     * Get statistics about font loading
     */
    getStats(): {
        handleCount: number;
        cacheSize: number;
        cachedUrls: string[];
    };
    /**
     * Pre-load fonts for specific charsets (optional optimization)
     * This can be called to warm the cache before rendering
     */
    preloadFonts(charsets: FontCharset[]): Promise<void>;
    /**
     * MapFont - called by PDFium when it needs a font
     */
    private mapFont;
    /**
     * GetFontData - called by PDFium to get font bytes
     */
    private getFontData;
    /**
     * DeleteFont - called by PDFium when done with a font
     */
    private deleteFont;
    /**
     * Find the best matching font variant for the given parameters
     */
    private findBestFontMatch;
    /**
     * Normalize a FontEntry to an array of FontVariants
     */
    private normalizeToVariants;
    /**
     * Select the best matching variant based on weight and italic
     * Uses CSS font matching algorithm principles:
     * 1. Exact italic match preferred
     * 2. Closest weight (with bias toward bolder for weights >= 400)
     */
    private selectBestVariant;
    /**
     * Get font URL for a charset (backward compatible helper)
     */
    private getFontUrlForCharset;
    /**
     * Fetch font data synchronously
     * Uses custom fontLoader if provided, otherwise falls back to XMLHttpRequest (browser)
     */
    private fetchFontSync;
    /**
     * Fetch font data asynchronously (for preloading)
     * Uses custom fontLoader if provided, otherwise falls back to fetch API
     */
    private fetchFontAsync;
}
/**
 * Create a file system font loader for Node.js environments
 *
 * This helper creates a FontLoader function that reads fonts from the file system.
 * It requires Node.js's `fs` and `path` modules to be passed in to avoid
 * bundling issues in browser environments.
 *
 * @param fs - Node.js fs module (or compatible)
 * @param path - Node.js path module (or compatible)
 * @param basePath - Base directory path where fonts are located
 * @returns A FontLoader function for use in FontFallbackConfig
 *
 * @example
 * ```typescript
 * import { readFileSync } from 'fs';
 * import { join } from 'path';
 * import { createNodeFontLoader, FontCharset } from '@embedpdf/engines/pdfium';
 *
 * const fontLoader = createNodeFontLoader(
 *   { readFileSync },
 *   { join },
 *   '/path/to/fonts'
 * );
 *
 * const fontFallback = {
 *   fonts: {
 *     [FontCharset.SHIFTJIS]: 'NotoSansJP-Regular.otf',
 *   },
 *   fontLoader,
 * };
 * ```
 */
export declare function createNodeFontLoader(fs: {
    readFileSync: (path: string) => Uint8Array | ArrayBufferLike;
}, path: {
    join: (...paths: string[]) => string;
}, basePath: string): FontLoader;
