"""Run concurrent real split extraction processes with isolated transfer directories."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import threading

import pytest
from temporalio.exceptions import CancelledError

from tasks.P2_execute_plan import activities
from tasks.P3_parse_files import parse_archives, split_volumes

pytestmark = pytest.mark.integration


@pytest.fixture
def volume_set(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    source = tmp_path / "payload.bin"
    source.write_bytes(bytes(range(256)) * 64)
    subprocess.run(["7z", "a", "-mx=0", "-v1024b", str(tmp_path / "archive.7z"), str(source)],
                   check=True, capture_output=True)
    volumes = sorted(tmp_path.glob("archive.7z.*"))
    assert len(volumes) > 1
    files = {path.name: path for path in volumes}
    rows = [("", "/" + path.name, path.name, path.stat().st_size, "") for path in volumes]
    resolved = split_volumes.group_volume_sets(rows, "dataset")[0]

    def transfer(collection, dataset, items, **kwargs):
        for item in items:
            shutil.copyfile(files[item["item_hash"]], item["path"])

    monkeypatch.setattr(activities, "write_blob_files", transfer)
    return resolved, source.read_bytes()


@pytest.mark.parametrize("cancel_first", [False, True])
def test_attempt_cleanup_preserves_a_concurrent_extraction(volume_set, monkeypatch, cancel_first):
    resolved, expected = volume_set
    original = subprocess.run
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    attempts = []

    def extract(command, **kwargs):
        if command[0] == "7z" and command[1] == "x":
            with lock:
                ordinal = len(attempts)
                attempts.append(command)
            barrier.wait(timeout=10)
            if cancel_first and ordinal == 0:
                raise CancelledError("cancel one extraction")
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", extract)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(parse_archives.extract_split_set, "collection", resolved,
                                   resolved.entry[2]) for _ in range(2)]
        outputs, errors = [], []
        for future in futures:
            try:
                outputs.append(future.result(timeout=30))
            except CancelledError as error:
                errors.append(error)
    assert len(outputs) == (1 if cancel_first else 2)
    assert len(errors) == int(cancel_first)
    assert len({str(Path(command[-1]).parent) for command in attempts}) == 2
    if len(outputs) == 2:
        shutil.rmtree(outputs[0]["out_dir"])
        outputs = outputs[1:]
    for result in outputs:
        assert (Path(result["out_dir"]) / "payload.bin").read_bytes() == expected
        shutil.rmtree(result["out_dir"])
