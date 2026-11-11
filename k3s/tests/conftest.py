"""Shared helpers of the cluster test suites. The tests import the modules of k3s/ from the repository."""
import importlib.util
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
K3S = TESTS.parent
REPO = K3S.parent
FIXTURES = TESTS / 'fixtures'
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


@pytest.fixture
def site_file(tmp_path):
    def write(name, text=None):
        path = tmp_path / name
        path.write_text(text if text is not None else site_text(name))
        return path
    return write
