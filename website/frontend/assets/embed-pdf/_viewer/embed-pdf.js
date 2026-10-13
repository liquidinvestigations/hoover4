import EmbedPDF from './dist/embedpdf.js';
const DOC_ID = "x-pdf-viewer-doc-id";
const viewerDisposals = new WeakMap();
const registryDisposals = new WeakMap();
function reuseRegistryDisposal(registry) {
  if (!registryDisposals.has(registry)) {
    const destroy = registry.destroy.bind(registry);
    const state = { started: false, promise: null };
    registry.destroy = () => {
      if (state.started) return Promise.resolve();
      state.started = true;
      state.promise = Promise.resolve().then(destroy);
      return state.promise;
    };
    registryDisposals.set(registry, state);
    const engine = registry.getPlugin('document-manager')?.engine;
    if (engine?.destroy) {
      const destroyEngine = engine.destroy.bind(engine);
      let engineDisposal;
      engine.destroy = () => {
        if (!engineDisposal) {
          registry.destroy();
          engineDisposal = state.promise.then(destroyEngine, error => {
            trace("registry-destroy-failed", { message: String(error && error.message || error) });
            console.error("PDF viewer registry destroy failed", error);
            return destroyEngine();
          }).catch(error => {
            trace("engine-destroy-failed", { message: String(error && error.message || error) });
            console.error("PDF viewer engine destroy failed", error);
          });
        }
        return engineDisposal;
      };
    }
  }
  return registry;
}
let pendingDisposal = Promise.resolve();

function trace(event, extra) {
  const row = {
    event,
    generation: window.x_pdf_viewer_generation || 0,
    documentId: DOC_ID,
    ...extra,
  };
  window.x_pdf_lifecycle = window.x_pdf_lifecycle || [];
  window.x_pdf_lifecycle.push(row);
  console.info("pdf-lifecycle", row);
}

function destroyViewer(viewer) {
  if (!viewerDisposals.has(viewer)) {
    viewerDisposals.set(viewer, Promise.resolve(viewer.registry).then(registry => {
      const requested = reuseRegistryDisposal(registry).destroy();
      return registryDisposals.get(registry).promise || requested;
    }).catch(error => {
      trace("registry-destroy-failed", { message: String(error && error.message || error) });
      console.error("PDF viewer registry destroy failed", error);
    }));
  }
  return viewerDisposals.get(viewer);
}

window.x_dispose_pdf_viewer = async function(invalidate = true) {
  if (invalidate) window.x_pdf_viewer_generation = (window.x_pdf_viewer_generation || 0) + 1;
  const viewer = window.x_pdf_viewer;
  window.x_pdf_viewer = null;
  trace("dispose-start", { invalidate, hadViewer: Boolean(viewer) });
  if (viewer) pendingDisposal = Promise.all([pendingDisposal, destroyViewer(viewer)]);
  try {
    await pendingDisposal;
  } catch (error) {
    trace("dispose-failed", { message: String(error && error.message || error) });
    console.error("PDF viewer pending disposal failed", error);
    pendingDisposal = Promise.resolve();
  }
  trace("dispose-complete", { hadViewer: Boolean(viewer) });
  return Boolean(viewer);
};

function bindScrollApi(scroll, documentId, generation, viewer) {
  return {
    scrollToPage(options, docId) {
      if (generation !== window.x_pdf_viewer_generation || window.x_pdf_viewer !== viewer) {
        trace("skip-stale-scroll", { requestedId: docId || documentId, currentGeneration: window.x_pdf_viewer_generation });
        return;
      }
      const id = docId || documentId;
      trace("scroll-to-page", { requestedId: id, pageNumber: options.pageNumber });
      scroll.forDocument(id).scrollToPage(options);
    },
    onPageChange: scroll.onPageChange,
  };
}

window.x_open_pdf_viewer = async function(pdf_url, callback_fn) {
  const generation = (window.x_pdf_viewer_generation || 0) + 1;
  window.x_pdf_viewer_generation = generation;
  trace("open-start", { pdf_url });
  await window.x_dispose_pdf_viewer(false);
  if (generation !== window.x_pdf_viewer_generation) {
    trace("open-cancelled-after-dispose", {});
    return false;
  }
  const container = document.getElementById('x-pdf-viewer');
  if (!container || container.isConnected === false) {
    console.error("PDF CONTAINER NOT FOUND: ", container);
    trace("open-missing-container", { connected: Boolean(container && container.isConnected) });
    return null;
  }
  while (container.firstChild) {
    container.removeChild(container.lastChild);
  }

  const viewer = EmbedPDF.init({
    type: 'container',
    target: container,
    documentManager: {
        initialDocuments: [
          {
            url: pdf_url,
            autoActivate: true,
            documentId: DOC_ID,
          },
        ]
    },
    theme: { preference: 'light' },
    disabledCategories: [
        'annotation',
        'print',
        'redaction',
        'export',
        'document',
        'shapes',
        'zoom',
        'tools',
        'page',
        'sidebars',
        'panel',
        'spread',
        'rotate',
        'scroll',
    ],
  });
  window.x_pdf_viewer = viewer;
  trace("open-init", { pdf_url });

  const registry = reuseRegistryDisposal(await viewer.registry);
  if (generation !== window.x_pdf_viewer_generation) {
    trace("open-cancelled-after-registry", {});
    await destroyViewer(viewer);
    return false;
  }

    const commands = registry.getPlugin('commands').provides();
    const ui = registry.getPlugin('ui').provides();

    const schema = ui.getSchema();
    schema.toolbars = {};
    schema.overlays = {};

    const scroll = registry.getPlugin('scroll').provides();
    const search = registry.getPlugin('search').provides();
    const zoom = registry.getPlugin('zoom').provides();
    const boundScroll = bindScrollApi(scroll, DOC_ID, generation, viewer);
    scroll.onLayoutReady((event) => {
      if (generation !== window.x_pdf_viewer_generation || window.x_pdf_viewer !== viewer || document.getElementById('x-pdf-viewer') !== container) {
        trace("skip-stale-layout", { eventDocumentId: event && event.documentId });
        return;
      }
      trace("layout-ready", { eventDocumentId: event && event.documentId, isInitial: event && event.isInitial });
      callback_fn(pdf_url, event, boundScroll, search, zoom);
    });
  trace("open-complete", { pdf_url });
  return true;
};

const openSinglePdf = window.x_open_pdf_viewer;
const disposeSinglePdf = window.x_dispose_pdf_viewer;
let multipartSource = null;
window.x_dispose_pdf_viewer = async function(invalidate = true) {
  if (invalidate && multipartSource) {
    multipartSource.cancelled = true;
    multipartSource = null;
  }
  return disposeSinglePdf(invalidate);
};

window.x_open_pdf_viewer = async function(pdfUrl, callback, manifest = null) {
  if (!manifest || !manifest.parts || manifest.parts.length === 0) {
    if (multipartSource) multipartSource.cancelled = true;
    multipartSource = null;
    return openSinglePdf(pdfUrl, callback);
  }
  if (multipartSource) multipartSource.cancelled = true;
  const state = { cancelled: false, part: null, scroll: null, search: null, zoom: null,
    results: { results: [], total: 0 }, pageListeners: [], ready: false, opening: null };
  multipartSource = state;
  const current = () => !state.cancelled && multipartSource === state;
  function localResults() {
    const offset = state.part.first_page - 1;
    const results = state.results.results.filter(hit => hit.pageIndex >= offset && hit.pageIndex < state.part.last_page)
      .map(hit => ({ ...hit, pageIndex: hit.pageIndex - offset }));
    return { results, total: results.length };
  }
  function applyResults() {
    if (state.search && state.part) {
      state.search.startSearch(DOC_ID);
      state.search.setExternalSearchResults(DOC_ID, localResults());
    }
  }
  const virtualScroll = {
    async scrollToPage(options, docId) {
      if (!current()) return;
      const page = Math.max(1, Math.min(manifest.page_count, options.pageNumber));
      const part = manifest.parts.find(part => part.first_page <= page && page <= part.last_page);
      if (!part) return;
      await loadPart(part);
      if (!current() || state.part !== part) return;
      state.scroll.scrollToPage({ ...options, pageNumber: page - part.first_page + 1 }, docId);
    },
    onPageChange(listener) { state.pageListeners.push(listener); },
  };
  const virtualSearch = {
    startSearch() { if (current() && state.search) state.search.startSearch(DOC_ID); },
    setExternalSearchResults(docId, results) { if (current()) { state.results = results; applyResults(); } },
    async goToResult(index) {
      const hit = state.results.results[index];
      if (!current() || !hit) return;
      const part = manifest.parts.find(part => part.first_page <= hit.pageIndex + 1 && hit.pageIndex + 1 <= part.last_page);
      await loadPart(part);
      if (!current() || state.part !== part) return;
      const localIndex = state.results.results.slice(0,index).filter(item => item.pageIndex >= part.first_page - 1 && item.pageIndex < part.last_page).length;
      state.search.goToResult(localIndex, DOC_ID);
    },
  };
  const zoomListeners = [];
  const virtualZoom = {
    zoomIn() { if (current() && state.zoom) state.zoom.zoomIn(); },
    zoomOut() { if (current() && state.zoom) state.zoom.zoomOut(); },
    getState() { return state.zoom.getState(); },
    onZoomChange(listener) { zoomListeners.push(listener); },
  };
  async function loadPart(part) {
    if (!current() || !part) return;
    if (state.part && state.part.part_index === part.part_index) { if (state.opening) await state.opening; return; }
    const previousZoom = state.zoom ? state.zoom.getState().currentZoomLevel : null;
    state.part = part;
    const url = `${manifest.route}/${part.part_index}`;
    state.opening = new Promise((resolve, reject) => {
      openSinglePdf(url, (loadedUrl, event, scroll, search, zoom) => {
        if (!current() || state.part !== part) { resolve(); return; }
        if (state.loadedPart === part) { resolve(); return; }
        state.loadedPart = part;
        state.scroll = scroll; state.search = search; state.zoom = zoom;
        scroll.onPageChange(event => {
          if (current() && state.part === part) state.pageListeners.forEach(listener => listener({ ...event, pageNumber: event.pageNumber + part.first_page - 1 }));
        });
        zoom.onZoomChange(event => { if (current()) zoomListeners.forEach(listener => listener(event)); });
        state.pageListeners.forEach(listener => listener({ ...event, pageNumber: event.pageNumber + part.first_page - 1 }));
        if (previousZoom !== null) zoom.requestZoom(previousZoom);
        applyResults();
        if (!state.ready) {
          state.ready = true;
          callback(pdfUrl, { ...event, totalPages: manifest.page_count, pageNumber: event.pageNumber + part.first_page - 1 }, virtualScroll, virtualSearch, virtualZoom);
        }
        resolve();
      }).then(opened => { if (opened === false || opened === null) resolve(); }).catch(reject);
    });
    await state.opening;
  }
  return loadPart(manifest.parts[0]);
};
