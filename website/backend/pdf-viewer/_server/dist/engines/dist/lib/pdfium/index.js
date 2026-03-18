import { B, F, P, a, R, c, b, d, i, r, e } from "../../direct-engine-D-Jf9yyY.js";
import { I, b as b2, c as c2, a as a2 } from "../../browser-BISJ9naB.js";
import { P as P2 } from "../../pdf-engine-ZvReuoDb.js";
import { FontCharset } from "@embedpdf/models";
import { FontCharset as FontCharset2 } from "@embedpdf/models";
import { fonts as fonts$6 } from "@embedpdf/fonts-jp";
import { fonts as fonts$5 } from "@embedpdf/fonts-kr";
import { fonts as fonts$4 } from "@embedpdf/fonts-sc";
import { fonts as fonts$3 } from "@embedpdf/fonts-tc";
import { fonts as fonts$2 } from "@embedpdf/fonts-arabic";
import { fonts as fonts$1 } from "@embedpdf/fonts-hebrew";
import { fonts } from "@embedpdf/fonts-latin";
import { createPdfiumEngine } from "./web/worker-engine.js";
function buildCdnUrls(version = "latest") {
  return {
    jp: `https://cdn.jsdelivr.net/npm/@embedpdf/fonts-jp@${version}/fonts`,
    kr: `https://cdn.jsdelivr.net/npm/@embedpdf/fonts-kr@${version}/fonts`,
    sc: `https://cdn.jsdelivr.net/npm/@embedpdf/fonts-sc@${version}/fonts`,
    tc: `https://cdn.jsdelivr.net/npm/@embedpdf/fonts-tc@${version}/fonts`,
    arabic: `https://cdn.jsdelivr.net/npm/@embedpdf/fonts-arabic@${version}/fonts`,
    hebrew: `https://cdn.jsdelivr.net/npm/@embedpdf/fonts-hebrew@${version}/fonts`,
    latin: `https://cdn.jsdelivr.net/npm/@embedpdf/fonts-latin@${version}/fonts`
  };
}
function toFontVariants(fonts2, baseUrl) {
  return fonts2.map((f) => ({
    url: `${baseUrl}/${f.file}`,
    weight: f.weight,
    italic: f.italic
  }));
}
function buildCdnFontConfig(urls) {
  return {
    fonts: {
      [FontCharset.SHIFTJIS]: toFontVariants(fonts$6, urls.jp),
      [FontCharset.HANGEUL]: toFontVariants(fonts$5, urls.kr),
      [FontCharset.GB2312]: toFontVariants(fonts$4, urls.sc),
      [FontCharset.CHINESEBIG5]: toFontVariants(fonts$3, urls.tc),
      [FontCharset.ARABIC]: toFontVariants(fonts$2, urls.arabic),
      [FontCharset.HEBREW]: toFontVariants(fonts$1, urls.hebrew),
      [FontCharset.CYRILLIC]: toFontVariants(fonts, urls.latin),
      [FontCharset.GREEK]: toFontVariants(fonts, urls.latin),
      [FontCharset.VIETNAMESE]: toFontVariants(fonts, urls.latin)
    }
  };
}
const FONT_CDN_URLS = buildCdnUrls("latest");
const cdnFontConfig = buildCdnFontConfig(FONT_CDN_URLS);
function createCdnFontConfig(version = "latest") {
  return buildCdnFontConfig(buildCdnUrls(version));
}
const DEFAULT_PDFIUM_WASM_URL = "https://cdn.jsdelivr.net/npm/@embedpdf/pdfium@2.9.0/dist/pdfium.wasm";
export {
  B as BitmapFormat,
  DEFAULT_PDFIUM_WASM_URL,
  FONT_CDN_URLS,
  FontCharset2 as FontCharset,
  F as FontFallbackManager,
  I as ImageConverterError,
  P2 as PdfEngine,
  P as PdfiumErrorCode,
  a as PdfiumNative,
  R as RenderFlag,
  b2 as browserImageDataToBlobConverter,
  cdnFontConfig,
  c as computeFormDrawParams,
  createCdnFontConfig,
  c2 as createHybridImageConverter,
  b as createNodeFontLoader,
  d as createPdfiumDirectEngine,
  createPdfiumEngine as createPdfiumWorkerEngine,
  a2 as createWorkerPoolImageConverter,
  i as isValidCustomKey,
  r as readArrayBuffer,
  e as readString
};
//# sourceMappingURL=index.js.map
