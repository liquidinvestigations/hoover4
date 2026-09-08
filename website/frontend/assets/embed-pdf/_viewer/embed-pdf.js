import EmbedPDF from './dist/embedpdf.js';
// import EmbedPDF from '@embedpdf/snippet';
const DOC_ID = "x-pdf-viewer-doc-id";
const viewerDisposals = new WeakMap();
let pendingDisposal = Promise.resolve();

function destroyViewer(viewer) {
  if (!viewerDisposals.has(viewer)) {
    viewerDisposals.set(viewer, Promise.resolve(viewer.registry).then(registry => registry.destroy()));
  }
  return viewerDisposals.get(viewer);
}

window.x_dispose_pdf_viewer = async function(invalidate = true) {
  if (invalidate) window.x_pdf_viewer_generation = (window.x_pdf_viewer_generation || 0) + 1;
  const viewer = window.x_pdf_viewer;
  window.x_pdf_viewer = null;
  if (viewer) pendingDisposal = Promise.all([pendingDisposal, destroyViewer(viewer)]);
  await pendingDisposal;
  return Boolean(viewer);
};

window.x_open_pdf_viewer = async function(pdf_url, callback_fn) {
  const generation = (window.x_pdf_viewer_generation || 0) + 1;
  window.x_pdf_viewer_generation = generation;
  const container = document.getElementById('x-pdf-viewer');
  await window.x_dispose_pdf_viewer(false);
  if (generation !== window.x_pdf_viewer_generation) return false;
  if (container) {
    while (container.firstChild) {
      container.removeChild(container.lastChild);
    }

    const viewer = EmbedPDF.init({
      type: 'container',
      target: container,
      documentManager: {
          // Load these files on startup
          initialDocuments: [
            {
              url: pdf_url,
              // By default, autoActivate is true.
              // This document will open and become active.
              autoActivate: true,
              // OPTIONAL: Set a custom ID so you can easily reference
              // this document later (e.g. to scroll or close it).
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

    const registry = await viewer.registry;
    if (generation !== window.x_pdf_viewer_generation) {
      await destroyViewer(viewer);
      return false;
    }

      // 1. Get the plugins
      const commands = registry.getPlugin('commands').provides();
      const ui = registry.getPlugin('ui').provides();

    // 4. Replace a button in the toolbar
      const schema = ui.getSchema();
      // console.log("UI SCHEMA: ", schema);
      // console.log("UI SCHEMA TOOLBARS: " + JSON.stringify(schema.toolbars, null, 2));
      schema.toolbars = {};

      // console.log("UI SCHEMA OVERLAYS: " + JSON.stringify(schema.overlays, null, 2));
      schema.overlays = {};
      // console.log("UI SCHEMA SELECTION MENUS: " + JSON.stringify(schema.selectionMenus, null, 2));
      // schema.selectionMenus = {};

      const scroll = registry.getPlugin('scroll').provides();
      const search = registry.getPlugin('search').provides();
      const zoom = registry.getPlugin('zoom').provides();
      scroll.onLayoutReady((event) => {
        if (generation !== window.x_pdf_viewer_generation || window.x_pdf_viewer !== viewer || document.getElementById('x-pdf-viewer') !== container) return;
        // console.log("PDF LAYOUT READY: ", event);
        callback_fn(pdf_url, event, scroll, search, zoom);
      });
    return true;
  } else {
    console.error("PDF CONTAINER NOT FOUND: ", container);
    return null;
  }
};
