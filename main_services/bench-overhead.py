#!/usr/bin/env python3
"""Micro-benchmarks for the per-activity overhead floor.

Run inside hoover4-worker (processing is /app; this file is not on that mount):

    docker exec -i hoover4-worker uv run python - < main_services/bench-overhead.py

Each probe prints p50/mean/min/max over >=15 iterations. Controls (SELECT 1,
warm Magika.identify_path, in-process extractous, `file` subprocess) are here
so a later measurement can tell whether the machine moved. This script only
measures; it does not change Magika construction or the ClickHouse client.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

ITERATIONS = 15


def _pick_probe_file() -> str:
    for root in (
        Path("/testdata/enron-kaminski-v/inbox"),
        Path("/testdata"),
        Path("/etc"),
    ):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.stat().st_size > 32:
                return str(path)
    return "/etc/hosts"


def _stats(samples: list[float]) -> str:
    xs = sorted(samples)
    n = len(xs)
    p50 = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    return (
        f"p50={p50*1000:.3f}ms  mean={statistics.mean(xs)*1000:.3f}ms  "
        f"min={xs[0]*1000:.3f}ms  max={xs[-1]*1000:.3f}ms  n={n}"
    )


def _time(fn, n: int = ITERATIONS) -> list[float]:
    # One discarded warmup so construction/cache effects are not the first row.
    fn()
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t0)
    return out


def main() -> int:
    probe = _pick_probe_file()
    print(f"probe file: {probe}")

    import clickhouse_connect
    from database.clickhouse import (
        CLICKHOUSE_HOST,
        CLICKHOUSE_PASS,
        CLICKHOUSE_USER,
        CLIENT_SETTINGS,
        GLOBAL_DB,
    )

    def get_client(**extra):
        settings = dict(CLIENT_SETTINGS)
        settings.update(extra.pop("settings", {}))
        return clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASS,
            database=GLOBAL_DB,
            settings=settings,
            **extra,
        )

    def probe_get_client_close():
        c = get_client()
        c.close()

    print("clickhouse_connect.get_client() + close():", _stats(_time(probe_get_client_close)))

    warm = get_client()
    warm.query("SELECT 1")

    def probe_select_1():
        warm.query("SELECT 1")

    print("warm SELECT 1:", _stats(_time(probe_select_1)))

    warm.command(
        "CREATE TABLE IF NOT EXISTS Hoover4_Processing.bench_overhead_probe "
        "(x UInt8) ENGINE = Memory"
    )

    def probe_insert_async():
        c = get_client(settings={"async_insert": 1, "wait_for_async_insert": 1})
        try:
            c.insert("bench_overhead_probe", [[1]], column_names=["x"])
        finally:
            c.close()

    print("1-row insert async_insert=1 wait_for_async_insert=1:", _stats(_time(probe_insert_async)))

    def probe_insert_sync():
        c = get_client(settings={"async_insert": 0, "wait_for_async_insert": 0})
        try:
            c.insert("bench_overhead_probe", [[1]], column_names=["x"])
        finally:
            c.close()

    print("1-row insert no async settings:", _stats(_time(probe_insert_sync)))

    import pyarrow as pa
    from database.clickhouse import get_global_client

    def probe_store_shaped_insert():
        tbl = pa.table({"x": pa.array([1], type=pa.uint8())})
        with get_global_client() as client:
            client.insert_arrow("bench_overhead_probe", tbl)

    print("_store_file_types shaped (client + insert_arrow):", _stats(_time(probe_store_shaped_insert)))

    from tasks.P3_parse_files.parse_mime import mime_types_from_name

    def probe_detect_mime_body():
        mime_types_from_name(probe)
        tbl = pa.table({"x": pa.array([1], type=pa.uint8())})
        with get_global_client() as client:
            client.insert_arrow("bench_overhead_probe", tbl)

    print("detect_mime_from_name body (name + insert):", _stats(_time(probe_detect_mime_body)))

    from magika import Magika

    def probe_magika_ctor():
        Magika()

    print("Magika() construction:", _stats(_time(probe_magika_ctor)))

    magika = Magika()
    magika.identify_path(probe)

    def probe_magika_warm():
        magika.identify_path(probe)

    print("Magika.identify_path() warm:", _stats(_time(probe_magika_warm)))

    helper = (
        "import json, sys;"
        "from extractous import Extractor, TesseractOcrConfig;"
        "ex = Extractor().set_ocr_config(TesseractOcrConfig().set_language('eng'));"
        "text, meta = ex.extract_file_to_string(sys.argv[1]);"
        "sys.stdout.write(json.dumps({'n': len(text or '')}))"
    )

    def probe_extractous_sub():
        res = subprocess.run(
            [sys.executable, "-c", helper, probe],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        if res.returncode != 0:
            raise RuntimeError(res.stderr[-200:])

    print("extractous via subprocess helper:", _stats(_time(probe_extractous_sub)))

    from extractous import Extractor, TesseractOcrConfig

    ex = Extractor().set_ocr_config(TesseractOcrConfig().set_language("eng"))
    ex.extract_file_to_string(probe)

    def probe_extractous_inproc():
        Extractor().set_ocr_config(TesseractOcrConfig().set_language("eng")).extract_file_to_string(probe)

    print("extractous in-process:", _stats(_time(probe_extractous_inproc)))

    def probe_file():
        subprocess.run(["file", "--mime-type", probe], capture_output=True, check=False)

    print("file subprocess (one call):", _stats(_time(probe_file)))

    from tasks.P3_parse_files.parse_mime import _run_file_multi

    def probe_file_multi():
        _run_file_multi(probe)

    print("_run_file_multi (4 file calls):", _stats(_time(probe_file_multi)))

    warm.command("DROP TABLE IF EXISTS Hoover4_Processing.bench_overhead_probe")
    warm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
