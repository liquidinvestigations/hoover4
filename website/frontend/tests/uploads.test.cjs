// Exercise asynchronous driver commands with delayed transport replies.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const { createHash } = require('node:crypto');
const source = readFileSync(__dirname + '/../assets/uploads.js', 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return { resolve, promise }; };
const reply = (status, body) => ({ status, ok: status < 300, text: async () => JSON.stringify(body), json: async () => body });

function setup(fetch) {
  const events = [], uploads = [], inputs = new Map();
  const document = {
    addEventListener() {},
    getElementById: id => inputs.get(id),
    createElement: () => ({ style: {}, addEventListener(name, fn) { this[name] = fn; }, click() {} }),
    body: { appendChild(el) { inputs.set(el.id, el); } },
  };
  const window = { addEventListener() {}, removeEventListener() {} };
  class Upload {
    constructor(file, options) { this.options = options; uploads.push(this); }
    start() { this.starts = (this.starts || 0) + 1; }
    async abort() { this.aborted = true; }
  }
  vm.runInNewContext(source, { window, document, tus: { Upload }, fetch, setTimeout, clearTimeout, Blob });
  const driver = window.hooverUploads;
  driver.attach(e => events.push(e));
  const file = new Blob(['abc']); file.name = 'a.txt'; file.lastModified = 1000;
  const input = inputs.get('x-upload-file-input'); input.files = [file]; input.change();
  const id = events[0].files[0].id;
  const begin = { cmd: 'begin', ids: [id], paths: ['a.txt'], chunk_bytes: 10, body: '{}' };
  const resume = { cmd: 'resume', batch_id: 'b1', items: [{ id, file_no: 0, path: 'a.txt' }], chunk_bytes: 10, commit_when_done: true };
  return { driver, events, uploads, begin, resume };
}
const batch = { batch_id: 'b1', files: [{ file_no: 0 }] };

test('repeated begin sends one request before and after its delayed response', async () => {
  const response = deferred(); let calls = 0;
  const h = setup(() => { calls++; return response.promise; });
  h.driver.command(h.begin); h.driver.command(h.begin);
  assert.equal(calls, 1);
  response.resolve(reply(201, batch)); await flush();
  h.driver.command(h.begin);
  assert.equal(calls, 1); assert.equal(h.uploads.length, 1);
  h.driver.command({ cmd: 'detach' });
});

test('a failed commit remains retryable and repeated retry sends once', async () => {
  let commits = 0; const second = deferred();
  const h = setup(async url => url.endsWith('/begin') ? reply(201, batch) : (++commits === 1 ? reply(503, { message: 'temporarily unavailable' }) : second.promise));
  h.driver.command(h.begin); await flush();
  h.uploads[0].options.onSuccess(); await flush();
  assert.equal(h.events.at(-1).kind, 'commit_failed');
  h.driver.command({ cmd: 'retry_commit' }); h.driver.command({ cmd: 'retry_commit' }); await flush();
  assert.equal(commits, 2);
  second.resolve(reply(200, { detail: '/uploads/c/b1' })); await flush();
  assert.equal(h.events.at(-1).kind, 'committed');
});

test('finish rejects duplicate commands while commit waits', async () => {
  const response = deferred(); let calls = 0;
  const h = setup(() => { calls++; return response.promise; });
  h.driver.command({ cmd: 'finish', batch_id: 'b1' });
  h.driver.command({ cmd: 'finish', batch_id: 'b1' }); await flush();
  assert.equal(calls, 1);
  response.resolve(reply(200, { detail: '/uploads/c/b1' })); await flush();
  assert.equal(h.events.at(-1).kind, 'committed');
});

test('failed prefix transport releases the pending state for reselection', async () => {
  let calls = 0;
  const h = setup(async () => { calls++; throw new Error('offline'); });
  h.driver.command(h.resume); await flush();
  assert.equal(h.events.at(-1).kind, 'resume_failed');
  h.driver.command(h.resume); await flush();
  assert.equal(calls, 2);
});

test('an ended prefix does not commit a batch as if validation succeeded', async () => {
  const calls = [];
  const h = setup(async url => { calls.push(url); return reply(409, { message: 'ended' }); });
  h.driver.command(h.resume); await flush();
  assert.equal(h.events.at(-1).kind, 'resume_failed');
  assert.equal(calls.length, 1); assert.equal(h.uploads.length, 0);
});

test('leaving during begin prevents its late response from starting a transfer', async () => {
  const response = deferred(); const h = setup(() => response.promise);
  h.driver.command(h.begin); h.driver.command({ cmd: 'detach' });
  const next = []; h.driver.attach(e => next.push(e));
  response.resolve(reply(201, batch)); await flush();
  assert.equal(h.uploads.length, 0); assert.equal(next.length, 0);
});

test('callbacks of an aborted run cannot change the next page', async () => {
  const h = setup(async () => reply(201, batch));
  h.driver.command(h.begin); await flush();
  const next = []; h.driver.attach(e => next.push(e));
  h.uploads[0].options.onError(new Error('aborted'));
  h.uploads[0].options.onSuccess();
  assert.equal(next.length, 0);
});

test('prefix SHA-256 matches the standard digest at block boundaries', () => {
  const h = setup(async () => reply(200, {}));
  for (const size of [0, 1, 55, 56, 63, 64, 65, 1024, 1048577]) {
    const data = Buffer.alloc(size, 97);
    assert.equal(h.driver.sha256Hex(data), createHash('sha256').update(data).digest('hex'));
  }
});

for (const status of [200, 503]) {
  test(`a delayed abort response (${status}) cannot change a replacement page`, async () => {
    const response = deferred();
    const h = setup(async url => url.endsWith('/begin') ? reply(201, batch) : response.promise);
    h.driver.command(h.begin); await flush();
    h.driver.command({ cmd: 'abort' }); await flush();
    const nextEvents = [];
    h.driver.attach(event => nextEvents.push(event));
    response.resolve(reply(status, { message: 'failed' })); await flush();
    assert.deepEqual(nextEvents, []);
  });
}

test('a transfer cancellation failure remains retryable', async () => {
  const h = setup(async url => url.endsWith('/begin') ? reply(201, batch) : reply(200, {}));
  h.driver.command(h.begin); await flush();
  h.uploads[0].abort = async () => { throw new Error('cancel failed'); };
  h.driver.command({ cmd: 'abort' }); await flush();
  assert.equal(h.events.at(-1).kind, 'abort_failed');
  h.uploads[0].abort = async () => {};
  h.driver.command({ cmd: 'abort' }); await flush();
  assert.equal(h.events.at(-1).kind, 'aborted');
});
