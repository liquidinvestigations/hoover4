import http from 'http';
import fs from 'fs';
import { init } from './dist/pdfium/dist/index.js';
import { PdfiumNative, PdfEngine } from './dist/engines/dist/index.js';
import { MatchFlag } from './dist/models/dist/index.js';

async function initPdfium() {
  const pdfiumWasm = './dist/pdfium/dist/pdfium.wasm';
  console.log("INIT. LOADING WASM: ", pdfiumWasm);
  const wasmBinary = fs.readFileSync(pdfiumWasm);
  console.log("WASM BINARY: ", wasmBinary.length, " bytes");

  const pdfiumModule = await init({ wasmBinary });
  console.log("PDFIUM MODULE LOADED.");
  const native = new PdfiumNative(pdfiumModule);
  console.log("PDFIUM NATIVE CREATED.");
  const engine = new PdfEngine(native, {});
  console.log("PDF ENGINE CREATED.");

  return engine;
}

const ENGINE = await initPdfium();

async function searchPdfMultipleKeywords(pdf_url, keywords) {
  var results = [];
  const doc = await ENGINE.openDocumentUrl({ id: pdf_url, url: pdf_url }).toPromise();
  for (const keyword of keywords) {
    const result_set = await ENGINE.searchAllPages(doc, keyword, {
      flags: [MatchFlag.MatchWholeWord, MatchFlag.MatchConsecutive]
    }).toPromise();
    results.push({ keyword, result_set });
  }
  await ENGINE.closeDocument(doc).toPromise();
  return results;
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET') {
    let body = '';
    req.on('data', chunk => {
      body += chunk.toString();
    });
    req.on('end', async () => {
      try {
        const { url, keywords } = JSON.parse(body || '{}');
        if (!url || !keywords || !Array.isArray(keywords)) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing url or keywords list in JSON body' }));
          return;
        }

        console.log(`Searching PDF: ${url} for keywords: ${keywords.join(', ')}`);
        const results = await searchPdfMultipleKeywords(url, keywords);

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(results));
      } catch (error) {
        console.error('Error processing request:', error);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal Server Error', details: error.message }));
      }
    });
  } else {
    res.writeHead(405, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Method Not Allowed. Use GET with JSON body.' }));
  }
});

const PORT = 13500;
server.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});

