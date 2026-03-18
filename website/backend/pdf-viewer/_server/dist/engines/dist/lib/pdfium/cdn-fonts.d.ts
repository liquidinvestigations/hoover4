import { FontFallbackConfig } from './font-fallback';
/**
 * CDN base URLs for EmbedPDF font packages hosted on jsDelivr (using @latest)
 */
export declare const FONT_CDN_URLS: {
    jp: string;
    kr: string;
    sc: string;
    tc: string;
    arabic: string;
    hebrew: string;
    latin: string;
};
/**
 * Default CDN font configuration using @embedpdf/fonts-* packages from jsDelivr
 *
 * This is the default configuration for browser-based worker engines.
 * Fonts are loaded on-demand from jsDelivr when PDFium needs them.
 *
 * Uses @latest to always get the newest version of font packages.
 *
 * Included packages:
 * - @embedpdf/fonts-jp: Japanese (7 weights: Thin to Black)
 * - @embedpdf/fonts-kr: Korean (7 weights: Thin to Black)
 * - @embedpdf/fonts-sc: Simplified Chinese (5 weights: Light to Bold)
 * - @embedpdf/fonts-tc: Traditional Chinese (7 weights: Thin to Black)
 * - @embedpdf/fonts-arabic: Arabic (Regular, Bold)
 * - @embedpdf/fonts-hebrew: Hebrew (Regular, Bold)
 * - @embedpdf/fonts-latin: Latin/Cyrillic/Greek/Vietnamese (9 weights with italics)
 */
export declare const cdnFontConfig: FontFallbackConfig;
/**
 * Create a CDN font config with a specific version
 *
 * Use this if you need to pin to a specific version for stability.
 *
 * @param version - Version string (e.g., '1.0.0', '1', 'latest')
 * @returns FontFallbackConfig with versioned CDN URLs
 *
 * @example
 * ```typescript
 * // Pin to specific version
 * const fontConfig = createCdnFontConfig('1.0.0');
 *
 * // Use major version (recommended for stability)
 * const fontConfig = createCdnFontConfig('1');
 * ```
 */
export declare function createCdnFontConfig(version?: string): FontFallbackConfig;
export type { FontFallbackConfig };
