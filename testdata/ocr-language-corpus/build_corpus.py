#!/usr/bin/env python3
"""Build the labelled OCR language image corpus.

Subcommands:
  pages    Render Wikipedia and Wikisource pages into JPG images, with visible text.
  no-text  Download and generate the images without text.
  finish   Sort manifest.jsonl and report orphan images and sizes.
  reencode Encode the kept PNG files again at --quality.

The command is resumable. A rerun skips each image that has a manifest row and a file.
Run it with an isolated interpreter. See Readme.md for the dependencies and the commands.
"""
import argparse, asyncio, base64, csv, datetime, hashlib, html as html_mod, io, json, os, random, re, subprocess, sys
import time, unicodedata, urllib.error, urllib.parse, urllib.request
from pathlib import Path

from PIL import Image, ImageFilter
from playwright.async_api import TimeoutError as PWTimeout, async_playwright
import numpy as np

UA = 'hoover4-ocr-corpus/1.0 (https://github.com/liquidinvestigations/hoover4)'
VIEW = {'width': 1240, 'height': 1754}
LONG_EDGE = 1754
TODAY = datetime.date.today().isoformat()
WP_LICENCE = 'CC BY-SA 4.0'
ALLOWED_HOSTS = ('.wikipedia.org', '.wikimedia.org', '.wikisource.org', 'wikisource.org')
HIDE_CSS = """
#siteNotice, #centralNotice, .frb, .cn-fundraising, .mw-notification-area,
.vector-sticky-header, #vector-sticky-header, #p-lang-btn-sticky-header { display: none !important; }
html { scroll-behavior: auto !important; }
"""
ARTICLE_CSS = """
.vector-column-start, .vector-column-end, .mw-table-of-contents-container, #vector-page-tools-pinned-container,
#vector-appearance-pinned-container, .vector-page-toolbar, #mw-panel, .vector-pinnable-element { display: none !important; }
.mw-page-container-inner { display: block !important; }
.mw-page-container, .mw-content-container, .vector-body, #mw-content-text, .mw-parser-output { max-width: none !important; }
"""
AZ_CYRL = dict(zip('abcçdeəfgğhxıijkqlmnoöprsştuüvyz', 'абҹчдеәфҝғһхыижкглмноөпрсштуүвјз'))
TRANSLIT_JS = """
(map) => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) { if (['SCRIPT', 'STYLE'].includes(n.parentElement.tagName)) continue;
    n.nodeValue = [...n.nodeValue].map(c => { const l = c.toLocaleLowerCase('az');
      if (!map[l]) return c;
      return l === c ? map[l] : map[l].toUpperCase(); }).join(''); } }
"""
SCRIPT_NAMES = {
    'Han': ('CJK',), 'Japanese': ('CJK', 'HIRAGANA', 'KATAKANA'), 'Hangul': ('HANGUL',), 'Fraktur': ('LATIN',),
    'Canadian_Aboriginal': ('CANADIAN',), 'Meetei Mayek': ('MEETEI MAYEK',),
}
EN_STOP = set('the of and in to is was for with as by that on are from'.split())
RU_STOP = set('в на и с по из что был для года от это'.split())
CYRILLIC_MINOR = {'abq', 'ady', 'ava', 'che', 'dar', 'inh', 'kbd', 'lbe', 'lez', 'tab'}
SIMPLIFIED_ONLY = set('这们来说国时会为对过经发动学问实与产开关长应处')
TRADITIONAL_ONLY = set('這們來說國時會為對過經發動學問實與產開關長應處')
# Fixed pages for language forms with no Wikipedia. A title with "#0.4" scrolls to that page fraction.
WIKISOURCE = {
    'enm': ('en.wikisource.org', ['Piers Ploughman (Wright)/Passus 16', 'Piers Ploughman (Wright)/Passus 19', 'Piers Ploughman (Wright)/Passus 19#0.5']),
    'frm': ('fr.wikisource.org', ['Les Œuvres de François Rabelais (Éditions Marty-Laveaux)/Pantagruel/33', 'Les Œuvres de François Rabelais (Éditions Marty-Laveaux)/Pantagruel/32', 'Les Œuvres de François Rabelais (Éditions Marty-Laveaux)/Pantagruel/31']),
    'ita_old': ('it.wikisource.org', ['Divina Commedia/Inferno/Canto I', 'Divina Commedia/Inferno/Canto III', 'Decameron/Giornata prima/Novella terza']),
    'spa_old': ('es.wikisource.org', ['Libro de Buen Amor/041', 'Libro de Buen Amor/069', 'La Celestina: Razones 01']),
    'grc': ('el.wikisource.org', ['Ιλιάς/Α', 'Ιλιάς/Δ', 'Σωκράτους Απολογία (Λιβάνιος)']),
    'kat_old': ('ka.wikisource.org', ['შუშანიკის წამება', 'შუშანიკის წამება#0.3', 'შუშანიკის წამება#0.6']),
    'syr': ('wikisource.org', ['Syriac book of Psalms', 'Syriac book of Psalms#0.3', 'Syriac book of Psalms#0.6']),
    'deu_latf': ('de.wikisource.org', ['Faust - Der Tragödie erster Teil', 'Faust - Der Tragödie erster Teil#0.4', 'Faust - Der Tragödie zweiter Teil']),
    'frk': ('de.wikisource.org', ['Rothkäppchen (1857)', 'Der Froschkönig oder der eiserne Heinrich (1857)', 'Hänsel und Grethel (1857)']),
}

# Latin-script Pali root texts. EasyOCR reads Pali in Latin script only, and no wiki holds it.
BILARA = 'https://raw.githubusercontent.com/suttacentral/bilara-data/published/root/pli/ms/sutta/'
BILARA_TEXTS = ['dn/dn1_root-pli-ms.json', 'mn/mn10_root-pli-ms.json', 'dn/dn16_root-pli-ms.json']
BILARA_HTML = ('<!doctype html><html lang="pi"><meta charset="utf-8"><body style="margin:60px 90px;'
               'font:21px/1.5 serif"><div id="mw-content-text">%s</div></body></html>')

VISIBLE_TEXT_JS = r"""
() => {
  const VH = innerHeight, VW = innerWidth;
  const content = document.querySelector('#mw-content-text');
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const lines = []; let cur = '', lastBlock = null, contentChars = 0, maxBottom = 0;
  const blockOf = el => { while (el && el !== document.body) {
      const d = getComputedStyle(el).display;
      if (!d.startsWith('inline') && d !== 'contents') return el;
      el = el.parentElement; } return document.body; };
  const charBottom = (n, i, r) => { const t = n.nodeValue;
      for (let j = i; j < Math.min(i + 8, t.length); j++) { r.setStart(n, j); r.setEnd(n, j + 1);
        const q = r.getClientRects(); if (q.length) return q[0].bottom; }
      return null; };
  let n;
  while ((n = walker.nextNode())) {
    const t = n.nodeValue; if (!t.trim()) continue;
    const p = n.parentElement;
    if (!p || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA'].includes(p.tagName)) continue;
    if (!p.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const rects = [...r.getClientRects()].filter(q => q.width > 1 && q.height > 1);
    const shown = rects.filter(q => q.bottom > 0 && q.top < VH && q.right > 0 && q.left < VW);
    if (!shown.length) continue;
    const q0 = shown[0];
    const x = Math.min(VW - 1, Math.max(0, (q0.left + q0.right) / 2));
    const y = Math.min(VH - 1, Math.max(0, (Math.max(q0.top, 0) + Math.min(q0.bottom, VH)) / 2));
    const hit = document.elementFromPoint(x, y);
    if (!hit || !(p.contains(hit) || hit.contains(p) || p.parentElement.contains(hit))) continue;
    let a = 0, b = t.length;
    if (rects[0].top < 0) { let lo = 0, hi = t.length - 1;
      while (lo < hi) { const m = (lo + hi) >> 1; const c = charBottom(n, m, r);
        if (c === null || c <= 0) lo = m + 1; else hi = m; } a = lo; }
    if (rects[rects.length - 1].bottom > VH) { let lo = a, hi = t.length;
      while (lo < hi) { const m = (lo + hi) >> 1; const c = charBottom(n, m, r);
        if (c !== null && c <= VH) lo = m + 1; else hi = m; } b = lo; }
    const s = t.slice(a, b); if (!s.trim()) continue;
    const blk = blockOf(p);
    if (blk !== lastBlock) { if (cur.trim()) lines.push(cur.trim()); cur = ''; lastBlock = blk; }
    cur += s.replace(/\s+/g, ' ');
    if (content && content.contains(p)) { contentChars += s.trim().length;
      maxBottom = Math.max(maxBottom, Math.min(VH, shown[shown.length - 1].bottom)); }
  }
  if (cur.trim()) lines.push(cur.trim());
  const cfg = (window.mw && mw.config) ? mw.config.get(['wgRevisionId', 'wgCurRevisionId', 'wgPageName', 'wgArticleId', 'wgUserVariant']) : {};
  return {text: lines.join('\n'), contentChars, maxBottom, htmlLang: document.documentElement.lang, cfg,};
}
"""
SCROLL_JS = r"""
(fraction) => {
  const c = document.querySelector('#mw-content-text') || document.body;
  const box = c.getBoundingClientRect();
  if (fraction > 0) { window.scrollTo(0, box.top + scrollY + box.height * fraction); return scrollY; }
  for (const el of c.querySelectorAll('p, li, dd, .poem, pre, div.prp-pages-output')) {
    if (el.closest('table, .infobox, .navbox, .ambox, .metadata, .hatnote, .toc')) continue;
    const r = el.getBoundingClientRect();
    if (r.width > 100 && (el.innerText || '').trim().length >= 60) {
      let y = r.top;
      const prev = el.previousElementSibling;
      if (prev && /^H[1-4]$|heading/.test(prev.tagName + ' ' + prev.className)) y = prev.getBoundingClientRect().top;
      window.scrollTo(0, Math.max(0, y + scrollY - 24)); return scrollY; }
  }
  window.scrollTo(0, Math.max(0, box.top + scrollY - 24)); return scrollY;
}
"""


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def http(url, retries=6, timeout=45):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == retries - 1:
                raise
            wait = float(e.headers.get('Retry-After') or 0) or 2 ** (i + 1)
            log('http', e.code, 'backoff', wait, url[:90])
            time.sleep(min(wait, 60))
        except (urllib.error.URLError, TimeoutError):
            if i == retries - 1:
                raise
            time.sleep(2 ** (i + 1))


def api(host, **params):
    params.update(format='json', formatversion=2, maxlag=5)
    return json.loads(http(f'https://{host}/w/api.php?' + urllib.parse.urlencode(params)))


def font_coverage():
    """Return the union of code points in all scalable fonts that fontconfig reports."""
    out = subprocess.run(['fc-list', ':scalable=true', '--format', '%{charset}\n'], capture_output=True, text=True, check=True).stdout
    cov = set()
    for line in set(out.splitlines()):
        for part in line.split():
            a, _, b = part.partition('-')
            cov.update(range(int(a, 16), int(b or a, 16) + 1))
    return cov


def letters(text):
    return [c for c in text if unicodedata.category(c)[0] in 'LM']


def script_share(text, script):
    names = SCRIPT_NAMES.get(script, (script.upper(),))
    ls = [c for c in text if unicodedata.category(c)[0] == 'L']
    if not ls:
        return 0.0
    return sum(unicodedata.name(c, '').startswith(names) for c in ls) / len(ls)


def stop_share(text, stop):
    words = re.findall(r'\w+', text.lower())
    return sum(w in stop for w in words) / max(len(words), 1)


class Store:
    def __init__(self, out, state):
        self.out, self.state = Path(out), Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.manifest = self.out / 'manifest.jsonl'
        self.rows = {}
        if self.manifest.exists():
            for line in self.manifest.read_text().splitlines():
                r = json.loads(line)
                if (self.out / r['path']).exists():
                    self.rows[r['path']] = r

    def done(self, path):
        return path in self.rows

    def add(self, row, jpeg, text, png=None):
        p = self.out / row['path']
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.tmp')
        tmp.write_bytes(jpeg)
        tmp.rename(p)
        if png:
            keep = self.state / 'png' / row['path'].replace('.jpg', '.png')
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(png)
        if text:
            p.with_suffix('.txt').write_text(text + '\n', encoding='utf-8')
        im = Image.open(io.BytesIO(jpeg))
        row.update(sha256=hashlib.sha256(jpeg).hexdigest(), width=im.width, height=im.height, bytes=len(jpeg),
                   text_path=str(Path(row['path']).with_suffix('.txt')) if text else None)
        self.rows[row['path']] = row
        with self.manifest.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')

    def load_state(self, folder):
        p = self.state / f'{folder}.json'
        return json.loads(p.read_text()) if p.exists() else {'rejected': {}, 'failed': {}}

    def save_state(self, folder, st):
        (self.state / f'{folder}.json').write_text(json.dumps(st, ensure_ascii=False, indent=0))


def jpeg_bytes(png, quality):
    im = Image.open(io.BytesIO(png)).convert('RGB')
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=quality, optimize=True, progressive=True)
    return b.getvalue()


def label(lang):
    return {k: (lang[k] or None) for k in ('tesseract', 'easyocr', 'iso639_1', 'iso639_3')} | {
        'language': lang['name'], 'script': lang['script']}


def page_url(host, title, variant):
    q = {'title': title}
    if variant:
        q['variant'] = variant
    return f'https://{host}/w/index.php?' + urllib.parse.urlencode(q)


def host_of(lang):
    return 'incubator.wikimedia.org' if lang['source'] == 'incubator' else f"{lang['wiki']}.wikipedia.org"


def candidates(lang, st, long_first=False):
    """Yield article titles for one language: random long pages first, the longest pages after that."""
    host, seen = host_of(lang), set(st['rejected'])
    if lang['source'] == 'incubator' or lang['title_prefix']:
        pages, cont = [], {}
        prefix = lang['title_prefix'] or f"Wp/{lang['wiki']}/"
        while True:
            r = api(host, action='query', list='allpages', apprefix=prefix, aplimit=500,
                    apfilterredir='nonredirects', apminsize=800, **cont)
            pages += r['query']['allpages']
            if 'continue' not in r:
                break
            cont = r['continue']
        random.shuffle(pages)
        yield from ((p['title'], 'prefix-random') for p in pages)
        return
    for minsize, rounds in () if long_first else ((6000, 4), (2500, 2)):
        for _ in range(rounds):
            r = api(host, action='query', generator='random', grnnamespace=0, grnlimit=40, prop='info', grnfilterredir='nonredirects')
            pages = [p for p in r.get('query', {}).get('pages', []) if p.get('length', 0) >= minsize and p['title'] not in seen]
            for p in pages:
                seen.add(p['title'])
                yield p['title'], 'random'
    pages, cont = [], {}
    for _ in range(4):
        r = api(host, action='query', list='allpages', apfilterredir='nonredirects', apminsize=8000 if long_first else 2500, aplimit=500, **cont)
        pages += r['query']['allpages']
        if 'continue' not in r:
            break
        cont = r['continue']
    random.shuffle(pages)
    for p in pages[:60]:
        if p['title'] not in seen:
            yield p['title'], 'long-allpages'


class Renderer:
    def __init__(self, ctx, args, cov, fraktur_css):
        self.ctx, self.args, self.cov, self.fraktur_css = ctx, args, cov, fraktur_css

    async def open(self):
        self.page = await self.ctx.new_page()
        await self.page.route('**/*', self._route)

    async def _route(self, route):
        u = urllib.parse.urlsplit(route.request.url)
        host = u.hostname or ''
        blocked = not (host.endswith(ALLOWED_HOSTS) or host == 'wikisource.org')
        blocked = blocked or 'beacon' in u.path or host.startswith('intake')
        # A file stored on a local wiki can be non-free. Only Commons files are free by policy.
        if host == 'upload.wikimedia.org' and not u.path.startswith(('/wikipedia/commons/', '/wikisource/')):
            blocked = True
        await (route.abort() if blocked else route.continue_())

    async def render_html(self, html):
        await self.page.set_content(html, wait_until='load')
        png = await self.page.screenshot(type='png')
        return (png, await self.page.evaluate(VISIBLE_TEXT_JS)), None

    async def render(self, url, kind, fraction, fraktur=False, translit=False):
        for attempt in range(6):
            try:
                resp = await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
            except PWTimeout:
                resp = None
            if resp is not None and resp.status == 429:
                wait = float(resp.headers.get('retry-after') or 0) or 5 * 2 ** attempt
                log('page 429 backoff', wait)
                await asyncio.sleep(min(wait, 120))
                continue
            break
        if resp is None or resp.status >= 400:
            return None, f'status {resp.status if resp else "timeout"}'
        try:
            await self.page.wait_for_load_state('load', timeout=15000)
        except PWTimeout:
            pass
        await self.page.add_style_tag(content=HIDE_CSS + ('' if kind == 'main' else ARTICLE_CSS) + (self.fraktur_css if fraktur else ''))
        if translit:
            await self.page.evaluate(TRANSLIT_JS, AZ_CYRL)
        if kind != 'main':
            await self.page.evaluate(SCROLL_JS, fraction)
        try:
            await self.page.wait_for_load_state('networkidle', timeout=5000)
        except PWTimeout:
            pass
        await self.page.evaluate('document.fonts.ready.then(() => 1)')
        await asyncio.sleep(0.3)
        png = await self.page.screenshot(type='png')
        info = await self.page.evaluate(VISIBLE_TEXT_JS)
        return (png, info), None

    def check(self, info, lang, kind, relax):
        text, script = info['text'], lang['script']
        ls = letters(text)
        missing = sorted({c for c in ls if ord(c) not in self.cov})
        miss = sum(c in missing for c in ls)
        share = script_share(text, script)
        m = {'visible_letters': len(ls), 'content_chars': info['contentChars'], 'text_bottom': round(info['maxBottom']),
             'script_share': round(share, 3), 'missing_glyphs': miss, 'missing_sample': ''.join(missing[:12])}
        if miss > max(3, 0.002 * len(ls)):
            return m, f'tofu {miss}/{len(ls)} {"".join(missing[:8])}'
        if kind == 'main':
            return m, None if share >= (0.2 if lang['source'] == 'incubator' or relax else 0.35) and len(ls) >= 150 else f'main script share {share:.2f} letters {len(ls)}'
        min_chars, min_bottom, min_share = (250, 700, 0.5) if relax else (800, 1200, 0.7)
        if script in ('Han', 'Japanese', 'Tibetan', 'Hangul', 'Thaana'):
            min_chars //= 2
        if info['contentChars'] < min_chars or info['maxBottom'] < min_bottom:
            return m, f"short {info['contentChars']} chars bottom {info['maxBottom']:.0f}"
        if share < min_share:
            return m, f'script share {share:.2f}'
        if lang['iso639_3'] not in ('eng', 'enm') and stop_share(text, EN_STOP) > (0.1 if script == 'Latin' else 0.03):
            return m, 'english text'
        if lang['folder'] in CYRILLIC_MINOR and stop_share(text, RU_STOP) > 0.12:
            return m, 'russian text'
        if lang['script'] == 'Han':
            s, t = sum(c in SIMPLIFIED_ONLY for c in text), sum(c in TRADITIONAL_ONLY for c in text)
            bad = t > s if lang['variant'] == 'zh-cn' else s > t
            m['simplified_traditional'] = [s, t]
            if bad:
                return m, f'wrong han variant {s}/{t}'
        return m, None


async def do_bilara(lang, store, rnd, args):
    sha = json.loads(await asyncio.to_thread(http, 'https://api.github.com/repos/suttacentral/bilara-data/commits/published'))['sha']
    for n, name in enumerate(BILARA_TEXTS, 1):
        path = f"{lang['folder']}/source-{n}.jpg"
        if store.done(path):
            continue
        url = BILARA + name
        data = json.loads(await asyncio.to_thread(http, url))
        paras = {}
        for key, seg in data.items():
            paras.setdefault(key.rsplit('.', 1)[0], []).append(html_mod.escape(seg))
        got, _ = await rnd.render_html(BILARA_HTML % ''.join(f"<p>{''.join(p)}</p>" for p in paras.values()))
        png, info = got
        metrics, reason = rnd.check(info, lang, 'source', False)
        if reason:
            log(' FAILED', path, reason)
            continue
        row = label(lang) | {
            'path': path, 'has_text': True, 'kind': 'source', 'source_url': url.replace('/published/', f'/{sha}/'),
            'page_title': name, 'revision_id': sha, 'retrieved': TODAY, 'licence': 'CC0 1.0', 'selection': 'fixed',
            'variant': None, 'html_lang': 'pi', 'relaxed_fill': False, 'quality': args.quality,
            'source_kind': lang['source'], **metrics}
        store.add(row, jpeg_bytes(png, args.quality), info['text'], png)
        log(' ok', path, metrics['content_chars'])


async def do_language(lang, store, rnd, args):
    if lang['source'] == 'suttacentral':
        return await do_bilara(lang, store, rnd, args)
    folder, host = lang['folder'], None
    st = store.load_state(folder)
    is_source = lang['source'] == 'wikisource'
    n_random = args.random_pages
    if is_source:
        host, titles = WIKISOURCE[folder]
        slots = [('wikisource', i + 1) for i in range(len(titles))]
    else:
        host = host_of(lang)
        slots = [('main', 1)] + [('random', i + 1) for i in range(n_random)]
    todo = [s for s in slots if not store.done(f'{folder}/{s[0]}-{s[1]}.jpg')]
    if not todo:
        return
    log('start', folder, host, 'todo', len(todo))

    async def accept(kind, n, title, url, fraction, selection):
        got, err = await rnd.render(url, kind, fraction, fraktur=lang['script'] == 'Fraktur', translit=lang['folder'] == 'aze_cyrl')
        if err:
            return err
        (png, info) = got
        metrics, reason = rnd.check(info, lang, kind, args.relax)
        if reason:
            if lang['script'] == 'Fraktur' or kind == 'main':
                log(' reject', folder, kind, title, reason, metrics)
            return reason
        rev = info['cfg'].get('wgRevisionId') or info['cfg'].get('wgCurRevisionId')
        src = f'https://{host}/w/index.php?' + urllib.parse.urlencode(
            {'title': title} | ({'oldid': rev} if rev else {}) | ({'variant': lang['variant']} if lang['variant'] else {}))
        row = label(lang) | {
            'path': f'{folder}/{kind}-{n}.jpg', 'has_text': True, 'kind': kind, 'source_url': src, 'page_title': title,
            'revision_id': rev, 'retrieved': TODAY, 'licence': WP_LICENCE, 'selection': selection,
            'variant': lang['variant'] or None, 'html_lang': info['htmlLang'], 'relaxed_fill': bool(args.relax),
            'quality': args.quality, 'source_kind': lang['source'], **metrics}
        if lang['folder'] == 'aze_cyrl':
            row['script_transliterated'] = True
        store.add(row, jpeg_bytes(png, args.quality), info['text'], png)
        log(' ok', row['path'], f"{metrics['content_chars']}c share={metrics['script_share']} {len(title) and title[:40]}")
        return None

    if is_source:
        for (kind, n), t in zip(slots, titles):
            if store.done(f'{folder}/{kind}-{n}.jpg'):
                continue
            title, _, frac = t.partition('#')
            err = await accept(kind, n, title, page_url(host, title, ''), float(frac or 0), 'fixed')
            if err:
                st['failed'][t] = err
                log(' FAILED', folder, t, err)
    else:
        if ('main', 1) in todo:
            title = await asyncio.to_thread(main_title, lang)
            err = await accept('main', 1, title, page_url(host, title, lang['variant']), 0, 'main') if title else 'no main page'
            if err:
                st['failed']['main'] = err
                log(' FAILED main', folder, err)
        remaining = [s for s in todo if s[0] == 'random']
        tried = 0
        if remaining:
            gen = candidates(lang, st, args.long_first)
            while remaining and tried < args.max_tries:
                item = await asyncio.to_thread(next, gen, None)
                if item is None:
                    break
                title, selection = item
                if title in st['rejected'] and not args.relax:
                    continue
                if any(r['page_title'] == title for r in store.rows.values() if r['path'].startswith(folder + '/')):
                    continue
                tried += 1
                err = await accept('random', remaining[0][1], title, page_url(host, title, lang['variant']), 0, selection)
                if err:
                    st['rejected'][title] = err
                else:
                    remaining.pop(0)
            if remaining:
                log(' SHORT', folder, 'missing', len(remaining), 'tried', tried)
                st['failed']['random'] = f'{len(remaining)} slots open after {tried} tries'
    store.save_state(folder, st)


def main_title(lang):
    if lang['source'] == 'incubator':
        t = f"Wp/{lang['wiki']}/Main Page"
        r = api('incubator.wikimedia.org', action='query', titles=t, prop='info', redirects=1)
        return None if r['query']['pages'][0].get('missing') else r['query']['pages'][0]['title']
    return api(host_of(lang), action='query', meta='siteinfo', siprop='general')['query']['general']['mainpage']


async def run_pages(args):
    out = Path(args.out)
    langs = list(csv.DictReader(open(out / 'languages.tsv', encoding='utf-8'), delimiter='\t'))
    if args.only:
        only = set(args.only.split(','))
        langs = [l for l in langs if l['folder'] in only]
    store, cov = Store(out, args.state), font_coverage()
    log('font coverage', len(cov), 'code points; languages', len(langs))
    css = ''
    if args.fraktur_font and Path(args.fraktur_font).exists():
        b64 = base64.b64encode(Path(args.fraktur_font).read_bytes()).decode()
        css = ("@font-face{font-family:'corpusfraktur';src:url(data:font/ttf;base64," + b64 + ")}"
               "#mw-content-text, #mw-content-text *, #firstHeading {font-family:'corpusfraktur' !important}")
    deadline = time.time() + args.max_seconds
    queue = asyncio.Queue()
    for l in langs:
        queue.put_nowait(l)
    async with async_playwright() as p:
        br = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, chromium_sandbox=True,
                                     args=['--hide-scrollbars', '--disable-gpu'])

        async def worker():
            ctx = await br.new_context(viewport=VIEW, user_agent=UA, locale='en-US', java_script_enabled=True, service_workers='block')
            rnd = Renderer(ctx, args, cov, css)
            await rnd.open()
            while time.time() < deadline:
                try:
                    lang = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    await do_language(lang, store, rnd, args)
                except Exception as e:
                    log('ERROR', lang['folder'], repr(e)[:300])
                    await rnd.page.close()
                    await rnd.open()
            await ctx.close()

        await asyncio.gather(*(worker() for _ in range(args.workers)))
        await br.close()
    log('rows', len(store.rows), 'queue left', queue.qsize())
    return 3 if queue.qsize() else 0


def noise_page(seed, kind):
    rng = np.random.default_rng(seed)
    h, w = LONG_EDGE, 1240
    if kind == 'white':
        a = np.full((h, w), 255, np.uint8)
    elif kind == 'scan':
        a = np.clip(rng.normal(242, 5, (h, w)) - 60 * (rng.random((h, w)) < 0.0006), 0, 255).astype(np.uint8)
    elif kind == 'grey':
        small = Image.fromarray(np.clip(rng.normal(205, 30, (h // 8, w // 8)), 0, 255).astype(np.uint8))
        a = np.asarray(small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6)))
    elif kind == 'cream':
        grad = np.linspace(236, 226, h)[:, None]
        a = np.clip(grad + rng.normal(0, 3, (h, w)), 0, 255).astype(np.uint8)
    b = io.BytesIO()
    Image.fromarray(a).convert('RGB').save(b, 'JPEG', quality=67, optimize=True)
    return b.getvalue()


def run_no_text(args):
    out = Path(args.out)
    store = Store(out, args.state)
    free = re.compile(r'^(public domain|pd|cc0|cc[ -]by(-sa)?[ -]\d)', re.I)
    rows = list(csv.DictReader(open(out / 'no-text-sources.tsv', encoding='utf-8'), delimiter='\t'))
    n = 0
    for r in rows:
        n += 1
        path = f"no-text/{r['id']}.jpg"
        if store.done(path):
            continue
        t = 'File:' + r['title']
        q = api('commons.wikimedia.org', action='query', titles=t, prop='imageinfo', iiprop='url|extmetadata|size|mime', iiurlwidth=2560)
        ii = q['query']['pages'][0].get('imageinfo')
        if not ii:
            log('missing', t)
            continue
        ii = ii[0]
        lic = ii['extmetadata'].get('LicenseShortName', {}).get('value', '')
        if not free.match(lic):
            log('licence refused', t, lic)
            continue
        raw = Image.open(io.BytesIO(http(ii.get('thumburl') or ii['url']))).convert('RGBA')
        im = Image.new('RGB', raw.size, 'white')
        im.paste(raw, mask=raw.getchannel('A'))
        im.thumbnail((LONG_EDGE, LONG_EDGE), Image.LANCZOS)
        if max(im.size) < LONG_EDGE:
            f = LONG_EDGE / max(im.size)
            im = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
        b = io.BytesIO()
        im.save(b, 'JPEG', quality=args.quality, optimize=True, progressive=True)
        artist = re.sub(r'<[^>]+>', '', ii['extmetadata'].get('Artist', {}).get('value', '')).strip()
        store.add({'path': path, 'has_text': False, 'kind': 'no-text', 'subkind': r['subkind'], 'source_url': ii['descriptionurl'],
                   'page_title': r['title'], 'revision_id': None, 'retrieved': TODAY, 'licence': lic, 'artist': artist[:200],
                   'tesseract': None, 'easyocr': None, 'iso639_1': None, 'iso639_3': None, 'language': None, 'script': None}, b.getvalue(), '')
        log('ok', path, lic, r['title'][:60])
        time.sleep(2)
    for i, kind in enumerate(('white', 'white', 'scan', 'scan', 'grey', 'cream')):
        path = f'no-text/generated-{i + 1}.jpg'
        if not store.done(path):
            store.add({'path': path, 'has_text': False, 'kind': 'no-text', 'subkind': f'generated-{kind}', 'source_url': None, 'page_title': None,
                       'revision_id': None, 'retrieved': TODAY, 'licence': 'CC0 1.0', 'tesseract': None, 'easyocr': None, 'iso639_1': None,
                       'iso639_3': None, 'language': None, 'script': None}, noise_page(i, kind), '')
    return 0


def run_reencode(args):
    """Encode each kept PNG again at --quality, for the size limit."""
    out = Path(args.out)
    store = Store(out, args.state)
    for path, row in store.rows.items():
        keep = store.state / 'png' / path.replace('.jpg', '.png')
        if not keep.exists():
            continue
        jpeg = jpeg_bytes(keep.read_bytes(), args.quality)
        (out / path).write_bytes(jpeg)
        row.update(sha256=hashlib.sha256(jpeg).hexdigest(), bytes=len(jpeg), quality=args.quality)
    return run_finish(args, store)


def run_finish(args, store=None):
    out = Path(args.out)
    store = store or Store(out, args.state)
    rows = sorted(store.rows.values(), key=lambda r: r['path'])
    known = {r['path'] for r in rows}
    for f in out.rglob('*.jpg'):
        if str(f.relative_to(out)) not in known:
            log('orphan image', f)
    with (out / 'manifest.jsonl').open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    total = sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
    log('rows', len(rows), 'bytes', total, 'jpg', sum(r['bytes'] for r in rows))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['pages', 'no-text', 'finish', 'reencode'])
    ap.add_argument('--out', default=str(Path(__file__).resolve().parent), help='corpus folder')
    ap.add_argument('--state', default='/tmp/ocr-language-corpus/state', help='folder for rejected page titles')
    ap.add_argument('--only', help='comma list of folder names')
    ap.add_argument('--quality', type=int, default=67)
    ap.add_argument('--random-pages', type=int, default=3)
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--max-tries', type=int, default=25, help='article renders for one language in one run')
    ap.add_argument('--max-seconds', type=int, default=500)
    ap.add_argument('--long-first', action='store_true', help='skip random selection, for wikis of bot stubs')
    ap.add_argument('--relax', action='store_true', help='accept shorter pages and mark them in the manifest')
    ap.add_argument('--fraktur-font', default='/tmp/ocr-language-corpus/fonts/UnifrakturMaguntia-Book.ttf')
    a = ap.parse_args()
    if a.command == 'pages':
        return asyncio.run(run_pages(a))
    return {'no-text': run_no_text, 'finish': run_finish, 'reencode': run_reencode}[a.command](a)


if __name__ == '__main__':
    sys.exit(main())
