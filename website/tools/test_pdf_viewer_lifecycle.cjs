const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(process.env.PDF_VIEWER_SCRIPT || path.join(
  __dirname, '../frontend/assets/embed-pdf/_viewer/embed-pdf.js'), 'utf8')
  .replace("import EmbedPDF from './dist/embedpdf.js';", 'const EmbedPDF = globalThis.EmbedPDF;');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

async function waitForViewers(viewers, count) {
  for (let i = 0; viewers.length < count && i < 50; i++) await Promise.resolve();
  assert.equal(viewers.length, count);
}

function environment() {
  const viewers = [];
  const container = {};
  const context = {
    console, window: {}, document: { getElementById: () => container },
    EmbedPDF: { init(options) {
      const pending = deferred();
      const state = { pending, destroys: 0, layout: null, url: options.documentManager.initialDocuments[0].url,
        pages: [], results: null, zoomLevel: 1, pageChange: null };
      state.registry = {
        destroy: async () => { state.destroys += 1; },
        getPlugin: () => ({ provides: () => ({
          getSchema: () => ({}), onLayoutReady: callback => { state.layout = callback; },
          forDocument: () => ({scrollToPage: options => state.pages.push(options.pageNumber)}),
          onPageChange: callback => { state.pageChange = callback; },
          startSearch: () => {}, setExternalSearchResults: (id, results) => { state.results=results; }, goToResult: () => {},
          getState: () => ({currentZoomLevel:state.zoomLevel}), requestZoom: level => {state.zoomLevel=level;},
          zoomIn: () => {state.zoomLevel+=0.25;}, zoomOut: () => {state.zoomLevel-=0.25;}, onZoomChange: () => {},
        }) }),
      };
      viewers.push(state);
      return { registry: pending.promise };
    } },
  };
  vm.runInNewContext(source, context);
  return { context, viewers };
}

test('disposal during pending initialization destroys the registry once', async () => {
  const { context, viewers } = environment();
  let callbacks = 0;
  const opening = context.window.x_open_pdf_viewer('old.pdf', () => { callbacks += 1; });
  await waitForViewers(viewers, 1);
  const disposing = context.window.x_dispose_pdf_viewer();
  viewers[0].pending.resolve(viewers[0].registry);
  assert.equal(await opening, false);
  assert.equal(await disposing, true);
  assert.equal(viewers[0].destroys, 1);
  assert.equal(callbacks, 0);
  assert.equal(context.window.x_pdf_viewer, null);
});

test('a previous layout callback cannot update the replacement viewer', async () => {
  const { context, viewers } = environment();
  let oldCallbacks = 0;
  let currentCallbacks = 0;
  const first = context.window.x_open_pdf_viewer('old.pdf', () => { oldCallbacks += 1; });
  await waitForViewers(viewers, 1);
  viewers[0].pending.resolve(viewers[0].registry);
  assert.equal(await first, true);
  const second = context.window.x_open_pdf_viewer('current.pdf', () => { currentCallbacks += 1; });
  await waitForViewers(viewers, 2);
  viewers[1].pending.resolve(viewers[1].registry);
  assert.equal(await second, true);
  viewers[0].layout({ page: 1 });
  viewers[1].layout({ page: 2 });
  assert.equal(oldCallbacks, 0);
  assert.equal(currentCallbacks, 1);
  assert.equal(viewers[0].destroys, 1);
  await context.window.x_dispose_pdf_viewer();
  assert.equal(viewers[1].destroys, 1);
});

test('rapid source changes wait for disposal and initialize only the latest source', async () => {
  const { context, viewers } = environment();
  const first = context.window.x_open_pdf_viewer('old.pdf', () => {});
  await waitForViewers(viewers, 1);
  viewers[0].pending.resolve(viewers[0].registry);
  await first;
  const destruction = deferred();
  viewers[0].registry.destroy = () => {
    viewers[0].destroys += 1;
    return destruction.promise;
  };
  const second = context.window.x_open_pdf_viewer('intermediate.pdf', () => {});
  const third = context.window.x_open_pdf_viewer('latest.pdf', () => {});
  for (let i = 0; i < 20; i++) await Promise.resolve();
  assert.equal(viewers.length, 1);
  destruction.resolve();
  await waitForViewers(viewers, 2);
  viewers[1].pending.resolve(viewers[1].registry);
  assert.equal(await second, false);
  assert.equal(await third, true);
  assert.equal(viewers[0].destroys, 1);
  await context.window.x_dispose_pdf_viewer();
});

test('a failed registry destroy does not block the next open', async () => {
  const { context, viewers } = environment();
  const first = context.window.x_open_pdf_viewer('old.pdf', () => {});
  await waitForViewers(viewers, 1);
  viewers[0].registry.destroy = async () => {
    viewers[0].destroys += 1;
    throw new Error('destroy failed');
  };
  viewers[0].pending.resolve(viewers[0].registry);
  assert.equal(await first, true);
  const second = context.window.x_open_pdf_viewer('current.pdf', () => {});
  await waitForViewers(viewers, 2);
  viewers[1].pending.resolve(viewers[1].registry);
  assert.equal(await second, true);
  assert.equal(viewers[0].destroys, 1);
  assert.equal(viewers[1].destroys, 0);
  await context.window.x_dispose_pdf_viewer();
  assert.equal(viewers[1].destroys, 1);
});

test('layout ready records generation and document identity', async () => {
  const { context, viewers } = environment();
  const opened = context.window.x_open_pdf_viewer('current.pdf', () => {});
  await waitForViewers(viewers, 1);
  viewers[0].pending.resolve(viewers[0].registry);
  assert.equal(await opened, true);
  viewers[0].layout({ documentId: 'x-pdf-viewer-doc-id', isInitial: true, pageNumber: 1, totalPages: 1 });
  const events = context.window.x_pdf_lifecycle.map(row => row.event);
  assert.ok(events.includes('open-start'));
  assert.ok(events.includes('layout-ready'));
  await context.window.x_dispose_pdf_viewer();
});


test('multipart navigation translates pages and search results and preserves zoom', async () => {
  const {context,viewers} = environment();
  let controller;
  const manifest={page_count:200,route:'/_download_pdf_part/dataset/hash/original/-/-',parts:[
    {part_index:1,first_page:1,last_page:100},{part_index:2,first_page:101,last_page:200}]};
  const opening=context.window.x_open_pdf_viewer('complete.pdf',(url,event,scroll,search,zoom)=>{
    controller={url,event,scroll,search,zoom};
  },manifest);
  async function load(index) {
    await waitForViewers(viewers,index+1);
    viewers[index].pending.resolve(viewers[index].registry);
    for(let i=0;!viewers[index].layout && i<50;i++) await Promise.resolve();
    viewers[index].layout({documentId:'x-pdf-viewer-doc-id',pageNumber:1,totalPages:100,isInitial:true});
  }
  await load(0); await opening;
  assert.equal(controller.event.totalPages,200);
  assert.equal(viewers[0].url,manifest.route+'/1');
  const pages=[];controller.scroll.onPageChange(event=>pages.push(event.pageNumber));
  controller.zoom.zoomIn();
  controller.search.setExternalSearchResults('',{results:[{pageIndex:100,charIndex:1,charCount:4}],total:1});
  assert.equal(viewers[0].results.total,0);
  const navigating=controller.scroll.scrollToPage({pageNumber:101},'');
  await load(1);await navigating;
  assert.equal(viewers[1].url,manifest.route+'/2');
  assert.equal(viewers[1].pages.at(-1),1);
  assert.equal(viewers[1].results.results[0].pageIndex,0);
  assert.equal(viewers[1].zoomLevel,1.25);
  viewers[1].pageChange({pageNumber:2});
  assert.equal(pages.at(-1),102);
  await context.window.x_dispose_pdf_viewer();
  await controller.scroll.scrollToPage({pageNumber:1},'');
  assert.equal(viewers.length,2);
});


test('custom element cleanup performs registry disposal once', async () => {
  const {context,viewers}=environment();
  const opening=context.window.x_open_pdf_viewer('source.pdf',()=>{});
  await waitForViewers(viewers,1);
  viewers[0].pending.resolve(viewers[0].registry);await opening;
  await context.window.x_dispose_pdf_viewer();
  await viewers[0].registry.destroy();
  assert.equal(viewers[0].destroys,1);
});


test('recursive component cleanup does not wait for its own disposal', async () => {
  const {context,viewers}=environment();
  const opening=context.window.x_open_pdf_viewer('source.pdf',()=>{});
  await waitForViewers(viewers,1);
  viewers[0].registry.destroy=async()=>{
    viewers[0].destroys+=1;
    await viewers[0].registry.destroy();
  };
  viewers[0].pending.resolve(viewers[0].registry);await opening;
  await context.window.x_dispose_pdf_viewer();
  assert.equal(viewers[0].destroys,1);
  const replacement=context.window.x_open_pdf_viewer('replacement.pdf',()=>{});
  await waitForViewers(viewers,2);
  viewers[1].pending.resolve(viewers[1].registry);assert.equal(await replacement,true);
});


test('engine destruction waits for document-manager disposal', async () => {
  const { context, viewers } = environment();
  const opening = context.window.x_open_pdf_viewer('source.pdf', () => {});
  await waitForViewers(viewers, 1);
  const closing = deferred();
  const events = [];
  const engine = { destroy() { events.push('engine'); } };
  const getPlugin = viewers[0].registry.getPlugin;
  viewers[0].registry.getPlugin = id => id === 'document-manager' ? { engine } : getPlugin(id);
  viewers[0].registry.destroy = async () => { events.push('registry'); await closing.promise; };
  viewers[0].pending.resolve(viewers[0].registry);
  await opening;
  const destruction = engine.destroy();
  await Promise.resolve();
  assert.deepEqual(events, ['registry']);
  closing.resolve();
  await destruction;
  assert.deepEqual(events, ['registry', 'engine']);
  await context.window.x_dispose_pdf_viewer();
});


test('failed registry disposal still destroys the engine', async () => {
  const { context, viewers } = environment();
  context.console = { ...console, error() {} };
  const opening = context.window.x_open_pdf_viewer('source.pdf', () => {});
  await waitForViewers(viewers, 1);
  let destroyed = 0;
  const engine = { destroy() { destroyed++; } };
  const getPlugin = viewers[0].registry.getPlugin;
  viewers[0].registry.getPlugin = id => id === 'document-manager' ? { engine } : getPlugin(id);
  viewers[0].registry.destroy = async () => { throw Error('failed registry disposal'); };
  viewers[0].pending.resolve(viewers[0].registry);
  await opening;
  await engine.destroy();
  assert.equal(destroyed, 1);
  assert.ok(context.window.x_pdf_lifecycle.some(row => row.event === 'registry-destroy-failed'));
});
