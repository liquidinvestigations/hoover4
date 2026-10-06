"""Write bounded telemetry batches to ClickHouse once per minute."""

import atexit
import json
import logging
import threading

log = logging.getLogger(__name__)
FLUSH_SECONDS = 60
MAX_ROWS = 100_000
_lock = threading.Lock()
_rows = {}
_thread = None


def record(base, database, auth, table, row):
    """Collect one telemetry row without blocking the request."""
    global _thread
    with _lock:
        if _thread is None:
            _thread = threading.Thread(target=_run, name='clickhouse-telemetry', daemon=True)
            _thread.start()
            atexit.register(flush)
        bucket = _rows.setdefault((base, database, tuple(auth), table), [])
        if len(bucket) >= MAX_ROWS:
            bucket.pop(0)
            log.warning('ClickHouse telemetry buffer full, dropped one %s row', table)
        bucket.append(row)


def _run():
    timer = threading.Event()
    while not timer.wait(FLUSH_SECONDS):
        flush()


def flush():
    """Wait for storage of each telemetry batch and report failed row counts."""
    import httpx

    global _rows
    with _lock:
        pending, _rows = _rows, {}
    for (base, database, auth, table), rows in pending.items():
        try:
            with httpx.Client(timeout=10.0, auth=auth) as client:
                response = client.post(
                    f'{base}/',
                    params={'database': database, 'async_insert': 1, 'wait_for_async_insert': 1,
                            'query': f'INSERT INTO {table} FORMAT JSONEachRow'},
                    content='\n'.join(json.dumps(row, ensure_ascii=False) for row in rows).encode('utf-8'),
                )
                response.raise_for_status()
        except Exception as exc:
            log.warning('ClickHouse telemetry insert failed, dropped %d %s rows: %s', len(rows), table, exc)
