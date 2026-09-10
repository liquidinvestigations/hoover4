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
    EmbedPDF: { init() {
      const pending = deferred();
      const state = { pending, destroys: 0, layout: null };
      state.registry = {
        destroy: async () => { state.destroys += 1; },
        getPlugin: () => ({ provides: () => ({
          getSchema: () => ({}), onLayoutReady: callback => { state.layout = callback; },
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
