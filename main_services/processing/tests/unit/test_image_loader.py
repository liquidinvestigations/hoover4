"""Tests for tasks.P3_parse_files.image_loader.load_image_rgb."""

import numpy as np
import pytest
from PIL import Image

from tasks.P3_parse_files.image_loader import load_image_rgb


def test_decodes_normal_png(tmp_path):
    path = tmp_path / "red.png"
    Image.new("RGB", (8, 6), (255, 0, 0)).save(path)

    arr = load_image_rgb(str(path))

    assert arr is not None
    assert arr.shape == (6, 8, 3)
    assert arr.dtype == np.uint8
    # RGB (not OpenCV's BGR): pure red stays (255, 0, 0)
    assert (arr[0, 0] == [255, 0, 0]).all()


def test_garbage_file_returns_none_without_raising(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 13 + b"not a real image")

    assert load_image_rgb(str(path)) is None


def test_truncated_tiff_returns_none_without_raising(tmp_path):
    path = tmp_path / "broken.tiff"
    Image.new("RGB", (16, 16), (0, 255, 0)).save(path)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 3])  # truncate

    assert load_image_rgb(str(path)) is None


def test_nonexistent_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_image_rgb(str(tmp_path / "does_not_exist.png"))


def test_falls_back_to_pillow_when_opencv_returns_none(tmp_path, monkeypatch):
    """The observed TIFF failure: OpenCV's libtiff lacks the compression."""
    import cv2

    path = tmp_path / "blue.png"
    Image.new("RGB", (4, 4), (0, 0, 255)).save(path)
    monkeypatch.setattr(cv2, "imread", lambda *a, **kw: None)

    arr = load_image_rgb(str(path))

    assert arr is not None
    assert (arr[0, 0] == [0, 0, 255]).all()


def test_falls_back_to_pillow_when_opencv_raises(tmp_path, monkeypatch):
    """OpenCV raises (rather than returning None) for codecs compiled out,
    e.g. `imgcodecs: OpenEXR codec is disabled`. That must not fail the activity."""
    import cv2

    path = tmp_path / "green.png"
    Image.new("RGB", (4, 4), (0, 255, 0)).save(path)

    def _boom(*_args, **_kwargs):
        raise cv2.error("OpenEXR codec is disabled")

    monkeypatch.setattr(cv2, "imread", _boom)

    arr = load_image_rgb(str(path))

    assert arr is not None
    assert (arr[0, 0] == [0, 255, 0]).all()


def test_undecodable_by_both_returns_none(tmp_path, monkeypatch):
    import cv2

    path = tmp_path / "mystery.exr"
    path.write_bytes(b"\x76\x2f\x31\x01" + b"\x00" * 64)

    def _boom(*_args, **_kwargs):
        raise cv2.error("OpenEXR codec is disabled")

    monkeypatch.setattr(cv2, "imread", _boom)

    assert load_image_rgb(str(path)) is None
