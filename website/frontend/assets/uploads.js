// The upload driver of the upload page and of "Continue upload" on the batch detail page.
//
// It holds the browser File objects, walks dropped folders, sends `begin`, runs at most
// MAX_ACTIVE tus-js-client uploads at a time, and sends `commit` when no file waits. A file
// that fails gets MAX_ATTEMPTS attempts in total. A failed attempt puts the file behind the
// files that have not started, and the commit runs also when files failed, so indexing
// starts without a person. A "Continue upload" run commits only when it sends every file of
// the batch that waits for bytes. Otherwise it ends with a `sent` event, and the batch stays
// open for another selection or for Finish upload. Abort stops the transfers and asks the
// server to delete the batch, with the files that it placed. The Rust
// page keeps the selection list and builds the `begin` body, so the page and the server
// measure the same bytes. The page and this script talk through one `document::eval`
// channel: the page sends commands (`cmd`), and the script sends events (`kind`).
//
// tus-js-client comes from assets/vendor/tus.min.js. Its source and checksum are in
// assets/vendor/Readme.md.
(() => {
  if (window.hooverUploads) return;

  // Files in transfer at one time. Most of the time of a small file is the round trips
  // of its requests, so several files share the wait.
  const MAX_ACTIVE = 8;
  // Attempts of one file, the first one included. tus-js-client repeats a failed request
  // inside one attempt with RETRY_DELAYS.
  const MAX_ATTEMPTS = 3;
  const RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 30000];
  const PROGRESS_MS = 200;
  const ENDED = "This upload has ended.";
  // The waits before a repeat of a request that met a busy lock (423).
  const BUSY_DELAYS = [1000, 5000, 15000, 30000];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // A fetch that is repeated after a 423 answer, with the delays of BUSY_DELAYS.
  async function fetchPatient(url, options) {
    let res = await fetch(url, options);
    for (const delay of BUSY_DELAYS) {
      if (res.status !== 423) break;
      await sleep(delay);
      res = await fetch(url, options);
    }
    return res;
  }

  const files = new Map();
  let nextId = 1;
  let sink = null;
  let run = null;
  let pending = false;
  let generation = 0;

  const emit = (event) => { try { if (sink) sink(event); } catch (_) { sink = null; } };

  // Selection ------------------------------------------------------------------------

  function addFiles(found) {
    if (pending || run) return;
    const added = [];
    for (const { file, path } of found) {
      const id = nextId++;
      files.set(id, file);
      added.push({ id, path, size: file.size, last_modified_ms: file.lastModified || null });
    }
    if (added.length) emit({ kind: "added", files: added });
  }

  function readAll(reader) {
    return new Promise((resolve) => {
      const out = [];
      const step = () => reader.readEntries((batch) => {
        if (!batch.length) return resolve(out);
        out.push(...batch);
        step();
      }, () => resolve(out));
      step();
    });
  }

  async function walk(entry, out) {
    if (entry.isFile) {
      const file = await new Promise((resolve) => entry.file(resolve, () => resolve(null)));
      if (file) out.push({ file, path: entry.fullPath.replace(/^\/+/, "") });
    } else if (entry.isDirectory) {
      for (const child of await readAll(entry.createReader())) await walk(child, out);
    }
  }

  async function onDrop(transfer) {
    const token = generation;
    const out = [];
    const entries = [];
    for (const item of transfer.items || []) {
      const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
      if (entry) entries.push(entry);
    }
    if (entries.length) {
      for (const entry of entries) await walk(entry, out);
    } else {
      for (const file of transfer.files || []) out.push({ file, path: file.name });
    }
    if (token === generation) addFiles(out);
  }

  function input(id, folder) {
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement("input");
      el.type = "file";
      el.id = id;
      el.multiple = true;
      if (folder) el.webkitdirectory = true;
      el.style.display = "none";
      el.addEventListener("change", () => {
        addFiles([...el.files].map((file) => ({ file, path: file.webkitRelativePath || file.name })));
        el.value = "";
      });
      document.body.appendChild(el);
    }
    return el;
  }

  const zoneOf = (target) => target && target.closest && target.closest("[data-upload-drop]");
  const mark = (zone, on) => {
    zone.style.borderStyle = on ? "solid" : "";
    zone.style.borderColor = on ? "var(--x-link)" : "";
  };
  document.addEventListener("dragover", (e) => {
    const zone = zoneOf(e.target);
    if (!zone) return;
    e.preventDefault();
    mark(zone, true);
  });
  document.addEventListener("dragleave", (e) => {
    const zone = zoneOf(e.target);
    if (zone && !zone.contains(e.relatedTarget)) mark(zone, false);
  });
  document.addEventListener("drop", (e) => {
    const zone = zoneOf(e.target);
    if (!zone) return;
    e.preventDefault();
    mark(zone, false);
    onDrop(e.dataTransfer);
  });
  document.addEventListener("click", (e) => {
    if (zoneOf(e.target)) input("x-upload-file-input", false).click();
  });
  // Both inputs exist from the start, so a test can set their files.
  const ensureInputs = () => { input("x-upload-file-input", false); input("x-upload-folder-input", true); };

  // Hash -----------------------------------------------------------------------------

  // SHA-256 over a Blob prefix, read in slices, so a large prefix is never one buffer.
  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);

  function sha256() {
    const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    const w = new Uint32Array(64);
    const block = new Uint8Array(64);
    let fill = 0;
    let length = 0;
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));
    function compress(b) {
      for (let i = 0; i < 16; i++) w[i] = (b[i * 4] << 24) | (b[i * 4 + 1] << 16) | (b[i * 4 + 2] << 8) | b[i * 4 + 3];
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      let [a, b2, c, d, e, f, g, hh] = h;
      for (let i = 0; i < 64; i++) {
        const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0;
        const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b2) ^ (a & c) ^ (b2 & c))) | 0;
        hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b2; b2 = a; a = (t1 + t2) | 0;
      }
      h[0] += a; h[1] += b2; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }
    return {
      update(bytes) {
        length += bytes.length;
        let i = 0;
        if (fill) {
          while (fill < 64 && i < bytes.length) block[fill++] = bytes[i++];
          if (fill < 64) return;
          compress(block);
          fill = 0;
        }
        for (; i + 64 <= bytes.length; i += 64) compress(bytes.subarray(i, i + 64));
        while (i < bytes.length) block[fill++] = bytes[i++];
      },
      hex() {
        const bits = length * 8;
        const tail = new Uint8Array(((fill + 9 + 63) >> 6) << 6);
        tail.set(block.subarray(0, fill));
        tail[fill] = 0x80;
        const view = new DataView(tail.buffer);
        view.setUint32(tail.length - 8, Math.floor(bits / 0x100000000));
        view.setUint32(tail.length - 4, bits >>> 0);
        for (let i = 0; i < tail.length; i += 64) compress(tail.subarray(i, i + 64));
        return [...h].map((x) => x.toString(16).padStart(8, "0")).join("");
      },
    };
  }

  async function prefixDigest(file, offset) {
    const hash = sha256();
    const slice = 8 * 1024 * 1024;
    for (let at = 0; at < offset; at += slice) {
      hash.update(new Uint8Array(await file.slice(at, Math.min(offset, at + slice)).arrayBuffer()));
    }
    return hash.hex();
  }

  // Transfer -------------------------------------------------------------------------

  const warnOnLeave = (e) => { e.preventDefault(); e.returnValue = ""; };

  function errorText(err) {
    const res = err && err.originalResponse;
    const body = res && res.getBody && res.getBody();
    if (body) {
      try { return JSON.parse(body).message || body; } catch (_) { return body; }
    }
    return String((err && err.message) || err);
  }

  // A failed attempt that the next attempt can change. An ended batch, a refused
  // permission and a missing file stay failed.
  function attemptAgain(err) {
    const res = err && err.originalResponse;
    if (!res) return true;
    const status = res.getStatus();
    return ![403, 404, 409, 410].includes(status);
  }

  function shouldRetry(err) {
    const res = err && err.originalResponse;
    if (!res) return true;
    const status = res.getStatus();
    if (status === 409) return (res.getBody() || "").trim() !== ENDED;
    return status >= 500 || status === 423;
  }

  // A run is one batch in transfer: its items, the uploads in flight and the totals.
  // `commitWhenDone` is false for a resume run that does not send every waiting file.
  function newRun(batchId, items, chunkBytes, commitWhenDone) {
    return {
      batchId, chunkBytes, items, commitWhenDone, active: new Set(), paused: false,
      stopping: false, ended: false, aborting: false, lastEmit: 0, timer: null,
    };
  }

  function progress(force) {
    if (!run) return;
    const now = Date.now();
    if (!force && now - run.lastEmit < PROGRESS_MS) {
      if (!run.timer) run.timer = setTimeout(() => { run && (run.timer = null); progress(true); }, PROGRESS_MS);
      return;
    }
    run.lastEmit = now;
    const items = run.items;
    emit({
      kind: "progress",
      sent: items.reduce((s, it) => s + it.acked, 0),
      total: items.reduce((s, it) => s + it.size, 0),
      done: items.filter((it) => it.state === "done").length,
      count: items.length,
      in_flight: items.filter((it) => it.state === "active").slice(0, MAX_ACTIVE).map((it) => it.path),
      slots: MAX_ACTIVE,
      failed: items.filter((it) => it.state === "failed").map((it) => ({ path: it.path, error: it.error })),
      paused: run.paused,
      phase: run.aborting ? "aborting" : run.ended ? "committing" : "transferring",
    });
  }

  function startItem(item) {
    const owner = run;
    item.state = "active";
    run.active.add(item);
    if (!item.upload) {
      item.upload = new tus.Upload(item.file, {
        endpoint: "/_upload/files/",
        uploadUrl: item.resumeUrl || null,
        chunkSize: run.chunkBytes,
        // The create request carries the first chunk, so a small file needs one request.
        uploadDataDuringCreation: true,
        retryDelays: RETRY_DELAYS,
        metadata: { batch: run.batchId, file: String(item.fileNo) },
        headers: { "X-Hoover-Upload": "1" },
        storeFingerprintForResuming: false,
        removeFingerprintOnSuccess: false,
        onShouldRetry: shouldRetry,
        onChunkComplete: (_chunk, accepted) => {
          if (run !== owner || owner.ended) return;
          item.acked = accepted;
          progress(false);
          if (run && run.paused && accepted < item.size) {
            item.upload.abort(false);
            item.state = "paused";
            run.active.delete(item);
            progress(true);
          }
        },
        onSuccess: () => {
          if (run !== owner || owner.ended) return;
          item.acked = item.size;
          item.state = "done";
          run.active.delete(item);
          pump();
        },
        onError: (err) => {
          if (run !== owner || owner.ended) return;
          run.active.delete(item);
          item.attempts += 1;
          item.error = errorText(err);
          if (item.attempts < MAX_ATTEMPTS && attemptAgain(err)) {
            item.state = "queued";
            run.items.splice(run.items.indexOf(item), 1);
            run.items.push(item);
          } else {
            item.state = "failed";
          }
          pump();
        },
      });
    }
    item.upload.start();
  }

  function pump() {
    if (!run || run.ended) return;
    if (!run.paused && !run.stopping) {
      for (const item of run.items) {
        if (run.active.size >= MAX_ACTIVE) break;
        if (item.state === "queued") startItem(item);
      }
    }
    progress(true);
    const waiting = run.items.some((it) => it.state === "queued" || it.state === "active" || it.state === "paused");
    if (!waiting) {
      if (run.commitWhenDone) commit();
      else endWithoutCommit();
    }
  }

  // The run sent its files, and other files of the batch still wait for bytes. The batch
  // stays `uploading`.
  function endWithoutCommit() {
    if (!run || run.ended) return;
    run.ended = true;
    window.removeEventListener("beforeunload", warnOnLeave);
    const batchId = run.batchId;
    run = null;
    emit({ kind: "sent", batch_id: batchId });
  }

  async function commit() {
    if (!run || run.ended || pending) return;
    const owner = run;
    const token = generation;
    const current = () => token === generation && run === owner;
    owner.ended = true;
    progress(true);
    emit({ kind: "phase", phase: "committing" });
    try {
      await Promise.all([...owner.active].map((item) => item.upload && item.upload.abort(false)));
      if (!current()) return;
      const res = await fetchPatient(`/_upload/${owner.batchId}/commit`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      if (!current()) return;
      const text = await res.text();
      if (!current()) return;
      let body = {};
      try { body = JSON.parse(text); } catch (_) { body = { message: text }; }
      if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
      run = null;
      window.removeEventListener("beforeunload", warnOnLeave);
      emit({ kind: "committed", detail: body.detail });
    } catch (err) {
      if (!current()) return;
      owner.ended = false;
      owner.stopping = true;
      emit({ kind: "commit_failed", message: String(err) });
    }
  }

  function beginRun(batchId, items, chunkBytes, commitWhenDone) {
    run = newRun(batchId, items, chunkBytes, commitWhenDone);
    window.addEventListener("beforeunload", warnOnLeave);
    pump();
  }

  async function begin(cmd) {
    const token = generation;
    let res;
    let text;
    try {
      res = await fetch("/_upload/begin", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: cmd.body,
      });
      if (token !== generation) return;
      text = await res.text();
      if (token !== generation) return;
    } catch (err) {
      if (token !== generation) return;
      pending = false;
      emit({ kind: "refused", status: 0, body: JSON.stringify({ message: String(err) }) });
      return;
    }
    pending = false;
    if (res.status !== 201) {
      emit({ kind: "refused", status: res.status, body: text });
      return;
    }
    const batch = JSON.parse(text);
    const items = batch.files.map((f, i) => {
      const file = files.get(cmd.ids[i]);
      return { fileNo: f.file_no, path: cmd.paths[i], file, size: file.size, acked: 0, state: "queued", attempts: 0 };
    });
    emit({ kind: "begun", batch_id: batch.batch_id });
    beginRun(batch.batch_id, items, cmd.chunk_bytes, true);
  }

  // "Continue upload": verify the acknowledged prefix of each matched file, then resume.
  // A file whose prefix differs keeps its transfer and is listed. The run commits after
  // its last file only when the page reports that it sends every waiting file of the
  // batch (`commit_when_done`) and no file differs.
  async function resume(cmd) {
    const token = generation;
    const items = [];
    const mismatched = [];
    for (const m of cmd.items) {
      const file = files.get(m.id);
      const res = await fetchPatient(`/_upload/${cmd.batch_id}/prefix/${m.file_no}`, { cache: "no-store" });
      if (token !== generation) return;
      if (res.status === 409 || res.status === 410) {
        throw new Error((await res.text()) || ENDED);
      }
      if (!res.ok) {
        const message = await res.text();
        if (token !== generation) return;
        mismatched.push({ path: m.path, error: message || `HTTP ${res.status}` });
        continue;
      }
      const digest = await res.json();
      if (token !== generation) return;
      const prefix = digest.offset > 0 ? await prefixDigest(file, digest.offset) : null;
      if (token !== generation) return;
      if (digest.offset > 0 && prefix !== digest.sha256) {
        mismatched.push({ path: m.path, error: "" });
        continue;
      }
      items.push({
        fileNo: m.file_no, path: m.path, file, size: file.size, acked: digest.offset, state: "queued", attempts: 0,
        resumeUrl: digest.offset > 0 ? `/_upload/files/${cmd.batch_id}-${m.file_no}` : null,
      });
    }
    if (token !== generation) return;
    pending = false;
    const commitWhenDone = !!cmd.commit_when_done && !mismatched.length;
    emit({ kind: "checked", mismatched, sending: items.length });
    // A run without files commits at once when every file of the batch has its bytes.
    if (items.length || commitWhenDone) beginRun(cmd.batch_id, items, cmd.chunk_bytes, commitWhenDone);
  }

  // Abort the batch: stop each transfer, then ask the server to delete the batch and the
  // files that it placed. Without a run, as on the detail page, only the request goes.
  // A failed request keeps the run ended, and Abort can be sent again.
  async function abort(batchId) {
    const owner = run;
    const token = generation;
    const current = () => token === generation && run === owner;
    if (owner ? owner.abortPending : pending) return;
    if (owner) owner.abortPending = true;
    else pending = true;
    try {
    if (owner) {
      if (owner.ended && !owner.aborting) return;
      owner.ended = true;
      owner.aborting = true;
      clearTimeout(owner.timer);
      progress(true);
      await Promise.all([...owner.active].map((item) => item.upload && item.upload.abort(false)));
      if (!current()) return;
      owner.active.clear();
    }
    emit({ kind: "phase", phase: "aborting" });
      const res = await fetchPatient(`/_upload/${batchId}/abort`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      if (!current()) return;
      if (!res.ok) {
        const text = await res.text();
        if (!current()) return;
        let message = text;
        try { message = JSON.parse(text).message || text; } catch (_) {}
        throw new Error(message || `HTTP ${res.status}`);
      }
      pending = false;
      if (run === owner) run = null;
      // The page returns to an empty selection.
      files.clear();
      window.removeEventListener("beforeunload", warnOnLeave);
      emit({ kind: "aborted", batch_id: batchId });
    } catch (err) {
      if (!current()) return;
      emit({ kind: "abort_failed", message: String(err.message || err) });
    } finally {
      if (current()) {
        if (owner) owner.abortPending = false;
        else pending = false;
      }
    }
  }

  function startRequest(cmd, task) {
    if (pending || run) return;
    pending = true;
    const token = generation;
    task(cmd).catch((err) => {
      if (token !== generation) return;
      pending = false;
      emit(cmd.cmd === "begin"
        ? { kind: "refused", status: 0, body: JSON.stringify({ message: String(err) }) }
        : { kind: "resume_failed", message: String(err) });
    });
  }

  function detach() {
    generation++;
    pending = false;
    const previous = run;
    run = null;
    if (previous) {
      clearTimeout(previous.timer);
      for (const item of previous.active) if (item.upload) item.upload.abort(false);
    }
    files.clear();
    sink = null;
    window.removeEventListener("beforeunload", warnOnLeave);
  }

  function command(cmd) {
    switch (cmd.cmd) {
      case "open_files": input("x-upload-file-input", false).click(); break;
      case "open_folder": input("x-upload-folder-input", true).click(); break;
      case "forget": for (const id of cmd.ids) files.delete(id); break;
      case "begin": startRequest(cmd, begin); break;
      case "resume": startRequest(cmd, resume); break;
      case "pause": if (run && !run.ended && !run.stopping) { run.paused = true; progress(true); } break;
      case "continue":
        if (run && !run.ended && !run.stopping) {
          run.paused = false;
          for (const item of run.items) if (item.state === "paused") item.state = "queued";
          pump();
        }
        break;
      case "abort":
        if (run && (!run.ended || run.aborting)) abort(run.batchId);
        else if (!run && !pending && cmd.batch_id) abort(cmd.batch_id);
        break;
      case "retry_commit": commit(); break;
      case "detach": detach(); break;
      case "finish":
        // Finish upload on the detail page: commit a batch without a run.
        if (!run && !pending) { run = newRun(cmd.batch_id, [], 0, true); commit(); }
        break;
    }
  }

  window.hooverUploads = {
    // A new page owns a new selection. Interrupted batches can resume from their detail page.
    attach(send) { detach(); sink = send; ensureInputs(); },
    command,
    sha256Hex(bytes) { const h = sha256(); h.update(bytes); return h.hex(); },
  };
})();
