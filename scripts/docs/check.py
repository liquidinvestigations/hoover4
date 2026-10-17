#!/usr/bin/env python3
"""Check tracked documentation and report defects with source locations."""
import argparse
import configparser
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
from urllib.parse import unquote, urlsplit

from markdown import parse

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prose", ROOT / ".agents/check-prose-style.py")
prose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prose)
CITATION = re.compile(r"(?:contentReference\[|oaicite:|\ue200cite\ue202|\bturn\d+(?:search|view|fetch)\d+\b)")
BARE_PATH = re.compile(r"(?<![\w:/])(?:\.{1,2}/)?[\w./-]+\.md(?:#[\w-]+)?\b", re.I)
SOURCE_PATH = re.compile(r"(?<![\w:/])(?:\.{1,2}/)?[\w.-]+(?:/[\w.-]+)+\.(?:py|rs|sh|ini|toml|sql|json|yaml|yml)\b")
REVIEW = re.compile(
    r"\b(?:simply|obviously|clearly|easily|please|just|of course|as you can see|"
    r"in order to|it is important|keep in mind|remember that|under the hood|"
    r"at a glance|key takeaways?|why (?:this|it) matters|things to know|"
    r"the bottom line|in summary|in conclusion)\b", re.I)


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def markdown_path(path, templates=False):
    return path.lower().endswith(".md") or (templates and path.lower().endswith(".md.j2"))


def png_size(path):
    with path.open("rb") as stream:
        data = stream.read(24)
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("The file is not a PNG image.")
    return struct.unpack(">II", data[16:24])


class Audit:
    def __init__(self, root, tracked, ownership=None):
        self.root = root.resolve()
        self.tracked = set(tracked)
        self.ownership = ownership or {}
        self.parsed, self.findings, self.graph, self.images = {}, [], {}, set()
        self.external = set()
        records = load_json(self.root / "docs/screenshot-provenance.json", {}).get("screenshots", [])
        self.screenshot_paths = {row["image"] for row in records}
        self.config = configparser.ConfigParser(interpolation=None, strict=False)
        self.config.read([self.root / "hoover4.ini.development", self.root / "hoover4.ini.release"])

    def add(self, path, line, rule, message, severity="error"):
        self.findings.append(dict(path=str(path), line=line, rule=rule, severity=severity, message=message))

    def document(self, path):
        if path not in self.parsed:
            self.parsed[path] = parse((self.root / path).read_text(encoding="utf-8"), path in ("AGENTS.md", "GEMINI.md", "docs/development/Documentation_Standards.md"))
        return self.parsed[path]

    def target(self, path, destination):
        parts = urlsplit(destination)
        if parts.scheme or parts.netloc:
            if parts.scheme in ("http", "https"):
                self.external.add(destination.split("#")[0])
            return None
        raw = unquote(parts.path)
        local = self.root / raw.lstrip("/") if raw.startswith("/") else self.root / Path(path).parent / raw
        if not raw:
            local = self.root / path
        # Resolve symlinks to prevent links to files outside the checkout.
        resolved = local.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            return ("", unquote(parts.fragment))
        lexical = Path(os.path.normpath(local)).relative_to(self.root).as_posix()
        return lexical, unquote(parts.fragment)

    def link(self, path, line, url):
        target = self.target(path, url)
        if target is None:
            return None
        dest, anchor = target
        if not dest:
            self.add(path, line, "link-outside", "The destination leaves the repository.")
            return None
        absolute = self.root / dest
        if not absolute.exists():
            self.add(path, line, "link-missing", f"The destination does not exist with this case: {dest}")
            return dest
        is_tracked = dest in self.tracked or (absolute.is_dir() and (dest == "." or any(p.startswith(dest.rstrip("/") + "/") for p in self.tracked)))
        if not is_tracked:
            self.add(path, line, "link-untracked", f"The destination is not tracked: {dest}")
        if absolute.is_dir() and anchor:
            indexes = sorted(p for p in self.tracked if Path(p).parent == Path(dest) and Path(p).name.lower() == "readme.md")
            if indexes:
                dest = indexes[0]
                absolute = self.root / dest
            else:
                self.add(path, line, "link-anchor", f"The directory has no tracked README for its fragment: {url}")
        if markdown_path(dest) and absolute.is_file():
            self.graph.setdefault(path, set()).add(dest)
            if anchor and anchor not in self.document(dest)["anchors"]:
                self.add(path, line, "link-anchor", f"The section does not exist: {url}")
        return dest

    def scan(self, paths):
        for path in paths:
            if path in self.ownership:
                continue
            doc = self.document(path)
            if doc.get("unclosed_examples"):
                self.add(path, 1, "prose-examples", "Pair the start and end markers for rule examples.")
            headings = doc["headings"]
            if not headings or headings[0][1] != 1:
                self.add(path, 1, "heading-title", "Start the document with a level-one heading.")
            previous = 0
            for line, level, title, _ in headings:
                if previous and level > previous + 1:
                    self.add(path, line, "heading-level", "The heading skips a level.")
                previous = level
                if len(title.split()) > 12 or re.search(r"[?!]|(?:\bnot\b.*\bbut\b)", title, re.I):
                    self.add(path, line, "heading-review", "Review the heading for a direct subject or instruction.", "warning")
            for line, anchor in doc.get("duplicate_ids", []):
                self.add(path, line, "heading-id", f"The explicit HTML ID is repeated: {anchor}")
            for line, text, heading in doc["prose"]:
                for _, _, _, term, _ in prose.phrase_errors(path, line, text, False):
                    self.add(path, line, "prose", f"Remove the prohibited wording: {term}")
                if CITATION.search(text):
                    self.add(path, line, "citation-token", "Replace the tool citation token with a public source link.")
                for match in REVIEW.finditer(text):
                    self.add(path, line, "heading-review" if heading else "prose-review", f"Review wording in context: {match.group()}", "warning")
            for line, language, code in doc["blocks"]:
                if language == "ini" and self.config.sections():
                    sample = configparser.ConfigParser(interpolation=None, strict=False)
                    try:
                        sample.read_string(code)
                        for section in sample.sections():
                            for key in sample[section]:
                                if not self.config.has_option(section, key):
                                    self.add(path, line, "config-review", f"Verify the configuration key against its parser: [{section}] {key}", "warning")
                    except configparser.Error:
                        self.add(path, line, "config-review", "The INI example is partial or invalid. Verify its parser and scope.", "warning")
            for line, text in doc["paths"]:
                for match in SOURCE_PATH.finditer(text):
                    candidate = match.group()
                    roots = [Path(path).parent, *Path(path).parents, Path(".")]
                    if not any(self.target((base / "_").as_posix(), candidate)[0] in self.tracked for base in roots):
                        self.add(path, line, "source-reference", f"Verify this source path and its directory context: {candidate}", "warning")
                for match in BARE_PATH.finditer(text):
                    candidate = match.group()
                    target = self.target(path, candidate)
                    root_target = candidate.split("#")[0]
                    if target and (target[0] in self.tracked or root_target in self.tracked):
                        self.add(path, line, "unlinked-path", f"Link this documentation path: {candidate}", "warning")
            for link in doc["links"]:
                dest = self.link(path, link.line, link.url)
                if link.image:
                    if not link.alt.strip():
                        self.add(path, link.line, "image-alt", "Describe the image in alternative text.")
                    if dest:
                        self.images.add(dest)
                        if dest.startswith("docs/user-manual/img/") or dest in self.screenshot_paths:
                            self.screenshot(path, link, dest)
            for line, code in doc["diagrams"]:
                if "accTitle:" not in code or "accDescr" not in code:
                    self.add(path, line, "diagram-description", "Add an accessible title and description where the diagram format supports them.", "warning")
        return self.findings

    def screenshot(self, path, link, dest):
        image = self.root / dest
        if image.exists():
            try:
                size = png_size(image)
                if size != (1400, 900):
                    self.add(path, link.line, "screenshot-size", f"Recapture at 1400 by 900 pixels: {dest} ({size[0]} by {size[1]})")
            except (OSError, ValueError) as error:
                self.add(path, link.line, "screenshot-file", str(error))
        if link.attrs.get("align") or link.attrs.get("width") != "100%":
            self.add(path, link.line, "screenshot-layout", "Use an HTML image with width=100% and no alignment attribute.")
        if link.attrs.get("_href") != link.url:
            self.add(path, link.line, "screenshot-full-size", "Link the image to its full-size file.")

    def reachability(self, paths):
        roots = {p for p in paths if Path(p).name.lower() == "readme.md" or p == "AGENTS.md" or p.endswith("/SKILL.md")}
        seen, todo = set(), list(roots)
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            todo.extend(self.graph.get(path, set()) - seen)
        for image in sorted(self.tracked - self.images):
            if image.startswith("docs/user-manual/img/") and image.lower().endswith(".png"):
                self.add(image, 1, "image-unreferenced", "No scanned documentation page references this manual image.", "warning")
        for path in sorted(set(paths) - seen - set(self.ownership)):
            self.add(path, 1, "index-reachability", "No README or skill index reaches this page through parsed links.", "warning")

    def feature_ids(self):
        if hasattr(self, "_feature_ids"):
            return self._feature_ids
        feature_file = "docs/technical-specification/Features.md"
        source = self.root / feature_file
        ids = re.findall(r"^\|\s*`(F-[\w-]+)`", source.read_text(), re.M) if source.exists() else []
        self._feature_ids = ids
        for identity, count in Counter(ids).items():
            if count > 1:
                self.add(feature_file, 1, "feature-duplicate", f"The feature ID occurs {count} times: {identity}")
        return ids

    def coverage(self, filename):
        data = load_json(self.root / filename, None)
        if data is None:
            self.add(filename, 1, "coverage-missing", "Create the feature and route coverage manifest.")
            return
        ids = self.feature_ids()
        entries = data.get("features", [])
        counts = Counter(entry.get("id") for entry in entries)
        for identity in sorted(set(ids) | set(counts)):
            if identity not in ids or counts[identity] != 1:
                self.add(filename, 1, "feature-coverage", f"Each registered feature needs one coverage entry: {identity}")
        for entry in entries:
            for field in ("source", "docs"):
                if not entry.get(field):
                    self.add(filename, 1, "coverage-field", f"Feature {entry.get('id')} needs {field}.")
                for target in entry.get(field, []):
                    self.link(filename, 1, "/" + target)
            if entry.get("audience") not in ("user", "admin", "operator", "developer"):
                self.add(filename, 1, "coverage-audience", f"Feature {entry.get('id')} needs an audience.")
            if entry.get("screenshot"):
                self.link(filename, 1, "/" + entry["screenshot"])
                self.link(filename, 1, "/" + entry.get("scenario", "MISSING"))
            elif not entry.get("no_screenshot_reason"):
                self.add(filename, 1, "coverage-screenshot", f"Explain screenshot applicability for {entry.get('id')}.")
        route_file = self.root / "website/frontend/src/routes.rs"
        routes = set(re.findall(r'#\[route\("([^"]+)"\)\]', route_file.read_text()))
        documented = data.get("routes", {})
        for route in sorted(routes ^ set(documented)):
            self.add(filename, 1, "route-coverage", f"The route coverage differs from the route declaration: {route}")
        for destination in documented.values():
            self.link(filename, 1, "/" + destination)

    def provenance(self, filename):
        data = load_json(self.root / filename, None)
        if data is None:
            self.add(filename, 1, "screenshot-manifest", "Create the public screenshot provenance manifest.")
            return
        entries = data.get("screenshots", [])
        covered = set()
        for entry in entries:
            image = entry.get("image", "")
            if image in covered:
                self.add(filename, 1, "screenshot-duplicate", f"The image has repeated provenance: {image}")
            covered.add(image)
            target = self.root / image
            self.link(filename, 1, "/" + image)
            if target.is_file():
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if digest != entry.get("sha256"):
                    self.add(filename, 1, "screenshot-hash", f"The screenshot differs from its capture record: {image}")
            self.link(filename, 1, "/" + entry.get("scenario", "MISSING"))
            if not re.fullmatch(r"[0-9a-f]{40}", entry.get("revision", "")) or not entry.get("captured_at"):
                self.add(filename, 1, "screenshot-evidence", f"Record the capture revision and date: {image}")
            if set(entry) - {"image", "scenario", "revision", "captured_at", "sha256"}:
                self.add(filename, 1, "screenshot-fields", "Keep private run fields out of the public manifest.")
        for image in sorted(self.images):
            if image.startswith("docs/user-manual/img/") and image not in covered:
                self.add(filename, 1, "screenshot-coverage", f"The published screenshot has no provenance: {image}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--templates", action="store_true")
    parser.add_argument("--require-manifests", action="store_true")
    parser.add_argument("--coverage", default="docs/documentation-coverage.json")
    parser.add_argument("--screenshots", default="docs/screenshot-provenance.json")
    args = parser.parse_args()
    names = args.index.read_text().split("\0") if args.index else subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT, text=True).split("\0")
    tracked = {p for p in names if p}
    paths = sorted(p for p in tracked if markdown_path(p, args.templates))
    if args.paths:
        paths = [p for p in paths if any(p == a or p.startswith(a.rstrip("/") + "/") for a in args.paths)]
        for name in args.paths:
            if markdown_path(name, args.templates) and (ROOT / name).is_file() and name not in paths:
                paths.append(name)
    if args.paths and not paths:
        parser.error("No Markdown files match the selected paths.")
    ownership = load_json(ROOT / "scripts/docs/ownership.json", {})
    audit = Audit(ROOT, tracked, ownership)
    audit.scan(paths)
    if not args.paths:
        audit.reachability(paths)
        audit.feature_ids()
    elif "docs/technical-specification/Features.md" in paths:
        audit.feature_ids()
    for field, method in ((args.coverage, audit.coverage), (args.screenshots, audit.provenance)):
        if args.require_manifests or (ROOT / field).exists():
            method(field)
    errors = sum(f["severity"] == "error" for f in audit.findings)
    result = dict(files=len(paths), excluded={p: ownership[p] for p in paths if p in ownership}, errors=errors,
                  findings=audit.findings, external_links=sorted(audit.external),
                  headings=[dict(path=p, line=h[0], level=h[1], title=h[2], anchor=h[3])
                            for p in paths if p not in ownership for h in audit.document(p)["headings"]])
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for finding in audit.findings:
            print("{path}:{line}: {severity} [{rule}] {message}".format(**finding))
        print(f"Scanned {len(paths)} files. Found {errors} errors and {len(audit.findings) - errors} warnings.")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
