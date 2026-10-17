"""Parse Markdown once for prose, destinations, headings, and diagrams."""
from dataclasses import dataclass, field
from html.parser import HTMLParser

from github_slugger import GithubSlugger
from markdown_it import MarkdownIt


@dataclass
class Destination:
    line: int
    url: str
    image: bool = False
    alt: str = ""
    attrs: dict = field(default_factory=dict)


class HTML(HTMLParser):
    def __init__(self, line):
        super().__init__(convert_charrefs=True)
        self.line = line
        self.links, self.ids, self.text = [], [], []
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        line = self.line + self.getpos()[0] - 1
        if "id" in attrs or (tag == "a" and "name" in attrs):
            self.ids.append(attrs.get("id") or attrs["name"])
        if tag == "a":
            self.hrefs.append(attrs.get("href", ""))
        if tag == "img":
            attrs["_href"] = self.hrefs[-1] if self.hrefs else ""
            self.links.append(Destination(line, attrs.get("src", ""), True, attrs.get("alt", ""), attrs))
        elif tag == "a" and "href" in attrs:
            self.links.append(Destination(line, attrs["href"]))

    def handle_endtag(self, tag):
        if tag == "a" and self.hrefs:
            self.hrefs.pop()

    def handle_data(self, text):
        self.text.append(text)


def mask_examples(source, allow_examples=False):
    """Keep source line numbers when excluding front matter and quoted rule examples."""
    lines = source.splitlines(keepends=True)
    front = bool(lines and lines[0].strip() == "---")
    examples = False
    for i, line in enumerate(lines):
        if front:
            lines[i] = "\n"
            if i and line.strip() in ("---", "..."):
                front = False
            continue
        if allow_examples and "<!-- prose-examples:start -->" in line:
            examples = True
        if examples:
            lines[i] = "\n"
        if "<!-- prose-examples:end -->" in line:
            examples = False
    return "".join(lines)


def inline_text(children, code=False):
    parts = []
    for token in children:
        if token.type in ("text", "softbreak", "hardbreak"):
            parts.append(token.content if token.type == "text" else " ")
        elif token.type == "code_inline":
            parts.append(token.content if code else " \x00 ")
        elif token.type == "image":
            parts.append(token.content)
    return "".join(parts)


def parse(source, allow_examples=False):
    parser = MarkdownIt("commonmark").enable("table")
    tokens = parser.parse(mask_examples(source, allow_examples))
    slugger = GithubSlugger()
    result = dict(headings=[], anchors=set(), links=[], prose=[], paths=[], diagrams=[], blocks=[])
    if allow_examples and source.count("<!-- prose-examples:start -->") != source.count("<!-- prose-examples:end -->"):
        result["unclosed_examples"] = True
    quote_depth, heading, seen_ids = 0, None, set()
    for token in tokens:
        if token.type == "blockquote_open":
            quote_depth += 1
        if token.type == "blockquote_close":
            quote_depth -= 1
        if quote_depth:
            continue
        line = (token.map or [0])[0] + 1
        if token.type == "heading_open":
            heading = int(token.tag[1:])
        elif token.type == "heading_close":
            heading = None
        elif token.type == "inline":
            children = token.children or []
            prose = inline_text(children)
            result["prose"].append((line, prose, bool(heading)))
            if heading:
                title = inline_text(children, code=True)
                slug = slugger.slug(title)
                result["headings"].append((line, heading, title, slug))
                result["anchors"].add(slug)
            link_depth = 0
            html = HTML(line)
            child_line = line
            for child in children:
                if child.type == "link_open":
                    link_depth += 1
                    result["links"].append(Destination(child_line, child.attrGet("href") or ""))
                elif child.type == "link_close":
                    link_depth -= 1
                elif child.type == "image":
                    result["links"].append(Destination(child_line, child.attrGet("src") or "", True, child.content))
                elif child.type == "html_inline":
                    html.feed(child.content)
                elif child.type in ("text", "code_inline") and not link_depth:
                    result["paths"].append((child_line, child.content))
                child_line += child.content.count("\n") + (child.type in ("softbreak", "hardbreak"))
            result["links"].extend(html.links)
            for anchor in html.ids:
                if anchor in seen_ids:
                    result.setdefault("duplicate_ids", []).append((line, anchor))
                seen_ids.add(anchor)
            result["anchors"].update(html.ids)
        elif token.type == "html_block":
            html = HTML(line)
            html.feed(token.content)
            result["links"].extend(html.links)
            for anchor in html.ids:
                if anchor in seen_ids:
                    result.setdefault("duplicate_ids", []).append((line, anchor))
                seen_ids.add(anchor)
            result["anchors"].update(html.ids)
            result["prose"].append((line, " ".join(html.text), False))
        elif token.type == "fence":
            language = token.info.strip().lower()
            result["blocks"].append((line, language, token.content))
            if language == "mermaid":
                result["diagrams"].append((line, token.content))
    return result
