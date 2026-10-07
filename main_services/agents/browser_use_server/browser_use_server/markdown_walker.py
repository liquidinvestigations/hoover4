"""Extract Markdown from the complete document body.

Remove navigation, forms, scripts, media, and unrelated controls.
Preserve source lists, tables, captions, code, and package metadata.
Keep links unless the caller disables them.
Wait for a quiet DOM when a short page is still loading.
Return non-HTML documents as text without an injected library.
"""

from __future__ import annotations

#: The DOM must not change for this long before the walk starts, on a short or loading page.
QUIET_MS = 600

#: The longest wait for a quiet DOM.
QUIET_MAX_MS = 4000

#: A page with less visible text than this, in characters, waits for a quiet DOM.
SHORT_PAGE_CHARS = 2000

#: The walk. `walk(doc, {links})` returns the Markdown of `doc`.
WALKER_JS = r"""
function walk(doc, opts) {
  const keepLinks = opts.links !== false;
  const win = doc.defaultView;
  const base = doc.baseURI || '';
  const DROP_TAGS = new Set(['SCRIPT','STYLE','NOSCRIPT','SVG','TEMPLATE','IFRAME','FORM','INPUT','SELECT','TEXTAREA','DIALOG','CANVAS','VIDEO','AUDIO','OBJECT','EMBED','MAP','LINK','META']);
  const PAGE_TAGS = new Set(['NAV','HEADER','FOOTER','ASIDE']);
  const DROP_ROLES = new Set(['navigation','banner','contentinfo','complementary','search','dialog','alertdialog','menu','menubar','tablist','toolbar','tooltip']);
  // A strong class or id word removes a box always. A weak word removes it only when it is
  // short or mostly links, because sites also use these words on content.
  const STRONG = /(^|[\s_-])(cookie|cookies|consent|gdpr|cmp|advert|advertisement|ads|adslot|sponsor|sponsored|newsletter|paywall|modal|popup|overlay|share|sharing|social|navbox|navbar|breadcrumb|breadcrumbs|editsection|noprint|skiplink)($|[\s_-])/i;
  const WEAK = /(^|\s)(banner|promo|subscribe|related|recommended|menu|toc|skip|footer|header|masthead|nav)($|[\s_-])/i;

  const descriptions = new Set(Array.from(doc.querySelectorAll('[aria-describedby]'))
    .flatMap(el => (el.getAttribute('aria-describedby') || '').split(/\s+/)));
  function hidden(el) {
    if (el.id && descriptions.has(el.id)) return false;
    if (el.matches('pre, code') || el.querySelector('pre, code')) return false;
    if (el.hidden || el.getAttribute('aria-hidden') === 'true') return true;
    if (typeof el.checkVisibility === 'function' && win && doc.documentElement.getClientRects().length) {
      try { if (!el.checkVisibility({checkOpacity: false, checkVisibilityCSS: true})) return true; } catch (e) {}
    }
    return false;
  }
  function textLen(el) { return (el.textContent || '').replace(/\s+/g, ' ').trim().length; }
  function linkLen(el) { let n = 0; for (const a of el.querySelectorAll('a')) n += textLen(a); return n; }

  // Keep source sections outside the largest article or main element.
  const root = doc.body || doc.documentElement;
  const rootLen = Math.max(1, textLen(root));

  // 2. What to skip. Never an ancestor of the root, and never a box with most of the text.
  const skip = new Set();
  const inArticle = el => !!el.closest('article, main, [role=main]');
  for (const el of root.querySelectorAll('*')) {
    if (skip.has(el)) continue;
    const tag = el.tagName.toUpperCase();
    let drop = false;
    if (DROP_TAGS.has(tag)) drop = true;
    else if (tag === 'BUTTON' && !el.querySelector('code, pre, .selectable')
             && !el.matches('[title*="copy" i], [class*="copy-button"]') && textLen(el) < 40) drop = true;
    else if (PAGE_TAGS.has(tag) && !(tag === 'HEADER' && inArticle(el) && el.querySelector('h1,h2'))) drop = true;
    else if (DROP_ROLES.has((el.getAttribute('role') || '').toLowerCase())) drop = true;
    else if (hidden(el)) drop = true;
    else {
      const name = ((typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '')) + ' ' + (el.id || '')).trim();
      if (name && textLen(el) < 0.3 * rootLen && !el.querySelector('h1')) {
        const n = textLen(el);
        if (STRONG.test(name)) drop = true;
        else if (tag !== 'TABLE' && WEAK.test(name) && (n < 200 || linkLen(el) / Math.max(1, n) > 0.3)) drop = true;
      }
    }
    if (drop) { skip.add(el); for (const d of el.querySelectorAll('*')) skip.add(d); }
  }

  // 3. Markdown.
  const out = [];
  const esc = s => s.replace(/\s+/g, ' ');
  const BLOCKS = new Set(['P','DIV','SECTION','ARTICLE','MAIN','H1','H2','H3','H4','H5','H6','UL','OL','LI','TABLE','PRE','BLOCKQUOTE','DL','DT','DD','FIGURE','FIGCAPTION','HR','DETAILS','SUMMARY','HEADER','FOOTER','ADDRESS','CENTER','TR','TD','TH']);
  const isBlock = el => BLOCKS.has(el.tagName.toUpperCase());
  function href(a) {
    const h = a.getAttribute('href') || '';
    if (!h || h.startsWith('#') || h.startsWith('javascript:')) return '';
    try { return new URL(h, base).href; } catch (e) { return ''; }
  }
  function inline(nodes) {
    let s = '';
    for (const c of nodes) {
      if (c.nodeType === 3) { s += c.nodeValue.replace(/\s+/g, ' '); continue; }
      if (c.nodeType !== 1 || skip.has(c)) continue;
      const t = c.tagName.toUpperCase();
      if (t === 'BR') { s += '\n'; continue; }
      if (t === 'IMG') { const alt = (c.getAttribute('alt') || '').trim(); if (alt) s += alt; continue; }
      if (t === 'SUP' && /reference|cite/.test(typeof c.className === 'string' ? c.className : '')) continue;
      const inner = inline(c.childNodes);
      if (t === 'A' && c.querySelector('img') && !(c.textContent || '').trim()) { s += inner; continue; }
      if (t === 'A' && keepLinks) { const u = href(c); const txt = esc(inner).trim(); s += (u && txt) ? `[${txt}](${u})` : inner; continue; }
      if (t === 'CODE' && !(c.parentElement && c.parentElement.tagName === 'PRE')) { s += '`' + inner + '`'; continue; }
      if ((t === 'STRONG' || t === 'B' || t === 'EM' || t === 'I') && inner.trim()) {
        // The marks go around the text. The spaces at its ends stay outside them.
        const mark = (t === 'STRONG' || t === 'B') ? '**' : '_';
        s += inner.match(/^\s*/)[0] + mark + inner.trim() + mark + inner.match(/\s*$/)[0];
        continue;
      }
      if (isBlock(c)) { s += '\n' + inner + '\n'; continue; }
      s += inner;
    }
    return s;
  }
  function para(text) {
    const t = text.split('\n').map(x => esc(x).trim()).filter(Boolean).join('\n');
    if (t) out.push(t);
  }
  function layoutTable(el) {
    if (el.querySelector('table') || (el.getAttribute('role') || '') === 'presentation') return true;
    if (el.querySelectorAll('tr').length < 2) return true;
    for (const c of el.querySelectorAll('td')) if (textLen(c) > 400) return true;
    return false;
  }
  function table(el) {
    for (const child of el.children) {
      if (child.tagName.toUpperCase() === 'CAPTION') para(inline(child.childNodes));
    }
    const own = r => !skip.has(r) && r.closest('table') === el;
    if (layoutTable(el)) {
      for (const r of el.querySelectorAll('tr')) {
        if (!own(r)) continue;
        for (const c of r.children) if (!skip.has(c)) children(c);
      }
      return;
    }
    const rows = Array.from(el.querySelectorAll('tr')).filter(own);
    const grid = rows.map(r => Array.from(r.children).filter(c => /^(TD|TH)$/i.test(c.tagName))
      .map(c => esc(inline(c.childNodes)).trim().replace(/\|/g, '\\|')));
    const wide = Math.max(0, ...grid.map(r => r.length));
    if (wide < 2 || grid.length < 2) { for (const r of grid) para(r.join(' ')); return; }
    const lines = grid.map(r => '| ' + r.concat(Array(wide - r.length).fill('')).join(' | ') + ' |');
    lines.splice(1, 0, '|' + ' --- |'.repeat(wide));
    out.push(lines.join('\n'));
  }
  function list(el, depth) {
    let i = 1;
    const ordered = el.tagName.toUpperCase() === 'OL';
    const items = [];
    for (const li of el.children) {
      if (skip.has(li) || li.tagName.toUpperCase() !== 'LI') continue;
      const nested = Array.from(li.children).filter(c => /^(UL|OL)$/i.test(c.tagName) && !skip.has(c));
      for (const n of nested) skip.add(n);
      const t = esc(inline(li.childNodes)).trim();
      for (const n of nested) skip.delete(n);
      if (t) items.push('  '.repeat(depth) + (ordered ? `${i++}. ` : '- ') + t);
      for (const n of nested) {
        const before = out.length; list(n, depth + 1);
        const sub = out.splice(before); if (sub.length) items.push(sub.join('\n'));
      }
    }
    if (items.length) out.push(items.join('\n'));
  }
  function block(el) {
    if (skip.has(el)) return;
    const t = el.tagName.toUpperCase();
    if (/^H[1-6]$/.test(t)) { const s = esc(inline(el.childNodes)).trim(); if (s) out.push('#'.repeat(+t[1]) + ' ' + s); return; }
    if (t === 'P' || t === 'FIGCAPTION' || t === 'DT' || t === 'DD' || t === 'SUMMARY' || t === 'ADDRESS') { para(inline(el.childNodes)); return; }
    if (t === 'PRE') { out.push('```\n' + (el.textContent || '').replace(/\n+$/, '') + '\n```'); return; }
    if (t === 'UL' || t === 'OL') { list(el, 0); return; }
    if (t === 'TABLE') { table(el); return; }
    if (t === 'BLOCKQUOTE') {
      const before = out.length; children(el);
      const sub = out.splice(before);
      if (sub.length) out.push(sub.join('\n\n').split('\n').map(x => '> ' + x).join('\n'));
      return;
    }
    if (t === 'HR') return;
    children(el);
  }
  function children(el) {
    let run = '';
    for (const c of el.childNodes) {
      if (c.nodeType === 3) { run += c.nodeValue.replace(/\s+/g, ' '); continue; }
      if (c.nodeType !== 1 || skip.has(c)) continue;
      if (isBlock(c)) { para(run); run = ''; block(c); }
      else run += c.tagName.toUpperCase() === 'BR' ? '\n' : inline([c]);
    }
    para(run);
  }
  if (root.tagName.toUpperCase() !== 'BODY' && !root.querySelector('h1')) {
    const h1 = doc.querySelector('h1');
    if (h1 && !skip.has(h1)) out.push('# ' + esc(h1.textContent || '').trim());
  }
  block(root);
  return out.join('\n\n');
}
"""


def extract_script(links: bool = True) -> str:
    """The extraction function for `browser_evaluate`. It returns the JSON string
    `{title, url, text}`, where `text` is the Markdown of the page."""
    return f"""async () => {{
  {WALKER_JS}
  const body = document.body;
  const visible = () => ((body && body.innerText) || '').length;
  const loading = () => document.readyState !== 'complete'
    || !!document.querySelector('[aria-busy="true"]');
  if (body && (visible() < {SHORT_PAGE_CHARS} || loading())) {{
    await new Promise(resolve => {{
      let quiet = null, cap = null, observer = null;
      const done = () => {{
        clearTimeout(quiet); clearTimeout(cap);
        if (observer) observer.disconnect();
        resolve();
      }};
      observer = new MutationObserver(() => {{
        clearTimeout(quiet); quiet = setTimeout(done, {QUIET_MS});
      }});
      observer.observe(document.documentElement,
                       {{childList: true, subtree: true, characterData: true}});
      quiet = setTimeout(done, {QUIET_MS});
      cap = setTimeout(done, {QUIET_MAX_MS});
    }});
  }}
  const type = document.contentType || '';
  let text;
  if (!body) text = (document.documentElement && document.documentElement.textContent) || '';
  else if (type && !/html/i.test(type)) text = body.innerText || '';
  else text = walk(document, {{links: {'true' if links else 'false'}}});
  return JSON.stringify({{title: document.title || '', url: location.href, text,
    status: Number(performance.getEntriesByType('navigation')?.[0]?.responseStatus) || 0}});
}}"""
