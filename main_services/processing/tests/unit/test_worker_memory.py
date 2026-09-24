"""The memory log writes one line at the threshold and one at each further step."""

import asyncio
import logging

import pytest

from tasks import worker_memory

GB = 1024**3


def test_memory_log_steps(caplog):
    readings = iter([int(4.2 * GB), int(4.5 * GB), int(5.1 * GB)])
    in_flight = {1: "parse_email_extract_text_headers abc123"}

    def read_rss():
        try:
            return next(readings)
        except StopIteration:
            raise asyncio.CancelledError

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await worker_memory.watch_memory(
                "processing-common-queue", in_flight, read_rss=read_rss, interval=0)

    with caplog.at_level(logging.WARNING, logger=worker_memory.__name__):
        asyncio.run(run())

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert lines == [
        "worker processing-common-queue resident size 4300 MB, activities in flight: "
        "parse_email_extract_text_headers abc123",
        "worker processing-common-queue resident size 5222 MB, activities in flight: "
        "parse_email_extract_text_headers abc123",
    ]


def test_memory_log_names_no_activity():
    assert worker_memory.describe({}) == "none"


def test_read_rss_bytes_reads_this_process():
    assert worker_memory.read_rss_bytes() > 0
