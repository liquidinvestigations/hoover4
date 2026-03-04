import EmbedPDF from 'https://cdn.jsdelivr.net/npm/@embedpdf/snippet@2.7.0/dist/embedpdf.js';
// import EmbedPDF from '@embedpdf/snippet';
const DOC_ID = "x-pdf-viewer-doc-id";

window.x_open_pdf_viewer = async function(pdf_url, callback_fn) {

const container = document.getElementById('x-pdf-viewer');
  if (container) {
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
          'spread','rotate', 'scroll',
      ],
    });

    const registry = await window.x_pdf_viewer.registry;

      // 1. Get the plugins
      const commands = registry.getPlugin('commands').provides();
      const ui = registry.getPlugin('ui').provides();

    // 4. Replace a button in the toolbar
      const schema = ui.getSchema();
      console.log("UI SCHEMA: ", schema);
      schema.toolbars = {};
      schema.overlays = {};
      schema.selectionMenus = {};

      const scroll = registry.getPlugin('scroll').provides();
      const search = registry.getPlugin('search').provides();
      scroll.onLayoutReady((event) => {callback_fn(event, scroll, search);});

  } else {
    console.error("PDF CONTAINER NOT FOUND: ", container);
    return null;
  }
}
// const pdf_url ='http://localhost:8080/_download_document/testdata/a0d06de0243c63497070c77e9bb6cab5a2d0bda5564daa03a37987a4f1640fd3';
const pdf_url ='https://snippet.embedpdf.com/ebook.pdf';
function callback_fn(event, scroll, search) {

  console.log("LAYOUT READY: ", event);
  console.log("DOC TOTAL PAGES: ", event.totalPages);
    // scroll.scrollToPage({
        // pageNumber: 2,
        // behavior: 'instant' // Instant jump for initial load
    // });
    const PAGE_IDX = 12;
    const search_result = search.searchAllPages('PDF', DOC_ID).toPromise();
    search_result.then((result) => {
        console.log("SEARCH RESULT: ", result);
        let item = result.results[PAGE_IDX];
        let page_index = item.pageIndex;
        let point = item.rects[0].origin;
        let individual_result = search.goToResult(PAGE_IDX, DOC_ID);
        scroll.scrollToPage({
          pageNumber: page_index+1,
          behavior: 'smooth',
          pageCoordinates: point,
          alignY: 40,
        }, DOC_ID);
        console.log("INDIVIDUAL RESULT: ", individual_result);
        console.log("GET FLAG: ", search.getState());
    });

}
await window.x_open_pdf_viewer(pdf_url,
  (event, scroll, search) => {
    console.log("LAYOUT READY: ", event);
  console.log("DOC TOTAL PAGES: ", event.totalPages);
    // scroll.scrollToPage({
        // pageNumber: 2,
        // behavior: 'instant' // Instant jump for initial load
    // });
    const PAGE_IDX = 12;
    const search_result = search.searchAllPages('PDF', DOC_ID).toPromise();
    search_result.then((result) => {
        console.log("SEARCH RESULT: ", result);
        let item = result.results[PAGE_IDX];
        let page_index = item.pageIndex;
        let point = item.rects[0].origin;
        let individual_result = search.goToResult(PAGE_IDX, DOC_ID);
        scroll.scrollToPage({
          pageNumber: page_index+1,
          behavior: 'smooth',
          pageCoordinates: point,
          alignY: 40,
        }, DOC_ID);
        console.log("INDIVIDUAL RESULT: ", individual_result);
        console.log("GET FLAG: ", search.getState());
    });
  }
);