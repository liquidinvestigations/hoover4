"""Adds the model server's API key to local calls to vLLM inside the hoover4-vllm container.

The compose wrapper mounts this folder at /opt/hoover4 and puts it first on PYTHONPATH, so
Python imports this module at start-up in every process of the container. The structured
server of the image calls vLLM with `urllib.request.urlopen` and sends no Authorization
header. vLLM refuses such a call with 401 when VLLM_API_KEY is set. This module wraps
`urlopen` so that a call to `http://127.0.0.1:<PORT>/` gets `Authorization: Bearer <key>`
when it has no Authorization header. A call to any other address is unchanged.

The key comes from HOOVER4_UPSTREAM_KEY, which the wrapper reads from the key file. An
empty key changes nothing.

A sitecustomize module of the image is hidden by this one, so this module runs it after
the wrap.
"""

import importlib.machinery
import importlib.util
import os
import sys
import urllib.request

KEY = os.environ.get("HOOVER4_UPSTREAM_KEY", "")
LOCAL = "http://127.0.0.1:" + os.environ.get("PORT", "8000") + "/"


def add_key(request, key=KEY, local=LOCAL):
    """The request with the key added when it goes to the local vLLM port.

    `request` is a URL string or a `urllib.request.Request`. The result is the same
    object when nothing changes.
    """
    if not key:
        return request
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    if not url.startswith(local):
        return request
    if not isinstance(request, urllib.request.Request):
        request = urllib.request.Request(url)
    if not request.has_header("Authorization"):
        request.add_header("Authorization", "Bearer " + key)
    return request


if KEY:
    _original_urlopen = urllib.request.urlopen

    def urlopen(request, *args, **kwargs):
        return _original_urlopen(add_key(request), *args, **kwargs)

    urllib.request.urlopen = urlopen


def _run_image_sitecustomize():
    here = os.path.dirname(os.path.abspath(__file__))
    rest = [p for p in sys.path if os.path.abspath(p or ".") != here]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


_run_image_sitecustomize()
