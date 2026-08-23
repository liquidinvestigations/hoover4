"""MHTML -> one self-contained HTML file.

Chromium's `Page.captureSnapshot` returns MHTML: `multipart/related`, the page plus every
subresource it loaded. That is a faithful archive and an unusable one, no browser will
render it from an `<iframe src>`. This module inlines it into a single HTML document with
`data:` URIs, which *does* render, and which the website serves under a CSP that forbids
every network fetch.

`email.parser` reads `multipart/related` with no new dependency, which is the whole reason
this is pure Python rather than a service.

## What is stripped, and why it is stripped here as well as in the CSP

Every `<script>`, every `on*` attribute, `<base>`, and any `javascript:` or
`data:text/html` href. The CSP (`default-src 'none'`) and the `sandbox=""` iframe already
prevent execution. This is defence in depth against a viewer that gets the headers wrong,
and it removes bytes nobody needs. A capture is an archive; it does not need to run.

Remaining absolute links get `rel="noopener noreferrer nofollow" target="_blank"`. The CSP
forbids navigation inside the frame anyway, but a dead link that looks live is worse than
one that is marked.

## The relative-reference trap

Subresource references resolve against **the part's own `Content-Location`**, not the
document's. A stylesheet at `https://cdn.example/css/app.css` containing
`url(../img/x.png)` means `https://cdn.example/img/x.png`, which is nowhere near the page
URL. Getting this wrong produces a capture that renders with missing images and no error
anywhere.
"""

from __future__ import annotations

import base64
import email
import email.policy
import logging
import quopri
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

#: Anything bigger is refused before parsing. The caller writes the artifact row with
#: `status='too_large'` and keeps the thumbnail.
DEFAULT_MAX_BYTES = 8 * 1024 * 1024


class SnapshotTooLarge(ValueError):
    """The MHTML exceeded the byte cap and was not converted."""


@dataclass
class Part:
    location: str
    content_type: str
    payload: bytes
    is_html: bool = False

    def data_uri(self) -> str:
        encoded = base64.b64encode(self.payload).decode("ascii")
        return f"data:{self.content_type};base64,{encoded}"


@dataclass
class Converted:
    html: str
    root_url: str
    #: Parts that were inlined, for the log. A capture with two of forty resources
    #: inlined is a broken capture that still renders.
    inlined: int = 0
    total_parts: int = 0
    dropped_scripts: int = 0
    unresolved: list[str] = field(default_factory=list)


def convert(
    mhtml: bytes,
    captured_at: str = "",
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Converted:
    """Inline an MHTML archive into one HTML document."""
    if len(mhtml) > max_bytes:
        raise SnapshotTooLarge(
            f"snapshot is {len(mhtml)} bytes, over the {max_bytes} byte cap"
        )

    message = email.message_from_bytes(mhtml, policy=email.policy.default)
    declared_root = (message.get("Content-Location") or "").strip()

    parts: list[Part] = []
    for sub in message.walk():
        if sub.is_multipart():
            continue
        content_type = (sub.get_content_type() or "application/octet-stream").lower()
        location = (sub.get("Content-Location") or "").strip()
        payload = _decode(sub)
        parts.append(
            Part(
                location=location,
                content_type=content_type,
                payload=payload,
                is_html=content_type == "text/html",
            )
        )

    root = _pick_root(parts, declared_root)
    if root is None:
        raise ValueError("MHTML contains no text/html part")

    # Everything that is not the root document, keyed by its absolute location.
    resources = {
        p.location: p for p in parts if p is not root and p.location
    }

    html = root.payload.decode(_charset(root), "replace")
    result = Converted(
        html="",
        root_url=root.location or declared_root,
        total_parts=len(parts),
    )

    html, result.dropped_scripts = _strip_scripts_and_handlers(html)
    html = _inline_references(html, resources, root.location or declared_root, result)
    html = _neutralise_links(html)
    html = _prepend_banner(html, result.root_url, captured_at)

    result.html = html
    log.info(
        "mhtml converted: %d/%d parts inlined, %d scripts dropped, %d unresolved",
        result.inlined, result.total_parts, result.dropped_scripts, len(result.unresolved),
    )
    return result


# ----------------------------------------------------------------------- parsing

def _decode(part) -> bytes:
    """Decode one part's payload, honouring its transfer encoding.

    `get_payload(decode=True)` handles base64 and quoted-printable, but returns `None` for
    a part with no recognised encoding. Falling through to the raw string is what keeps a
    plain 7-bit stylesheet from vanishing.
    """
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001 - a malformed part must not lose the whole capture
        payload = None
    if payload is not None:
        return payload
    raw = part.get_payload()
    if isinstance(raw, bytes):
        return raw
    text = str(raw or "")
    encoding = (part.get("Content-Transfer-Encoding") or "").lower()
    if encoding == "quoted-printable":
        return quopri.decodestring(text.encode("utf-8", "replace"))
    if encoding == "base64":
        try:
            return base64.b64decode(text)
        except Exception:  # noqa: BLE001
            return text.encode("utf-8", "replace")
    return text.encode("utf-8", "replace")


def _charset(part: Part) -> str:
    match = re.search(r"charset=([\w-]+)", part.content_type)
    return match.group(1) if match else "utf-8"


def _pick_root(parts: list[Part], declared_root: str) -> Part | None:
    """The document part: the one whose `Content-Location` matches the message's, else the
    first `text/html` part."""
    if declared_root:
        for part in parts:
            if part.is_html and part.location == declared_root:
                return part
    for part in parts:
        if part.is_html:
            return part
    return None


# --------------------------------------------------------------------- rewriting

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_SCRIPT_SELF_CLOSING_RE = re.compile(r"<script\b[^>]*/?>", re.IGNORECASE)
_BASE_RE = re.compile(r"<base\b[^>]*>", re.IGNORECASE)
_NOSCRIPT_OPEN_RE = re.compile(r"</?noscript\s*>", re.IGNORECASE)
_ON_ATTR_RE = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)


def _strip_scripts_and_handlers(html: str) -> tuple[str, int]:
    """Remove every script, inline handler and `<base>`. See the module docstring."""
    html, script_count = _SCRIPT_RE.subn("", html)
    html, extra = _SCRIPT_SELF_CLOSING_RE.subn("", html)
    html = _BASE_RE.sub("", html)
    # `<noscript>` content is what a scriptless viewer should see, so the tags go and the
    # content stays.
    html = _NOSCRIPT_OPEN_RE.sub("", html)
    html = _ON_ATTR_RE.sub("", html)
    return html, script_count + extra


_URL_ATTR_RE = re.compile(
    r"""(?P<attr>\b(?:src|poster|href|data-src)\s*=\s*)(?P<q>["'])(?P<url>[^"']*)(?P=q)""",
    re.IGNORECASE,
)
_SRCSET_RE = re.compile(
    r"""(?P<attr>\bsrcset\s*=\s*)(?P<q>["'])(?P<val>[^"']*)(?P=q)""", re.IGNORECASE
)
_CSS_URL_RE = re.compile(r"""url\(\s*(?P<q>["']?)(?P<url>[^)"']+)(?P=q)\s*\)""", re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(
    r"""(?P<attr>\bstyle\s*=\s*)(?P<q>["'])(?P<val>[^"']*)(?P=q)""", re.IGNORECASE
)
_STYLESHEET_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)


def _inline_references(
    html: str, resources: dict[str, Part], base_url: str, result: Converted
) -> str:
    """Replace every subresource reference with the part's `data:` URI."""

    def lookup(raw: str, relative_to: str) -> Part | None:
        candidate = (raw or "").strip()
        if not candidate or candidate.startswith(("data:", "about:", "#", "javascript:")):
            return None
        part = resources.get(candidate)
        if part is not None:
            return part
        # Resolve against the part's own location, not the document's. See the module
        # docstring. `relative_to` is the caller's context, which for CSS is the
        # stylesheet's own URL.
        absolute = urljoin(relative_to or base_url, candidate)
        return resources.get(absolute)

    def inline_css(css: str, relative_to: str) -> str:
        def repl(match):
            part = lookup(match.group("url"), relative_to)
            if part is None:
                if match.group("url") and not match.group("url").startswith("data:"):
                    result.unresolved.append(match.group("url"))
                return match.group(0)
            result.inlined += 1
            return f'url("{part.data_uri()}")'

        return _CSS_URL_RE.sub(repl, css)

    # 1. <link rel=stylesheet> -> an inline <style> holding the stylesheet, itself
    #    inlined against its own URL.
    def replace_link(match):
        tag = match.group(0)
        if "stylesheet" not in tag.lower():
            # Icons and preloads: rewrite the href to a data: URI if we have the bytes,
            # drop the reference otherwise so nothing tries to leave the sandbox.
            attr = _URL_ATTR_RE.search(tag)
            if attr is None:
                return tag
            part = lookup(attr.group("url"), base_url)
            if part is None:
                return ""
            result.inlined += 1
            return tag.replace(attr.group("url"), part.data_uri())
        attr = _URL_ATTR_RE.search(tag)
        if attr is None:
            return ""
        part = lookup(attr.group("url"), base_url)
        if part is None:
            result.unresolved.append(attr.group("url"))
            return ""
        result.inlined += 1
        css = part.payload.decode(_charset(part), "replace")
        return f"<style>{inline_css(css, part.location or base_url)}</style>"

    html = _STYLESHEET_LINK_RE.sub(replace_link, html)

    # 2. <style> blocks and style="" attributes.
    html = _STYLE_BLOCK_RE.sub(
        lambda m: m.group(1) + inline_css(m.group(2), base_url) + m.group(3), html
    )
    html = _STYLE_ATTR_RE.sub(
        lambda m: f'{m.group("attr")}{m.group("q")}{inline_css(m.group("val"), base_url)}{m.group("q")}',
        html,
    )

    # 3. srcset, before the plain attributes. A srcset value contains commas and
    #    descriptors, so the single-URL rewriter would mangle it.
    def replace_srcset(match):
        entries = []
        for entry in match.group("val").split(","):
            entry = entry.strip()
            if not entry:
                continue
            bits = entry.split(None, 1)
            part = lookup(bits[0], base_url)
            if part is None:
                entries.append(entry)
                continue
            result.inlined += 1
            entries.append(part.data_uri() + (f" {bits[1]}" if len(bits) > 1 else ""))
        q = match.group("q")
        return f'{match.group("attr")}{q}{", ".join(entries)}{q}'

    html = _SRCSET_RE.sub(replace_srcset, html)

    # 4. src / poster / data-src. `href` on anchors is deliberately left alone here and
    #    handled by _neutralise_links: an <a href> is a link, not a subresource.
    def replace_attr(match):
        attr_name = match.group("attr").split("=")[0].strip().lower()
        if attr_name == "href":
            return match.group(0)
        part = lookup(match.group("url"), base_url)
        if part is None:
            return match.group(0)
        result.inlined += 1
        q = match.group("q")
        return f'{match.group("attr")}{q}{part.data_uri()}{q}'

    return _URL_ATTR_RE.sub(replace_attr, html)


_ANCHOR_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>", re.IGNORECASE)
_HREF_RE = re.compile(r"""\bhref\s*=\s*(["'])(?P<url>[^"']*)\1""", re.IGNORECASE)


def _neutralise_links(html: str) -> str:
    """Mark every remaining link as leaving the archive, and remove the dangerous ones."""

    def repl(match):
        attrs = match.group("attrs")
        href = _HREF_RE.search(attrs)
        if href is not None:
            target = href.group("url").strip().lower()
            if target.startswith(("javascript:", "data:text/html", "vbscript:")):
                attrs = _HREF_RE.sub("", attrs)
                return f"<a{attrs}>"
        attrs = re.sub(r"""\s(?:target|rel)\s*=\s*(["'])[^"']*\1""", "", attrs, flags=re.IGNORECASE)
        return f'<a{attrs} target="_blank" rel="noopener noreferrer nofollow">'

    return _ANCHOR_RE.sub(repl, html)


_BANNER_TEMPLATE = (
    '<div style="all:initial;display:block;font:13px/1.5 -apple-system,BlinkMacSystemFont,'
    "'Segoe UI',Roboto,sans-serif;background:#1E293B;color:#E2E8F0;padding:10px 14px;"
    'border-bottom:2px solid #475569;">'
    '<strong style="color:#F8FAFC;">Archived copy</strong> &mdash; links are not live. '
    '<span style="opacity:.85;">{url}</span>{when}'
    "</div>"
)


def _prepend_banner(html: str, url: str, captured_at: str) -> str:
    """Say what this is, at the top, in inline styles the page's own CSS cannot undo."""
    when = f' <span style="opacity:.7;">captured {_escape(captured_at)}</span>' if captured_at else ""
    banner = _BANNER_TEMPLATE.format(url=_escape(url), when=when)
    match = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    if match:
        return html[: match.end()] + banner + html[match.end() :]
    return banner + html


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def page_title(html: str) -> str:
    match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html, re.IGNORECASE | re.DOTALL)
    return " ".join(match.group(1).split())[:300] if match else ""


def same_origin(url: str, other: str) -> bool:
    """Whether two URLs share scheme+host+port. Used only for logging."""
    try:
        a, b = urlparse(url), urlparse(other)
    except ValueError:
        return False
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)
