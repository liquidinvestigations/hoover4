"""Collect parser Arrow rows and isolate storage failures by file."""

from contextlib import contextmanager
from contextvars import ContextVar

BUFFER_BYTES = 8 * 1024 * 1024
_CURRENT = ContextVar('parser_insert_batch', default=None)


def current_batch():
    """Return the insert buffer of this activity thread."""
    return _CURRENT.get()


@contextmanager
def parser_insert_batch():
    """Keep one insert buffer for this stage activity."""
    batch = ParserInsertBatch()
    token = _CURRENT.set(batch)
    try:
        yield batch
    finally:
        _CURRENT.reset(token)


class ParserInsertBatch:
    """Write each table once per buffer and retain each file's write failures."""

    def __init__(self):
        self.index = None
        self.seen = set()
        self.callbacks = {}
        self.rows = {}
        self.errors = {}
        self.bytes = 0
        self.did_flush = False

    def add(self, client, table, rows, kwargs):
        if not rows.num_rows or self.index in self.errors:
            return
        # A parser table has one schema and one insert configuration per client.
        self.seen.add(self.index)
        identity = (id(client), table)
        entry = self.rows.setdefault(identity, (client, table, dict(kwargs), []))
        if entry[2] != kwargs:
            raise ValueError(f'Parser insert settings changed for {table}')
        entry[3].append((self.index, rows))
        self.bytes += rows.nbytes
        if self.bytes >= BUFFER_BYTES:
            self.flush()
            self.did_flush = True

    def after_storage(self, callback):
        """Run cleanup only after this file's rows reach storage."""
        self.seen.add(self.index)
        self.callbacks.setdefault(self.index, []).append(callback)

    def finish_file(self, index):
        callbacks = self.callbacks.pop(index, [])
        if index in self.errors:
            return
        for callback in callbacks:
            callback()

    def flush(self):
        """Wait for each batch, then isolate a failed batch by file."""
        import pyarrow as pa
        from database.clickhouse import insert_arrow_durable
        from tasks.heartbeat import stop_if_worker_is_stopping
        from temporalio.exceptions import CancelledError

        pending, self.rows = self.rows, {}
        self.bytes = 0
        # An OCR watermark goes last, so it reaches storage only after its text, and a
        # file whose text failed to store gets no watermark.
        priorities = {'blob_values': 0, 'blobs': 1, 'vfs_files': 2, 'table_documents': 4,
                      'raw_ocr_results': 5}
        ordered = sorted(pending.values(), key=lambda entry: priorities.get(entry[1], 3))
        for client, table, kwargs, pieces in ordered:
            stop_if_worker_is_stopping()
            pieces = [(index, rows) for index, rows in pieces if index not in self.errors]
            if not pieces:
                continue
            try:
                insert_arrow_durable(client, table, pa.concat_tables([rows for _, rows in pieces]), **kwargs)
            except CancelledError:
                raise
            except Exception:
                stop_if_worker_is_stopping()
                files = {}
                for index, rows in pieces:
                    files.setdefault(index, []).append(rows)
                for index, rows in files.items():
                    try:
                        insert_arrow_durable(client, table, pa.concat_tables(rows), **kwargs)
                    except CancelledError:
                        raise
                    except Exception as exc:
                        stop_if_worker_is_stopping()
                        self.errors[index] = exc
