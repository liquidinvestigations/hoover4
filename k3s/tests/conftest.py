"""Shared helpers of the cluster test suites. The tests import the modules of k3s/ from the repository."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
K3S = TESTS.parent
REPO = K3S.parent
FIXTURES = TESTS / 'fixtures'
# ../settings.py needs a site file name. A missing file gives the defaults of an installation without a site file.
# The tests always use it, and no kubeconfig, because a test that calls a step with its real state folder would change
# the state of the site that the environment names (a zone delete test removed the secrets of a real zone).
os.environ['HOOVER4_SITE'] = '/nonexistent/site.yml'
os.environ.pop('KUBECONFIG', None)
# The secret store of the tests is a JSON file of each test (secret_store()), never the store of a site.
for name in ('HOOVER4_SECRET_STORE', 'HOOVER4_SECRET_TOKEN', 'HOOVER4_SECRET_ROLE', 'HOOVER4_SECRET_ZONE'):
    os.environ.pop(name, None)
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


@pytest.fixture(autouse=True)
def secret_store(tmp_path, monkeypatch):
    """Each test gets its own file store (../secretstore.py FileStore). Return its path."""
    import secretstore
    path = tmp_path / 'secret-store.json'
    monkeypatch.setenv('HOOVER4_SECRET_STORE', f'file://{path}')
    for name in ('HOOVER4_SECRET_TOKEN', 'HOOVER4_SECRET_ROLE', 'HOOVER4_SECRET_ZONE'):
        monkeypatch.delenv(name, raising=False)
    secretstore.reset()
    secretstore._role = None
    yield path
    secretstore.reset()


@pytest.fixture(autouse=True)
def image_tags(monkeypatch):
    """The render tests use a revision that is no commit of the checkout, so every test gets the image tags in
    HOOVER4_IMAGE_TAGS, as deploy-k3s gives them to its steps."""
    keys = ('website', 'processing', 'regex', 'tesseract', 'ocr-pdf', 'clamav', 'pdf-search', 'garage-init', 'mcp-collections',
            'mcp-todo', 'mcp-whois', 'mcp-metasearch', 'mcp-browser', 'web-tor', 'research-agent', 'ai-server', 'easyocr', 'vllm')
    monkeypatch.setenv('HOOVER4_IMAGE_TAGS', json.dumps({k: f'tag-{k}' for k in keys}))
