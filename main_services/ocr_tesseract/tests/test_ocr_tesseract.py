"""Verify JPEG recovery, the Tesseract execution limit and the handler threads."""

import asyncio
import inspect
import io
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

import ocr_tesseract as service


def jpeg_bytes():
    image = Image.new("RGB", (320, 60), "white")
    ImageDraw.Draw(image).text((10, 15), "EXAMPLE DOCUMENT 12345", fill="black")
    image = image.resize((1280, 240))
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def invalid_scan_header(data):
    value = bytearray(data)
    offset = value.index(b"\xff\xda")
    size = int.from_bytes(value[offset + 2:offset + 4], "big")
    value[offset + size] = 0
    return bytes(value)


def test_a_decodable_jpeg_with_an_invalid_scan_header_recovers(monkeypatch):
    native = subprocess.run
    attempts = []

    def run(command, **kwargs):
        attempts.append(Path(command[1]).read_bytes()[:8])
        return native(command, **kwargs)

    monkeypatch.setattr(service.subprocess, "run", run)
    text, _, words = service._run_tesseract(invalid_scan_header(jpeg_bytes()), "eng", 6)
    assert "EXAMPLE" in text and words
    assert attempts == [b"\xff\xd8\xff\xe0\x00\x10JF", b"\x89PNG\r\n\x1a\n"]


def test_the_png_retry_preserves_dimensions_and_the_time_limit(monkeypatch):
    calls = []
    clock = iter([10.0, 12.0])
    monkeypatch.setattr(service.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(service, "OCR_SUBPROCESS_TIMEOUT_S", 30)

    def run(command, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            return SimpleNamespace(returncode=1, stderr=b"Error in pixReadStreamJpeg", stdout=b"")
        with Image.open(command[1]) as image:
            assert image.format == "PNG" and image.size == (1280, 240)
        return SimpleNamespace(returncode=0, stderr=b"", stdout=b"")

    monkeypatch.setattr(service.subprocess, "run", run)
    assert service._run_tesseract(jpeg_bytes(), "eng", 6) == ("", 0.0, [])
    assert calls == [30, 28]


def test_an_undecodable_jpeg_keeps_its_original_failure(monkeypatch):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stderr=b"Error in pixReadStreamJpeg: bad data", stdout=b"")

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="pixReadStreamJpeg: bad data"):
        service._run_tesseract(b"\xff\xd8invalid", "eng", 6)
    assert len(calls) == 1


def test_a_retry_cannot_start_after_the_execution_limit(monkeypatch):
    clock = iter([10.0, 40.0])
    monkeypatch.setattr(service.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(service, "OCR_SUBPROCESS_TIMEOUT_S", 30)
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stderr=b"Error in pixReadStreamJpeg", stdout=b"")

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        service._run_tesseract(jpeg_bytes(), "eng", 6)
    assert len(calls) == 1


def test_handler_threads_cover_the_admission():
    """FastAPI runs a `def` handler on AnyIO's thread limiter, 40 by default. Above that,
    admitted requests waited for a thread with no answer, and `/health` with them."""
    import anyio.to_thread

    async def limit_inside_lifespan():
        async with service.lifespan(service.app):
            return anyio.to_thread.current_default_thread_limiter().total_tokens

    assert asyncio.run(limit_inside_lifespan()) == (
        service.OCR_CONCURRENCY + service.OCR_QUEUE_DEPTH + 4)


def test_health_answers_without_a_handler_thread():
    assert inspect.iscoroutinefunction(service.health)
    body = asyncio.run(service.health())
    assert body["concurrency"] == service.OCR_CONCURRENCY
    assert body["queue_depth"] == service.OCR_QUEUE_DEPTH
    assert body["http_threads"] == service.HTTP_THREADS
