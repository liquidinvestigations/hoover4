"""The GPU key check of a GPU service.

All GPU services of an installation share one key. The service reads it from the
environment variable ``HOOVER4_GPU_API_KEY`` and refuses to start without it. Every
request except ``GET /health`` must carry ``Authorization: Bearer <key>``, else the
service answers 401. The health check of Compose and of the cluster calls ``/health``
without the key.

``ai_services/hoover4_ai_server/gpu_key.py`` and ``ai_services/easyocr_server/gpu_key.py``
are copies, because each image has its own build folder. A test compares them.
"""

import hmac
import os

VARIABLE = "HOOVER4_GPU_API_KEY"
OPEN_PATHS = frozenset({"/health"})


def read_key(environ=None):
    """The GPU key of the environment. An empty or missing value stops the start."""
    key = ((environ if environ is not None else os.environ).get(VARIABLE) or "").strip()
    if not key:
        raise SystemExit(
            "%s is empty. Give the service the GPU key of the installation: ./deploy "
            "reads it from [ai_services] vllm_api_key_file, and the cluster from the Secret "
            "gpu-api-key." % VARIABLE)
    return key


def allowed(path, authorization, key):
    """True for an open path, or for a header that carries the key."""
    if path in OPEN_PATHS:
        return True
    return hmac.compare_digest((authorization or "").encode(), ("Bearer " + key).encode())


def install(app, environ=None):
    """Read the key and add the check to a FastAPI app. Return the key."""
    from fastapi.responses import JSONResponse

    key = read_key(environ)

    @app.middleware("http")
    async def require_gpu_key(request, call_next):
        if not allowed(request.url.path, request.headers.get("authorization"), key):
            return JSONResponse({"detail": "This request needs the GPU key in the Authorization header."},
                                status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)

    return key
