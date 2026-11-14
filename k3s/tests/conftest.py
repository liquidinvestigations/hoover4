"""Shared helpers of the cluster test suites. The tests import the modules of k3s/ from the repository."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
K3S = TESTS.parent
REPO = K3S.parent
FIXTURES = TESTS / 'fixtures'
# ../settings.py needs a site file name. A missing file gives the defaults of an installation without a site file.
os.environ.setdefault('HOOVER4_SITE', '/nonexistent/site.yml')
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'hoover'))
sys.path.insert(0, str(K3S / 'hoover' / 'stores'))


def operator_settings():
    """k3s/platform/operator/settings.py under its own module name. k3s/settings.py holds the name settings."""
    name = 'operator_settings'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, K3S / 'platform/operator/settings.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def site_text(name):
    return (FIXTURES / name).read_text().replace('@REPO@', str(REPO))


def write_site(folder, name, text=None):
    """Write the site file fixture name into folder, with the zone state of fixtures/<stem>.zones.json in its state
    folder when that fixture exists. Return the path of the site file."""
    path = Path(folder) / name
    path.write_text(text if text is not None else site_text(name))
    zones = FIXTURES / (Path(name).stem + '.zones.json')
    if zones.exists():
        path.with_suffix('').mkdir(parents=True, exist_ok=True)
        (path.with_suffix('') / 'zone-state.json').write_text(zones.read_text())
    return path


@pytest.fixture
def site_file(tmp_path):
    def write(name, text=None):
        return write_site(tmp_path, name, text)
    return write
