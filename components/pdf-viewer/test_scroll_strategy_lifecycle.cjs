const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const path = require('node:path');
const { test } = require('node:test');

if (typeof global.window === 'undefined') {
  global.window = global;
}

const scrollDist = path.join(__dirname, 'embed-pdf-viewer/packages/plugin-scroll/dist/index.cjs');
const requireFromScroll = createRequire(scrollDist);
const {
  PluginRegistry,
  startLoadingDocument,
  setDocumentLoaded,
  closeDocument,
} = requireFromScroll('@embedpdf/core');
const { ViewportPluginPackage } = requireFromScroll('@embedpdf/plugin-viewport');
const { ScrollPluginPackage } = requireFromScroll(scrollDist);

const DOC_ID = 'x-pdf-viewer-doc-id';

function fakeDocument(id) {
  return {
    id,
    pageCount: 1,
    isEncrypted: false,
    isOwnerUnlocked: false,
    pages: [{
      index: 0,
      size: { width: 100, height: 200 },
      rotation: 0,
    }],
  };
}

async function openScrollRegistry(documentId = DOC_ID) {
  const registry = new PluginRegistry({});
  registry.registerPlugin(ViewportPluginPackage);
  registry.registerPlugin(ScrollPluginPackage);
  await registry.initialize();
  const store = registry.getStore();
  const scrollPlugin = registry.getPlugin('scroll');
  const scroll = scrollPlugin.provides();
  store.dispatch(startLoadingDocument(documentId, 'fixture.pdf'));
  store.dispatch(setDocumentLoaded(documentId, fakeDocument(documentId)));
  return { registry, store, scrollPlugin, scroll };
}

test('loading start creates a strategy for the document id', async () => {
  const { registry, scrollPlugin } = await openScrollRegistry();
  assert.equal(scrollPlugin.strategies.has(DOC_ID), true);
  assert.equal(Boolean(scrollPlugin.state.documents[DOC_ID]), true);
  await registry.destroy();
});

test('scroll after strategy deletion does not throw', async () => {
  const { registry, scrollPlugin, scroll } = await openScrollRegistry();
  assert.equal(scrollPlugin.strategies.has(DOC_ID), true);
  scrollPlugin.strategies.delete(DOC_ID);
  assert.equal(scrollPlugin.strategies.has(DOC_ID), false);
  assert.equal(Boolean(scrollPlugin.state.documents[DOC_ID]), true);
  scroll.scrollToPage({ pageNumber: 1, behavior: 'instant' });
  await registry.destroy();
});

test('close removes state before the strategy and ignores a late scroll', async () => {
  const { registry, store, scrollPlugin, scroll } = await openScrollRegistry();
  const originalDelete = scrollPlugin.strategies.delete.bind(scrollPlugin.strategies);
  const order = [];
  scrollPlugin.strategies.delete = (key) => {
    order.push({
      event: 'strategy-delete',
      hasScrollState: Boolean(scrollPlugin.state.documents[key]),
    });
    return originalDelete(key);
  };
  store.dispatch(closeDocument(DOC_ID));
  assert.equal(order.length, 1);
  assert.equal(order[0].hasScrollState, false);
  assert.equal(scrollPlugin.strategies.has(DOC_ID), false);
  assert.equal(Boolean(scrollPlugin.state.documents[DOC_ID]), false);
  scroll.scrollToPage({ pageNumber: 1, behavior: 'instant' });
  await registry.destroy();
});

test('a replacement document can scroll after the previous document closes', async () => {
  const { registry, store, scrollPlugin, scroll } = await openScrollRegistry();
  store.dispatch(closeDocument(DOC_ID));
  const nextId = 'x-pdf-viewer-doc-id-next';
  store.dispatch(startLoadingDocument(nextId, 'next.pdf'));
  store.dispatch(setDocumentLoaded(nextId, fakeDocument(nextId)));
  assert.equal(scrollPlugin.strategies.has(nextId), true);
  scroll.forDocument(nextId).scrollToPage({ pageNumber: 1, behavior: 'instant' });
  await registry.destroy();
});
