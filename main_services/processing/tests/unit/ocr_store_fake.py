"""An in-memory collection database for the OCR target tests.

`FakeOcrStore.query` answers each query of `tasks/ocr_targets.py` and
`tasks/P_admin/ocr_rerun.py` by its table and its shape, with the semantics of the real
query: `FINAL` keeps the row with the largest version of a key, and `argMax` takes the
value of the largest version. It records every query with its parameters, so a test can
check the chunk size. `insert_arrow` and `command` keep the writes of the real writers.
"""

import itertools
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

CD = "c_ds"
COLLECTION = "c"


class FakeOcrStore:
    def __init__(self):
        self.file_types = []    # (cd, hash, extracted_by, mimes, encodings, coarse, extensions)
        self.raw = []           # (cd, hash, engine, languages, raw_json)
        self.pdf_results = []   # (cd, hash, engine, languages, updated_at, is_deleted)
        self.skips = []         # (cd, hash, stage, engine, languages)
        self.errors = []        # (cd, hash, task, write_version, timestamp_seconds)
        self.text = []          # (cd, hash, extracted_by, page_id, text, version)
        self.index_state = []   # (cd, hash)
        self.receipts = []      # (cd, hash, extracted_by, page_id, text_version, receipt_version)
        self.pdfs = []          # (cd, hash)
        self.plan_hits = []     # (cd, item, plan)
        self.targets = []       # dicts, `seq` orders writes like updated_at
        self.queries = []
        self.inserts = []
        self._seq = itertools.count(1)

    # ---- helpers for tests -----------------------------------------------------------

    def add_image(self, file_hash, plan="p1", mime="image/png"):
        self.plan_hits.append((CD, file_hash, plan))
        for detector in ("file", "magika", "extension", "content_sniff"):
            self.file_types.append((CD, file_hash, detector, [mime], [], ["image"], []))

    def add_pdf(self, file_hash, plan="p1", pdfs_row=True):
        self.plan_hits.append((CD, file_hash, plan))
        for detector in ("file", "magika", "extension"):
            self.file_types.append((CD, file_hash, detector, ["application/pdf"], [], ["pdf"], []))
        if pdfs_row:
            self.pdfs.append((CD, file_hash))

    def open_targets(self, op_id):
        return {key: row for key, row in self._final_targets(op_id).items() if not row["done"]}

    def _final_targets(self, op_id=None):
        latest = {}
        for row in self.targets:
            key = (row["op_id"], row["collection_dataset"], row["file_hash"], row["stage"],
                   row["engine"], row["languages"])
            if op_id is not None and row["op_id"] != op_id:
                continue
            if key not in latest or row["seq"] > latest[key]["seq"]:
                latest[key] = row
        return latest

    def current_text(self, file_hash):
        latest = {}
        for cd, h, eb, page, text, version in self.text:
            if cd == CD and h == file_hash:
                key = (eb, page)
                if key not in latest or version > latest[key][1]:
                    latest[key] = (text, version)
        return latest

    # ---- client ----------------------------------------------------------------------

    def query(self, sql, parameters=None):
        p = dict(parameters or {})
        self.queries.append((sql, p))
        rows = self._answer(" ".join(sql.split()), p)
        return SimpleNamespace(result_rows=rows)

    def _answer(self, sql, p):
        cd = p.get("cd") or p.get("ds")
        hashes = set(p["h"]) if "h" in p else None

        def chosen(h):
            return hashes is None or h in hashes

        if "FROM image_previews" in sql:
            return []
        if sql.startswith("SELECT count() FROM raw_ocr_results"):
            return [(sum(1 for r in self.raw if r[0] == cd and r[1] == p["ih"]
                         and r[2] == p["en"] and r[3] == p["la"]),)]
        if sql.startswith("SELECT count(), argMax(is_deleted, updated_at) FROM pdf_ocr_results"):
            rows = sorted((r for r in self.pdf_results if r[0] == cd and r[1] == p["ph"]
                           and r[2] == p["en"] and r[3] == p["la"]), key=lambda r: r[4])
            return [(len(rows), rows[-1][5] if rows else 0)]
        if "FROM blobs" in sql:
            return []
        if "FROM file_types FINAL" in sql and "extracted_by IN" in sql:
            final = {}
            for row in self.file_types:
                if row[0] == cd and chosen(row[1]) and row[2] in p["d"]:
                    final[row[1], row[2]] = row
            return [list(row[1:]) for row in final.values()]
        if sql.startswith("SELECT plan_hash, groupArray(item_hash) FROM processing_plan_hits"):
            typed = {row[1] for row in self.file_types
                     if row[0] == cd and {"image", "pdf"} & set(row[5])}
            plans = {}
            for row_cd, item, plan in self.plan_hits:
                if row_cd != cd or item not in typed:
                    continue
                if "ph" in p and plan != p["ph"]:
                    continue
                plans.setdefault(plan, []).append(item)
            return [(plan, items) for plan, items in sorted(plans.items())]
        if "FROM raw_ocr_results FINAL" in sql:
            final = {}
            for row in self.raw:
                if row[0] == cd and chosen(row[1]) and row[2] in p["e"]:
                    final[row[1], row[2], row[3]] = row
            return [list(row[1:]) for row in final.values()]
        if "FROM raw_ocr_results" in sql:
            return sorted({(r[1], r[2], r[3]) for r in self.raw if r[0] == cd and chosen(r[1])})
        if "FROM pdf_ocr_results" in sql:
            latest = {}
            for row in self.pdf_results:
                if row[0] == cd and chosen(row[1]):
                    key = (row[1], row[2], row[3])
                    if key not in latest or row[4] > latest[key][4]:
                        latest[key] = row
            return [key for key, row in latest.items() if not row[5]]
        if "FROM ocr_skips" in sql:
            return sorted({tuple(r[1:]) for r in self.skips if r[0] == cd and chosen(r[1])})
        if "FROM processing_errors" in sql:
            grouped = {}
            for row_cd, h, task, wv, ts in self.errors:
                if row_cd != cd or not chosen(h) or task not in p["t"]:
                    continue
                g = grouped.setdefault((h, task), [0, 0, 0])
                g[0] = max(g[0], wv)
                g[1] = max(g[1], wv // 1_000_000 if wv > 0 else ts)
                if wv == 0:
                    g[2] = max(g[2], ts)
            return [(h, task, *values) for (h, task), values in grouped.items()]
        if "argMax(text, version) FROM text_content" in sql:
            out = []
            for h in sorted(hashes):
                for (eb, page), (text, _) in self.current_text(h).items():
                    if eb in p["v"]:
                        out.append((h, eb, page, text))
            return out
        if "max(version) FROM text_content" in sql and "startsWith" in sql:
            out = []
            for h in sorted(hashes):
                for (eb, page), (_, version) in self.current_text(h).items():
                    if eb.startswith(p["p"]):
                        out.append((h, eb, page, version))
            return out
        if "SELECT DISTINCT file_hash FROM text_content" in sql:
            return sorted({(r[1],) for r in self.text
                           if r[0] == cd and chosen(r[1]) and r[2].startswith(p["p"])})
        if "SELECT page_id, max(version) FROM text_content" in sql:
            return [(page, version) for (eb, page), (_, version)
                    in self.current_text(p["fh"]).items() if eb == p["eb"]]
        if "FROM index_state" in sql:
            return sorted({(r[1],) for r in self.index_state if r[0] == cd and chosen(r[1])})
        if "FROM ocr_indexed_text" in sql:
            latest = {}
            for row in self.receipts:
                if row[0] == cd and chosen(row[1]):
                    key = (row[1], row[2], row[3])
                    if key not in latest or row[5] > latest[key][5]:
                        latest[key] = row
            return [(r[1], r[2], r[3], r[4]) for r in latest.values()]
        if "FROM pdfs" in sql:
            return sorted({(r[1],) for r in self.pdfs if r[0] == cd and chosen(r[1])})
        if "FROM ocr_run_targets FINAL" in sql:
            rows = [row for row in self._final_targets(p["op"]).values()
                    if row["collection_dataset"] == cd]
            if sql.startswith("SELECT count() AS targets_total"):
                return [(len(rows), sum(row["done"] for row in rows))]
            if sql.startswith("SELECT count(), countIf(done = 0)"):
                return [(len(rows), sum(1 for row in rows if not row["done"]))]
            if "ph" in p:
                rows = [row for row in rows if row["plan_hash"] == p["ph"]]
            if "h" in p:
                rows = [row for row in rows if row["file_hash"] in hashes]
            if "done = 0" in sql:
                rows = [row for row in rows if not row["done"]]
            if sql.startswith("SELECT plan_hash FROM ocr_run_targets"):
                plans = sorted({row["plan_hash"] for row in rows if row["plan_hash"] > p["after"]})
                return [(plan,) for plan in plans[:p["limit"]]]
            if sql.startswith("SELECT plan_hash, file_hash"):
                rows = sorted(rows, key=lambda r: (r["plan_hash"], r["file_hash"]))[:p["limit"]]
                return [(r["plan_hash"], r["file_hash"], r["stage"], r["engine"], r["languages"])
                        for r in rows]
            return [(r["file_hash"], r["stage"], r["engine"], r["languages"], r["since_us"],
                     r["since_is_precise"]) for r in rows]
        raise AssertionError(f"the fake store does not answer: {sql}")

    def insert_arrow(self, table, arrow_table, settings=None, **_):
        rows = arrow_table.to_pylist()
        self.inserts.append((table, rows, settings))
        if table == "text_content":
            for row in rows:
                self.text.append((row["collection_dataset"], row["file_hash"], row["extracted_by"],
                                  row["page_id"], row["text"], row["version"]))
        elif table == "ocr_run_targets":
            for row in rows:
                since = row["since"].replace(tzinfo=None)
                since_us = (since - datetime(1970, 1, 1)) // timedelta(microseconds=1)
                self.targets.append({**row, "since_us": since_us, "seq": next(self._seq)})
        elif table == "ocr_skips":
            for row in rows:
                self.skips.append((row["collection_dataset"], row["file_hash"], row["stage"],
                                   row["engine"], row["languages"]))
        elif table == "raw_ocr_results":
            for row in rows:
                self.raw.append((row["collection_dataset"], row["image_hash"], row["engine"],
                                 row["languages"], row["raw_json"]))
        else:
            raise AssertionError(f"unexpected insert into {table}")

    def command(self, sql, parameters=None):
        p = dict(parameters or {})
        self.queries.append((sql, p))
        if sql.startswith("DELETE FROM text_content"):
            ids = set(p["ids"])
            self.text = [r for r in self.text if not (
                r[0] == p["cd"] and r[1] == p["fh"] and r[2] == p["eb"] and r[3] in ids)]
            return
        raise AssertionError(f"unexpected command: {sql}")

    @contextmanager
    def client(self, *_args, **_kwargs):
        yield self
