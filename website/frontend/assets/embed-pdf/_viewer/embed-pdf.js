import EmbedPDF from './dist/embedpdf.js';
const DOC_ID = "x-pdf-viewer-doc-id";
const viewerDisposals = new WeakMap();
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
    viewerDisposals.set(viewer, Promise.resolve(viewer.registry).then(registry => registry.destroy()).catch(error => {
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
      trace("scroll-to-page", { requestedId: id });
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

  const registry = await viewer.registry;
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
