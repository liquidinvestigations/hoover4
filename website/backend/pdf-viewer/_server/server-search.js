import http from 'http';
import fs from 'fs';
import { init } from './dist/pdfium/dist/index.js';
import { PdfiumNative, PdfEngine } from './dist/engines/dist/index.js';
import { MatchFlag } from './dist/models/dist/index.js';


const pdfiumWasm = './dist/pdfium/dist/pdfium.wasm';
console.log("INIT. LOADING WASM: ", pdfiumWasm);
const wasmBinary = fs.readFileSync(pdfiumWasm);
console.log("WASM BINARY: ", wasmBinary.length, " bytes");

async function initPdfium() {
  const pdfiumModule = await init({ wasmBinary });
  console.log("PDFIUM MODULE LOADED.");
  const native = new PdfiumNative(pdfiumModule);
  console.log("PDFIUM NATIVE CREATED.");
  const engine = new PdfEngine(native, {});
  console.log("PDF ENGINE CREATED.");

  return engine;
}


// The PDF arrives as the request body and the keywords as a query parameter.
//
// Passing a URL for this process to fetch instead points it back at the website's own
// HTTP port: the server asking itself for a document it already knows how to read. Such a
// request is not a browser's — it carries no session cookie — so a download route that
// requires one silently kills in-document search. The bytes travel over the connection
// that asked for the search, and nothing here reaches back into the caller.
async function searchPdfMultipleKeywords(pdfBytes, keywords) {
  var results = [];

  var engine = await initPdfium();
  try {
    // `id` only labels the document inside the engine's worker queue; nothing fetches it.
    const doc = await engine.openDocumentBuffer({
      id: `pdf-${pdfBytes.byteLength}-${keywords.length}`,
      content: pdfBytes.buffer.slice(pdfBytes.byteOffset, pdfBytes.byteOffset + pdfBytes.byteLength),
    }).toPromise();
    for (const keyword of keywords) {
      const result_set = await engine.searchAllPages(doc, keyword, {
        flags: [MatchFlag.MatchWholeWord, MatchFlag.MatchConsecutive]
      }).toPromise();
      results.push({ keyword, result_set });
    }
    return results;
  } finally {
    engine.destroy();
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'POST') {
    const chunks = [];
    req.on('data', chunk => {
      chunks.push(chunk);
    });
    req.on('end', async () => {
      try {
        const params = new URL(req.url, 'http://localhost').searchParams;
        let keywords;
        try {
          keywords = JSON.parse(params.get('keywords') || 'null');
        } catch (e) {
          keywords = null;
        }
        const pdfBytes = Buffer.concat(chunks);
        if (!Array.isArray(keywords) || pdfBytes.length === 0) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Need a ?keywords=<json array> and a PDF body' }));
          return;
        }

        console.log(`Searching ${pdfBytes.length} bytes of PDF for keywords: ${keywords.join(', ')}`);
        const results = await searchPdfMultipleKeywords(pdfBytes, keywords);

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
    res.end(JSON.stringify({ error: 'Method Not Allowed. POST the PDF bytes with ?keywords=' }));
  }
});

const PORT = 13500;
server.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});

