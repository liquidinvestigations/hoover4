import nodeResolve from '@rollup/plugin-node-resolve';
import copy from 'rollup-plugin-copy';
import rollupReplace from '@rollup/plugin-replace';
import dts from 'rollup-plugin-dts';
import typescript from '@rollup/plugin-typescript';
import commonjs from '@rollup/plugin-commonjs';
import MagicString from 'magic-string';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const SRC = 'src';
const DIST = 'dist';
const WASM = 'pdfium.wasm';
const ENTRY_ESM = `${SRC}/index.esm.ts`;
const ENTRY_CJS = `${SRC}/index.cjs.ts`;

const EXTERNAL_NODE_PACKAGES = ['fs', 'path', 'crypto'];

// Read version from package.json
const __dirname = dirname(fileURLToPath(import.meta.url));
const { version } = JSON.parse(readFileSync(resolve(__dirname, 'package.json'), 'utf8'));

function versionReplacer() {
  return rollupReplace({
    preventAssignment: true,
    values: {
      __PDFIUM_VERSION__: version,
    },
  });
}

const common = {
  treeshake: true,
  external: (id) => id === 'module' || id.endsWith(`/${WASM}`),
  plugins: [
    typescript(),
    nodeResolve({ extensions: ['.js', '.ts'] }),
    copy({ targets: [{ src: `${SRC}/vendor/${WASM}`, dest: DIST }] }),
    versionReplacer(), // Add version replacement to all builds
  ],
};

function patchEsmPath() {
  return {
    name: 'patch-esm-path',
    renderChunk(code) {
      const s = new MagicString(code);
      let hasChange = false;

      code.replace(/pdfium\.esm\.wasm/g, (match, offset) => {
        hasChange = true;
        s.overwrite(offset, offset + match.length, 'pdfium.wasm');
        return match;
      });

      if (!hasChange) return null; // nothing touched

      return {
        code: s.toString(),
        map: s.generateMap({ hires: true }),
      };
    },
  };
}

function setNotNodeEnvironment() {
  return rollupReplace({
    preventAssignment: true,
    values: {
      // This is helpefull for properly tree-shaking the node.js code
      ENVIRONMENT_IS_NODE: 'false',
    },
  });
}

/* -------- 1.  Browser-only bundle -------------------------------- */
const browser = {
  ...common,
  input: ENTRY_ESM,
  output: {
    file: `${DIST}/index.browser.js`,
    format: 'esm',
    sourcemap: true,
  },
  plugins: [...common.plugins, setNotNodeEnvironment(), patchEsmPath()],
};

/* -------- 2.  Neutral ESM (keeps Node path for SSR) -------------- */
const neutral = {
  ...common,
  input: ENTRY_ESM,
  output: {
    file: `${DIST}/index.js`,
    format: 'esm',
    sourcemap: true,
  },
  plugins: [...common.plugins, patchEsmPath()],
  // keeps ENVIRONMENT_IS_NODE, doesn't patch import('module')
};

/* -------- 3.  CommonJS bundle ----------------------------------- */
const cjs = {
  ...common,
  input: ENTRY_CJS,
  output: {
    file: `${DIST}/index.cjs`,
    format: 'cjs',
    exports: 'named',
    sourcemap: true,
  },
  plugins: [
    ...common.plugins,
    commonjs({
      strictRequires: true,
      ignore: EXTERNAL_NODE_PACKAGES,
    }),
  ],
};

/* -------- 4.  Typings (d.ts & d.cts) ---------------------------- */
const typesEsm = {
  input: ENTRY_ESM,
  plugins: [dts()],
  output: { file: `${DIST}/index.d.ts`, format: 'es' },
};
const typesCjs = {
  input: ENTRY_CJS,
  plugins: [dts()],
  output: { file: `${DIST}/index.d.cts`, format: 'es' },
};

export default [browser, neutral, cjs, typesEsm, typesCjs];
