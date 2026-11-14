"""The HTTP tests call a running server, which needs the GPU key on every route except
/health. With HOOVER4_GPU_API_KEY set, each request of the requests library sends it."""

import os

KEY = (os.environ.get("HOOVER4_GPU_API_KEY") or "").strip()

if KEY:
    import requests.api

    _request = requests.api.request

    def _request_with_key(method, url, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("Authorization", "Bearer " + KEY)
        return _request(method, url, headers=headers, **kwargs)

    requests.api.request = _request_with_key
