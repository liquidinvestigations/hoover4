import { build, Plugin } from 'vite';

const wasmUrlReplacer: Plugin = {
  name: 'wasm-url-replacer',
  enforce: 'pre',
  transform(code) {
    const pat = /new URL\(\s*["']pdfium\.wasm["']\s*,\s*import\.meta\.url\s*\)\.href/g;
    return pat.test(code) ? code.replace(pat, '"pdfium.wasm"') : null;
  },
};

export async function bundleWorker(): Promise<string> {
  const result = await build({
    logLevel: 'silent',
    configFile: false,
    plugins: [wasmUrlReplacer],
    build: {
      write: false,
      lib: {
        entry: 'src/lib/pdfium/worker.ts',
        formats: ['es'],
        fileName: () => 'worker.js',
      },
      minify: 'terser',
      rollupOptions: {
        output: { inlineDynamicImports: true },
      },
    },
  });

  const results = Array.isArray(result) ? result : [result];

  for (const r of results) {
    if ('output' in r) {
      return r.output[0].code;
    }
  }

  throw new Error('vite.build returned a RollupWatcher – cannot extract code');
}
