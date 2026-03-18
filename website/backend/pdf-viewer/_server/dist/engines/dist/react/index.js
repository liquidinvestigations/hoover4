import { useState, useRef, useEffect, createContext, useContext } from "react";
import { ignore } from "@embedpdf/models";
import { jsx } from "react/jsx-runtime";
const defaultWasmUrl = `https://cdn.jsdelivr.net/npm/@embedpdf/pdfium@2.9.0/dist/pdfium.wasm`;
function usePdfiumEngine(config) {
  const {
    wasmUrl = defaultWasmUrl,
    worker = true,
    logger,
    encoderPoolSize,
    fontFallback
  } = config ?? {};
  const [engine, setEngine] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const engineRef = useRef(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { createPdfiumEngine } = worker ? await import("@embedpdf/engines/pdfium-worker-engine") : await import("@embedpdf/engines/pdfium-direct-engine");
        const pdfEngine = await createPdfiumEngine(wasmUrl, {
          logger,
          encoderPoolSize,
          fontFallback
        });
        engineRef.current = pdfEngine;
        setEngine(pdfEngine);
        setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setError(e);
          setLoading(false);
        }
      }
    })();
    return () => {
      var _a, _b;
      cancelled = true;
      (_b = (_a = engineRef.current) == null ? void 0 : _a.closeAllDocuments) == null ? void 0 : _b.call(_a).wait(() => {
        var _a2, _b2;
        (_b2 = (_a2 = engineRef.current) == null ? void 0 : _a2.destroy) == null ? void 0 : _b2.call(_a2);
        engineRef.current = null;
      }, ignore);
    };
  }, [wasmUrl, worker, logger, fontFallback]);
  return { engine, isLoading: loading, error };
}
const PdfEngineContext = createContext(void 0);
function useEngineContext() {
  const contextValue = useContext(PdfEngineContext);
  if (contextValue === void 0) {
    throw new Error("useEngineContext must be used within a PdfEngineProvider");
  }
  return contextValue;
}
function useEngine() {
  const { engine, error } = useEngineContext();
  if (error) {
    throw error;
  }
  return engine;
}
function PdfEngineProvider({ children, engine, isLoading, error }) {
  const contextValue = {
    engine,
    isLoading,
    error
  };
  return /* @__PURE__ */ jsx(PdfEngineContext.Provider, { value: contextValue, children });
}
export {
  PdfEngineProvider,
  useEngine,
  useEngineContext,
  usePdfiumEngine
};
//# sourceMappingURL=index.js.map
