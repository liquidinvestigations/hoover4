import * as $ from "svelte/internal/client";
import { setContext, getContext } from "svelte";
import { ignore } from "@embedpdf/models";
import "svelte/internal/disclose-version";
const PDF_ENGINE_CONTEXT_KEY = Symbol("pdfEngineContext");
function setPdfEngineContext(value) {
  setContext(PDF_ENGINE_CONTEXT_KEY, value);
}
function getPdfEngineContext() {
  const context = getContext(PDF_ENGINE_CONTEXT_KEY);
  if (context === void 0) {
    throw new Error("getPdfEngineContext must be used within a PdfEngineProvider");
  }
  return context;
}
function useEngineContext() {
  const contextValue = getPdfEngineContext();
  if (contextValue === void 0) {
    throw new Error("useEngineContext must be used within a PdfEngineProvider");
  }
  return contextValue;
}
function useEngine() {
  const { engine, error } = getPdfEngineContext();
  if (error) {
    throw error;
  }
  return engine;
}
const defaultWasmUrl = "https://cdn.jsdelivr.net/npm/@embedpdf/pdfium@2.9.0/dist/pdfium.wasm";
function usePdfiumEngine(config) {
  const {
    wasmUrl = defaultWasmUrl,
    worker = true,
    logger,
    fontFallback
  } = config ?? {};
  const state = $.proxy({ engine: null, isLoading: true, error: null });
  let engineRef = $.state(null);
  const isBrowser = typeof window !== "undefined";
  if (isBrowser) {
    $.user_effect(() => {
      let cancelled = false;
      (async () => {
        try {
          const { createPdfiumEngine } = worker ? await import("@embedpdf/engines/pdfium-worker-engine") : await import("@embedpdf/engines/pdfium-direct-engine");
          const pdfEngine = await createPdfiumEngine(wasmUrl, { logger, fontFallback });
          $.set(engineRef, pdfEngine, true);
          state.engine = pdfEngine;
          state.isLoading = false;
        } catch (e) {
          if (!cancelled) {
            state.error = e;
            state.isLoading = false;
          }
        }
      })();
      return () => {
        var _a, _b;
        cancelled = true;
        (_b = (_a = $.get(engineRef)) == null ? void 0 : _a.closeAllDocuments) == null ? void 0 : _b.call(_a).wait(
          () => {
            var _a2, _b2;
            (_b2 = (_a2 = $.get(engineRef)) == null ? void 0 : _a2.destroy) == null ? void 0 : _b2.call(_a2);
            $.set(engineRef, null);
          },
          ignore
        );
      };
    });
  }
  return state;
}
function PdfEngineProvider($$anchor, $$props) {
  $.push($$props, true);
  $.user_effect(() => {
    setPdfEngineContext({
      engine: $$props.engine,
      isLoading: $$props.isLoading,
      error: $$props.error
    });
  });
  var fragment = $.comment();
  var node = $.first_child(fragment);
  $.snippet(node, () => $$props.children);
  $.append($$anchor, fragment);
  $.pop();
}
export {
  PdfEngineProvider,
  useEngine,
  useEngineContext,
  usePdfiumEngine
};
//# sourceMappingURL=index.js.map
