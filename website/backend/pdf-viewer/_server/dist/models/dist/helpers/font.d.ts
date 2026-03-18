import { PdfStandardFont } from '../pdf';
/**
 * Logical families of the 14 “Standard PDF” fonts.
 */
export declare enum PdfStandardFontFamily {
    Courier = "Courier",
    Helvetica = "Helvetica",
    Times = "Times",
    Symbol = "Symbol",
    ZapfDingbats = "ZapfDingbats",
    Unknown = "Unknown"
}
/** UI sentinel when multiple different fonts are selected at once.            */
export declare const MixedStandardFont: unique symbol;
export type UiStandardFontValue = PdfStandardFont | typeof MixedStandardFont;
interface StandardFontDescriptor {
    /** Enum value as returned by PDFium. */
    id: PdfStandardFont;
    /** Logical family (for the left dropdown).   */
    family: PdfStandardFontFamily;
    /** `true` ⇢ weight ≥ 700.                    */
    bold: boolean;
    /** `true` ⇢ italic / oblique.                */
    italic: boolean;
    /** Human-readable label (“Helvetica Bold”).  */
    label: string;
    /** CSS `font-family` fallback list.          */
    css: string;
}
/** Get the descriptor for a given enum (falls back to Unknown). */
export declare function getStandardFontDescriptor(font: PdfStandardFont): StandardFontDescriptor;
/** Convert enum → family. */
export declare function standardFontFamily(font: PdfStandardFont): PdfStandardFontFamily;
/** Is font bold? */
export declare function standardFontIsBold(font: PdfStandardFont): boolean;
/** Is font italic / oblique? */
export declare function standardFontIsItalic(font: PdfStandardFont): boolean;
/**
 * Convert **family + (bold, italic)** back to the enum.
 * Returns `undefined` when the combination doesn’t exist
 * (e.g. “Symbol + bold” is not a valid Standard-14 face).
 */
export declare function makeStandardFont(family: PdfStandardFontFamily, { bold, italic }: {
    bold: boolean;
    italic: boolean;
}): PdfStandardFont;
/** Keep the helpers you already added: */
export declare function standardFontLabel(font: PdfStandardFont): string;
export declare function standardFontCss(font: PdfStandardFont): string;
/**
 * CSS properties needed to render a standard PDF font correctly across all
 * platforms.  Bold / italic are expressed via `fontWeight` and `fontStyle`
 * instead of being baked into the `fontFamily` name (e.g. "Helvetica-Bold"),
 * which doesn't exist as a system font on Windows/Linux.
 */
export interface StandardFontCssProperties {
    fontFamily: string;
    fontWeight: 'normal' | 'bold';
    fontStyle: 'normal' | 'italic';
}
/** Resolve a `PdfStandardFont` enum to cross-platform CSS properties. */
export declare function standardFontCssProperties(font: PdfStandardFont): StandardFontCssProperties;
/** Family dropdown options (“Helvetica”, “Times”…). */
export declare const standardFontFamilySelectOptions: {
    value: PdfStandardFontFamily.Courier | PdfStandardFontFamily.Helvetica | PdfStandardFontFamily.Times | PdfStandardFontFamily.Symbol | PdfStandardFontFamily.ZapfDingbats;
    label: PdfStandardFontFamily.Courier | PdfStandardFontFamily.Helvetica | PdfStandardFontFamily.Times | PdfStandardFontFamily.Symbol | PdfStandardFontFamily.ZapfDingbats;
}[];
/**
 * Reduce multiple enums → single value or Mixed sentinel
 * (handy for multi-selection editing UIs).
 */
export declare function reduceStandardFonts(fonts: readonly PdfStandardFont[]): UiStandardFontValue;
export declare const STANDARD_FONT_FAMILIES: readonly PdfStandardFontFamily[];
/** Friendly label for each family (could also live in the descriptor list) */
export declare function standardFontFamilyLabel(fam: PdfStandardFontFamily): string;
export {};
