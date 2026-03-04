import EmbedPDF from 'https://cdn.jsdelivr.net/npm/@embedpdf/snippet@2.7.0/dist/embedpdf.js';
// import EmbedPDF from '@embedpdf/snippet';
const DOC_ID = "x-pdf-viewer-doc-id";

window.x_open_pdf_viewer = async function(pdf_url, callback_fn) {

  const container = document.getElementById('x-pdf-viewer');
  // drop previous pdf viewer
  if (window.x_pdf_viewer) {
    window.x_pdf_viewer = null;
  }
  if (container) {
    // drop previous containers
    while (container.firstChild) {
      container.removeChild(container.lastChild);
    }

    window.x_pdf_viewer = EmbedPDF.init({
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

    const registry = await window.x_pdf_viewer.registry;

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
      scroll.onLayoutReady((event) => {
        // console.log("PDF LAYOUT READY: ", event);
        callback_fn(pdf_url, event, scroll, search);
      });
    return true;
  } else {
    console.error("PDF CONTAINER NOT FOUND: ", container);
    return null;
  }
};
