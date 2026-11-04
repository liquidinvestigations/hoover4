# OCR language image corpus

This corpus holds labelled JPG images for a benchmark of two tasks.
The first task decides whether an image has text.
The second task decides which language the text has.
The corpus covers the languages of Tesseract and EasyOCR.

## Contents

| count | item |
|---|---|
| 140 | language folders |
| 540 | images with text |
| 40 | images without text |
| 147 MB | total size |

Each language image is one viewport of a rendered page.
The viewport is 1240 by 1754 pixels, which is A4 at 150 dpi.
The JPEG quality is 67.

## Folder layout

| path | content |
|---|---|
| `<code>/main-1.jpg` | The Wikipedia main page in its normal layout. |
| `<code>/random-<n>.jpg` | An article page, scrolled to the start of the body text. The side columns are hidden. |
| `<code>/wikisource-<n>.jpg` | A Wikisource page for a language form that has no Wikipedia. |
| `<code>/source-<n>.jpg` | A root text from SuttaCentral, for Pali in Latin script. |
| `<code>/<kind>-<n>.txt` | The DOM text inside the viewport. |
| `no-text/` | Photographs, drawings, charts and generated pages. The long edge is 1754 pixels. |
| `manifest.jsonl` | One row for each image. |
| `languages.tsv` | The mapping table of language codes, scripts and sources. |
| `no-text-sources.tsv` | The selected Commons files. |
| `gaps.tsv` | Missing images, substitutions and entries out of scope. |
| `build_corpus.py` | The generator. |

`<code>` is the Tesseract code. A language that only EasyOCR supports uses the EasyOCR code.

## Labels

Each manifest row has these fields:

- `path`, `text_path`, `kind`, `has_text`
- `tesseract`, `easyocr`, `iso639_1`, `iso639_3`, `language`, `script`
- `source_url`, `page_title`, `revision_id`, `retrieved`, `licence`
- `sha256`, `width`, `height`, `bytes`

Language images also have build measurements, for example `script_share` and `missing_glyphs`.
The `script` field states the script in the image.

Some EasyOCR codes differ from ISO 639-3.
EasyOCR `ang` is Angika, ISO `anp`. ISO `ang` is Old English, which the corpus does not hold.
EasyOCR `mah` is Magahi, ISO `mag`. ISO `mah` is Marshallese.

`bh` and `bho` use the same wiki, so their main page images show one page.
Pairs of script forms of a language also share a main page, for example `srp` and `srp_latn`.

Read `gaps.tsv` before you calculate a result for each language.

## Selection checks

A random article was accepted after these checks:

- The article filled most of the viewport with text.
- Most letters were in the expected Unicode script.
- The text was not mainly English, or mainly Russian for small Cyrillic wikis.
- For Chinese, the characters matched the simplified or traditional form.
- All installed scalable fonts together covered the visible letters.

These checks do not prove the language of a Latin-script page.
A page can quote another language.

## Licence

Wikipedia and Wikisource text is under CC BY-SA 4.0.
The authors are the contributors to the page revision in `source_url`.
The images of pages are adapted from these revisions, and they are under CC BY-SA 4.0.

Pictures inside a page come from Wikimedia Commons, and each picture keeps its own licence.
The build blocks files that a local wiki stores, because these files can be non-free.

The SuttaCentral root texts are CC0. The `no-text` rows state the licence and the source of each file.
The generated `no-text` pages are CC0.
Logos and marks in a Commons picture can have other rights.

## Regenerate the corpus

The build needs Chromium, fontconfig, and Python packages `playwright`, `pillow` and `numpy`.
The Fraktur rows need the font `UnifrakturMaguntia-Book.ttf` from Google Fonts, under the SIL Open Font License.
The `--fraktur-font` option gives its path.

```sh
python -I build_corpus.py pages --out . --quality 67
python -I build_corpus.py no-text --out . --quality 67
python -I build_corpus.py finish --out .
```

A rerun skips each image that has a manifest row and a file.
The `--relax` option accepts shorter pages for small wikis and marks them in the manifest.
The `--long-first` option skips random selection on a wiki of bot-written stubs.
Wikipedia pages change, so a new build gives different images and revisions.
