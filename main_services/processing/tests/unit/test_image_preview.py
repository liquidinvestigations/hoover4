"""The image preview stage: which files get a preview, and what the converters may read."""

import shutil
import subprocess

import pytest

from tasks.P3_parse_files import image_preview as ip


@pytest.mark.parametrize("head,mimes,routes,kind", [
    (b"\xff\xd8\xff\xe0", ["image/jpeg"], ["image"], ""),
    (b"\x89PNG\r\n\x1a\n", ["image/png"], ["image"], ""),
    (b"BM\x00\x00", ["image/bmp"], ["image"], ""),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", ["image/webp"], ["image"], ""),
    (b"\x00\x00\x00\x18ftypheic", ["image/heic"], ["image"], "raster"),
    (b"GIF89a", ["image/gif"], ["image"], "raster"),
    (b"II*\x00", ["image/tiff"], ["image"], "raster"),
    (b"<?xml version='1.0'?>\n<svg xmlns=", ["text/xml"], ["image"], "svg"),
    (b"\x1f\x8b", ["image/svg+xml"], ["image"], "svg"),
    (b"\x00\x00\x00\x18ftypisom", ["video/mp4"], ["video"], "video"),
])
def test_preview_kind(head, mimes, routes, kind):
    assert ip.preview_kind(head, mimes, routes) == kind


def test_split_s3_path_accepts_only_preview_keys():
    assert ip.split_s3_path("s3://hoover4-c-x/derived/image-preview/h.jpg") == (
        "hoover4-c-x", "derived/image-preview/h.jpg")
    assert ip.split_s3_path("s3://hoover4-c-x/blobs/h") == ("", "")
    assert ip.split_s3_path("/etc/passwd") == ("", "")
    assert ip.split_s3_path(0) == ("", "")


def _pixel(path, x, y):
    out = subprocess.run(["magick", path, "-format", f"%[pixel:p{{{x},{y}}}]", "info:"],
                         capture_output=True, check=True)
    return out.stdout.decode()


@pytest.mark.skipif(not shutil.which("rsvg-convert") or not shutil.which("magick"),
                    reason="the converters are in the worker image")
def test_svg_preview_fits_480_and_does_not_read_outside_files(tmp_path):
    secret = tmp_path / "secret.png"
    subprocess.run(["magick", "-size", "64x64", "xc:red", str(secret)], check=True)
    svg = tmp_path / "logo.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
        ' width="200" height="100"><rect width="200" height="100" fill="blue"/>'
        f'<image width="64" height="64" xlink:href="{secret}"/></svg>')
    work = tmp_path / "work"
    work.mkdir()
    out = ip.make_preview_file(str(svg), "svg", str(work), 60)
    size = subprocess.run(["magick", "identify", "-format", "%w %h", out],
                          capture_output=True, check=True).stdout.decode()
    assert size == "480 240"
    assert _pixel(out, 10, 10).startswith("srgb(0,0,25")


@pytest.mark.skipif(not shutil.which("magick"), reason="the converter is in the worker image")
def test_raster_policy_refuses_a_file_outside_the_work_folder(tmp_path):
    secret = tmp_path / "secret.png"
    subprocess.run(["magick", "-size", "64x64", "xc:red", str(secret)], check=True)
    mvg = tmp_path / "drawing.mvg"
    mvg.write_text(f"viewbox 0 0 100 100\nimage over 0,0 64,64 '{secret}'\n")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(RuntimeError):
        ip.make_preview_file(str(mvg), "raster", str(work), 60)


@pytest.mark.skipif(not shutil.which("magick"), reason="the converter is in the worker image")
def test_raster_preview_keeps_the_resolution(tmp_path):
    tiff = tmp_path / "scan.tiff"
    subprocess.run(["magick", "-size", "1700x2200", "xc:white", str(tiff)], check=True)
    work = tmp_path / "work"
    work.mkdir()
    out = ip.make_preview_file(str(tiff), "raster", str(work), 60)
    size = subprocess.run(["magick", "identify", "-format", "%w %h %m", out],
                          capture_output=True, check=True).stdout.decode()
    assert size == "1700 2200 JPEG"
