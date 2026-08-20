#!/usr/bin/env python3
"""Micro-benchmarks for the per-activity overhead floor.

Run inside hoover4-worker (processing is /app; this file is not on that mount):

    docker exec -i hoover4-worker uv run python - < main_services/bench-overhead.py

Each probe prints p50/mean/min/max over >=15 iterations. Controls (fresh
``get_client`` + close, SELECT 1, Magika construction, one-shot extractous
subprocess, in-process extractous, ``file``) stay so a later measurement can
tell whether the machine moved. Live-path probes use the pooled client, the
idempotent insert helper, the process-wide Magika detector, and the extractous
helper pool.
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
        get_global_client,
        insert_arrow_idempotent,
        insert_idempotent,
        reset_client_pool_for_tests,
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

    def probe_fresh_get_client_close():
        c = get_client()
        c.close()

    print(
        "fresh clickhouse_connect.get_client() + close():",
        _stats(_time(probe_fresh_get_client_close)),
    )

    reset_client_pool_for_tests()

    def probe_pooled_client():
        with get_global_client() as client:
            client  # kept for the process; enter/exit is the live path

    print("pooled get_global_client() enter/exit:", _stats(_time(probe_pooled_client)))

    with get_global_client() as warm:
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

        print(
            "1-row insert async_insert=1 wait_for_async_insert=1 (fresh client):",
            _stats(_time(probe_insert_async)),
        )

        def probe_insert_sync():
            c = get_client(settings={"async_insert": 0, "wait_for_async_insert": 0})
            try:
                c.insert("bench_overhead_probe", [[1]], column_names=["x"])
            finally:
                c.close()

        print(
            "1-row insert no async settings (fresh client):",
            _stats(_time(probe_insert_sync)),
        )

        def probe_insert_idempotent():
            insert_idempotent(warm, "bench_overhead_probe", [[1]], column_names=["x"])

        print(
            "1-row insert_idempotent (pooled, no async wait):",
            _stats(_time(probe_insert_idempotent)),
        )

        import pyarrow as pa

        def probe_store_shaped_insert():
            tbl = pa.table({"x": pa.array([1], type=pa.uint8())})
            insert_arrow_idempotent(warm, "bench_overhead_probe", tbl)

        print(
            "_store_file_types shaped (pooled + insert_arrow_idempotent):",
            _stats(_time(probe_store_shaped_insert)),
        )

        from tasks.P3_parse_files.parse_mime import mime_types_from_name

        def probe_detect_mime_body():
            mime_types_from_name(probe)
            tbl = pa.table({"x": pa.array([1], type=pa.uint8())})
            insert_arrow_idempotent(warm, "bench_overhead_probe", tbl)

        print(
            "detect_mime_from_name body (name + idempotent insert):",
            _stats(_time(probe_detect_mime_body)),
        )

        from magika import Magika
        from tasks.P3_parse_files.parse_mime import (
            identify_path_with_magika,
            reset_magika_for_tests,
        )

        def probe_magika_ctor():
            Magika()

        print("Magika() construction (control):", _stats(_time(probe_magika_ctor)))

        reset_magika_for_tests()
        t0 = time.perf_counter()
        identify_path_with_magika(probe)
        first_ms = (time.perf_counter() - t0) * 1000
        print(f"Magika identify_path first call (construct + identify): p50={first_ms:.3f}ms  n=1")

        def probe_magika_warm():
            identify_path_with_magika(probe)

        print("Magika.identify_path() warm (module detector):", _stats(_time(probe_magika_warm)))

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

        print(
            "extractous via one-shot subprocess (control):",
            _stats(_time(probe_extractous_sub)),
        )

        from tasks.P3_parse_files.parse_tika import (
            _extract_with_extractous,
            reset_extractous_pool_for_tests,
        )

        reset_extractous_pool_for_tests()
        t0 = time.perf_counter()
        _extract_with_extractous(probe)
        first_ext_ms = (time.perf_counter() - t0) * 1000
        print(f"extractous helper pool first call (spawn + extract): p50={first_ext_ms:.3f}ms  n=1")

        def probe_extractous_pool():
            _extract_with_extractous(probe)

        print("extractous via helper pool (warm):", _stats(_time(probe_extractous_pool)))
        reset_extractous_pool_for_tests()

        from extractous import Extractor, TesseractOcrConfig

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
