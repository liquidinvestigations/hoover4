import { inject, ref, onMounted, onBeforeUnmount, watch, defineComponent, toRefs, provide, renderSlot } from "vue";
import { ignore } from "@embedpdf/models";
const pdfEngineKey = Symbol("pdfEngineKey");
function useEngineContext() {
  const contextValue = inject(pdfEngineKey);
  if (!contextValue) {
    throw new Error("useEngineContext must be used within a PdfEngineProvider");
  }
  return contextValue;
}
function useEngine() {
  const { engine, error } = useEngineContext();
  if (error.value) {
    throw error.value;
  }
  return engine;
}
const defaultWasmUrl = "https://cdn.jsdelivr.net/npm/@embedpdf/pdfium@2.9.0/dist/pdfium.wasm";
function usePdfiumEngine(props = {}) {
  const { wasmUrl = defaultWasmUrl, worker = true, logger, fontFallback } = props;
  const engine = ref(null);
  const isLoading = ref(true);
  const error = ref(null);
  onMounted(loadEngine);
  onBeforeUnmount(destroyEngine);
  watch(
    () => [wasmUrl, worker, logger, fontFallback],
    () => {
      destroyEngine();
      loadEngine();
    }
  );
  async function loadEngine() {
    try {
      const { createPdfiumEngine } = worker ? await import("@embedpdf/engines/pdfium-worker-engine") : await import("@embedpdf/engines/pdfium-direct-engine");
      const pdfEngine = await createPdfiumEngine(wasmUrl, { logger, fontFallback });
      engine.value = pdfEngine;
      isLoading.value = false;
    } catch (e) {
      error.value = e;
      isLoading.value = false;
    }
  }
  function destroyEngine() {
    var _a, _b;
    (_b = (_a = engine.value) == null ? void 0 : _a.closeAllDocuments) == null ? void 0 : _b.call(_a).wait(() => {
      var _a2, _b2;
      (_b2 = (_a2 = engine.value) == null ? void 0 : _a2.destroy) == null ? void 0 : _b2.call(_a2);
      engine.value = null;
    }, ignore);
  }
  return { engine, isLoading, error };
}
const _sfc_main = /* @__PURE__ */ defineComponent({
  __name: "pdf-engine-provider",
  props: {
    engine: {},
    isLoading: { type: Boolean },
    error: {}
  },
  setup(__props) {
    const props = __props;
    const { engine, isLoading, error } = toRefs(props);
    provide(pdfEngineKey, {
      engine,
      isLoading,
      error
    });
    return (_ctx, _cache) => {
      return renderSlot(_ctx.$slots, "default");
    };
  }
});
export {
  _sfc_main as PdfEngineProvider,
  useEngine,
  useEngineContext,
  usePdfiumEngine
};
//# sourceMappingURL=index.js.map
