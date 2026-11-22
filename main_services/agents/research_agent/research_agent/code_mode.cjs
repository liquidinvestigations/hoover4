const fs = require("node:fs");
const { getQuickJS } = require("quickjs-emscripten");

let pending = Buffer.alloc(0);

function readLine() {
  const parts = [];
  let total = 0;
  while (total < 16 * 1024 * 1024) {
    const newline = pending.indexOf(10);
    if (newline !== -1) {
      parts.push(pending.subarray(0, newline));
      pending = pending.subarray(newline + 1);
      return Buffer.concat(parts).toString("utf8");
    }
    parts.push(pending);
    total += pending.length;
    const chunk = Buffer.allocUnsafe(65536);
    const count = fs.readSync(0, chunk, 0, chunk.length, null);
    if (!count) throw Error("The broker closed.");
    pending = chunk.subarray(0, count);
  }
  throw Error("The broker response exceeds the input limit.");
}

function send(value) {
  const buffer = Buffer.from(JSON.stringify(value) + "\n");
  if (buffer.length > 1024 * 1024) throw Error("The program output exceeds the byte limit.");
  for (let offset = 0; offset < buffer.length;) {
    offset += fs.writeSync(1, buffer, offset, buffer.length - offset);
  }
}

async function run() {
  const { code, names, timeout } = JSON.parse(readLine());
  const quickjs = await getQuickJS();
  const runtime = quickjs.newRuntime();
  const deadline = Date.now() + timeout;
  runtime.setMemoryLimit(32 * 1024 * 1024);
  runtime.setMaxStackSize(512 * 1024);
  runtime.setInterruptHandler(() => Date.now() >= deadline);
  const vm = runtime.newContext();
  try {
    for (const name of names) {
      const fn = vm.newFunction(name, args => {
        try {
          send({ call: name, args: args ? vm.dump(args) : {} });
          const reply = readLine();
          const decoded = JSON.parse(reply);
          if (decoded.broker_error) throw Error(decoded.broker_error);
          const value = vm.evalCode("JSON.parse(" + JSON.stringify(reply) + ")");
          return vm.unwrapResult(value);
        } catch (error) {
          return { error: vm.newError(String(error.message || error)) };
        }
      });
      vm.defineProp(vm.global, name, { value: fn, configurable: false });
      fn.dispose();
    }
    const execution = vm.evalCode("(async () => {\n" + code + "\n})()");
    const promise = vm.unwrapResult(execution);
    try {
      const jobs = runtime.executePendingJobs();
      if (jobs.error) {
        const error = vm.dump(jobs.error);
        jobs.error.dispose();
        throw Error(error.message || String(error));
      }
      const state = vm.getPromiseState(promise);
      if (state.type === "pending") throw Error("The program has an unresolved promise.");
      if (state.type === "rejected") {
        const failure = vm.dump(state.error);
        state.error.dispose();
        throw Error(failure.message || String(failure));
      }
      const output = vm.dump(state.value);
      state.value.dispose();
      send({ output: output === undefined ? null : output });
    } finally {
      promise.dispose();
    }
  } finally {
    vm.dispose();
    runtime.dispose();
  }
}

run().catch(error => send({ error: String(error.message || error).slice(0, 2000) }));
