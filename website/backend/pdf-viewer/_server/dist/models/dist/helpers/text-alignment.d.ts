import { PdfTextAlignment } from '../pdf';
/** Extra UI sentinel for “mixed values”. */
export declare const MixedTextAlignment: unique symbol;
export type UiTextAlignmentValue = PdfTextAlignment | typeof MixedTextAlignment;
export type CssTextAlign = 'left' | 'center' | 'right';
interface TextAlignmentInfo {
    id: PdfTextAlignment;
    label: string;
    css: CssTextAlign;
}
/** Get descriptor (falls back to Left if unknown). */
export declare function getTextAlignmentInfo(alignment: PdfTextAlignment): TextAlignmentInfo;
export declare function textAlignmentToCss(alignment: PdfTextAlignment): CssTextAlign;
export declare function cssToTextAlignment(value: CssTextAlign): PdfTextAlignment | undefined;
export declare function textAlignmentLabel(alignment: PdfTextAlignment): string;
export declare function reduceTextAlignments(values: readonly PdfTextAlignment[]): UiTextAlignmentValue;
export declare const textAlignmentSelectOptions: {
    value: PdfTextAlignment;
    label: string;
}[];
export {};
