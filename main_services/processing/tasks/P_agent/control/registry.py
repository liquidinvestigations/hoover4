"""The registry of policy handlers.

Handlers are trusted Python modules that the deployment provides read-only. Two directories
hold them: the built-in `handlers/` beside this file, and `handlers/` under the directory
that `HOOVER4_CHAT_CONTROL_DIR` names, when it is set. Each directory has a `manifest.json`:

    {"handlers": [{"name": "discovery", "module": "discovery.py",
                   "factory": "Handler", "api_version": 1}]}

The registry imports each named module from its file, calls the factory, and records the
SHA-256 of the file as the handler's code digest. A definition names handlers by these
names only, so editable rule data never holds an import path. A duplicate name, a module
outside its directory, an unknown factory or another interface version is a
configuration error, raised when the registry loads.

Activity code loads the registry, never workflow code, because Temporal replays workflow
code and a changed module must not change a replayed history.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from tasks.P_agent.control.model import API_VERSION, HandlerRef

BUILTIN_DIR = Path(__file__).resolve().parent
#: The deployment variable of the directory of custom handlers and definitions.
CONTROL_DIR_ENV = "HOOVER4_CHAT_CONTROL_DIR"


class ControlConfigError(ValueError):
    """A handler or a definition that cannot be used. The message names the fault."""


@dataclass(frozen=True)
class Registered:
    ref: HandlerRef
    handler: Any
    path: str


def control_dirs() -> list[Path]:
    """The built-in directory, then the configured one when it is set."""
    dirs = [BUILTIN_DIR]
    configured = (os.environ.get(CONTROL_DIR_ENV) or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_dir():
            raise ControlConfigError(f"{CONTROL_DIR_ENV} names {configured}, which is not a directory")
        dirs.append(path.resolve())
    return dirs


def _load_dir(root: Path, out: Dict[str, Registered]) -> None:
    handler_dir = root / "handlers"
    manifest_path = handler_dir / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text())
    except ValueError as exc:
        raise ControlConfigError(f"{manifest_path} is not JSON: {exc}") from None
    entries = manifest.get("handlers") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise ControlConfigError(f"{manifest_path} has no handlers list")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ControlConfigError(f"{manifest_path} has an entry that is not an object")
        name = str(entry.get("name") or "")
        module = str(entry.get("module") or "")
        factory = str(entry.get("factory") or "Handler")
        version = entry.get("api_version")
        if not name or not module:
            raise ControlConfigError(f"{manifest_path}: an entry has no name or module")
        if name in out:
            raise ControlConfigError(f"the handler name {name!r} is registered twice "
                                     f"({out[name].path} and {handler_dir / module})")
        path = (handler_dir / module).resolve()
        if handler_dir.resolve() not in path.parents or path.suffix != ".py":
            raise ControlConfigError(f"handler {name!r}: the module {module!r} is not a .py "
                                     f"file inside {handler_dir}")
        if version != API_VERSION:
            raise ControlConfigError(f"handler {name!r} declares interface version {version!r}, "
                                     f"and this worker implements {API_VERSION}")
        code = path.read_bytes()
        code_digest = hashlib.sha256(code).hexdigest()
        spec = importlib.util.spec_from_file_location(
            f"hoover4_chat_control_{code_digest[:12]}_{name}", path)
        if spec is None or spec.loader is None:
            raise ControlConfigError(f"handler {name!r}: {path} cannot be imported")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        make = getattr(mod, factory, None)
        if make is None:
            raise ControlConfigError(f"handler {name!r}: {path} has no factory {factory!r}")
        handler = make()
        if getattr(handler, "api_version", None) != API_VERSION:
            raise ControlConfigError(f"handler {name!r} implements interface version "
                                     f"{getattr(handler, 'api_version', None)!r}, not {API_VERSION}")
        for method in ("validate", "evaluate"):
            if not callable(getattr(handler, method, None)):
                raise ControlConfigError(f"handler {name!r} has no {method} method")
        out[name] = Registered(HandlerRef(name, API_VERSION, code_digest), handler, str(path))


_lock = threading.Lock()
_loaded: Optional[Dict[str, Registered]] = None


def load(refresh: bool = False) -> Dict[str, Registered]:
    """Every registered handler by name. The first call imports the modules."""
    global _loaded
    with _lock:
        if _loaded is None or refresh:
            out: Dict[str, Registered] = {}
            for root in control_dirs():
                _load_dir(root, out)
            _loaded = out
        return _loaded


def runtime_identity() -> str:
    """The digest of every registered handler identity, for the run record."""
    from tasks.P_agent.control.model import digest

    return digest(sorted([r.ref.name, r.ref.api_version, r.ref.code_digest]
                         for r in load().values()))
