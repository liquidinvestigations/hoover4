"""Run the external parser tools in bubblewrap, without the credentials and the network of the worker.

A parser tool reads an untrusted file. The worker process holds the store credentials in
its environment and can reach the stores. With ``HOOVER4_PARSER_SANDBOX=bwrap``,
:func:`run` and :class:`Popen` start each tool in a new user, network, IPC and UTS
namespace with an empty environment:

- The root file system is read-only.
- The folders of :func:`hidden` are empty: the plan folders of other plans, the dataset
  mounts of ``HOOVER4_DATASET_MOUNTS``, the secrets and the control files.
- The folder of each absolute path in the arguments (and the working folder) is
  visible again. A path in a dataset mount is read-only, and any other path is
  writable, so a tool writes only beside its own input and into its own output folder.
- ``/proc`` is the one of the worker. A process in the new user namespace cannot read
  the environment of the worker processes, because that read needs a ptrace right in
  the namespace of the worker.
- The environment holds ``PATH``, ``HOME=/tmp``, ``LANG`` and only the variables that
  the call site sets itself, not the ones it copies from the worker.

Without the setting, both functions are the ones of :mod:`subprocess`, so a Compose
worker runs each tool as before. The sandbox needs no capability, but it needs a runtime
that allows a new user namespace, for example a Kata or gVisor pod.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

#: The folders that are always empty in the sandbox. ``/data`` is the dataset root of a
#: cluster deployment.
BASE_HIDDEN = ("/tmp", "/run", "/var/run", "/data", "/control", "/upload-tmp", "/mirror", "/root")


def _dataset_paths() -> tuple[str, ...]:
    """The container paths of the dataset mounts of this worker, or ``/testdata``."""
    from tasks.dataset_mounts import DatasetMountsError, dataset_mounts
    try:
        return tuple(mount.path for mount in dataset_mounts())
    except DatasetMountsError:
        return ("/testdata",)


def hidden() -> tuple[str, ...]:
    """Every folder that is empty in the sandbox."""
    return tuple(dict.fromkeys(BASE_HIDDEN + _dataset_paths()))


def read_only() -> tuple[str, ...]:
    """The folders below which a path is read-only in the sandbox. A parser only reads a
    dataset, so a writable dataset mount is read-only here too."""
    return ("/data",) + _dataset_paths()


#: Tests replace these. None reads hidden() and read_only().
HIDDEN: tuple[str, ...] | None = None
READ_ONLY: tuple[str, ...] | None = None
_PATH = re.compile(r"(?:^|[=,]|^-o|file://)(/[^\s,]+)")
_BASE_ENV = ("PATH", "LANG", "LC_ALL", "TZ")


def enabled() -> bool:
    return os.getenv("HOOVER4_PARSER_SANDBOX", "").strip() == "bwrap"


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _hidden() -> tuple[str, ...]:
    return HIDDEN if HIDDEN is not None else hidden()


def _read_only() -> tuple[str, ...]:
    return READ_ONLY if READ_ONLY is not None else read_only()


def _visible(path: str) -> str | None:
    """The folder to show for a path of an argument, or None when it needs no bind."""
    path = os.path.normpath(path)
    roots = _hidden()
    if not any(_within(path, root) for root in roots):
        return None
    target = path if os.path.isdir(path) else os.path.dirname(path)
    while target and not os.path.isdir(target):
        target = os.path.dirname(target)
    # The roots themselves stay hidden, so a tool never sees the folders of other plans.
    if not target or target in roots or target in ("/", "/tmp/hoover4"):
        return path if os.path.exists(path) else None
    return target


def _binds(argv: list[str], cwd: str | None) -> list[str]:
    paths = []
    for arg in argv[1:]:
        paths += _PATH.findall(str(arg))
    if cwd:
        paths.append(cwd)
    out: list[str] = []
    seen = set()
    for path in paths:
        shown = _visible(path)
        if shown and shown not in seen:
            seen.add(shown)
            mode = "--ro-bind" if any(_within(shown, r) for r in _read_only()) else "--bind"
            out += [mode, shown, shown]
    return out


def _environment(env: dict | None) -> list[str]:
    values = {k: os.environ[k] for k in _BASE_ENV if k in os.environ}
    values["HOME"] = "/tmp"
    for key, value in (env or {}).items():
        # A value that the call site copies from the worker stays out, so the
        # credentials do not enter the sandbox.
        if key in _BASE_ENV or os.environ.get(key) != value:
            values[key] = value
    out = ["--clearenv"]
    for key, value in values.items():
        out += ["--setenv", key, str(value)]
    return out


def command(argv, env: dict | None = None, cwd: str | None = None) -> list[str]:
    """The bubblewrap command line for ``argv``."""
    argv = [str(a) for a in argv]
    bwrap = shutil.which("bwrap") or "/usr/bin/bwrap"
    out = [bwrap, "--unshare-user", "--unshare-ipc", "--unshare-net", "--unshare-uts",
           "--unshare-cgroup-try", "--die-with-parent", "--new-session",
           *_environment(env), "--ro-bind", "/", "/", "--ro-bind", "/proc", "/proc", "--dev", "/dev"]
    for root in _hidden():
        # bwrap cannot mount on a symbolic link, for example /var/run to /run. The
        # target of the link is hidden itself.
        if os.path.isdir(root) and not os.path.islink(root):
            out += ["--tmpfs", root]
    out += _binds(argv, cwd)
    if cwd:
        out += ["--chdir", cwd]
    return out + ["--", *argv]


def _wrap(args, kwargs):
    if not enabled():
        return args, kwargs
    if isinstance(args, (str, bytes)) or kwargs.get("shell"):
        raise ValueError("the parser sandbox runs an argument list, not a shell command")
    env = kwargs.pop("env", None)
    return command(args, env, kwargs.get("cwd")), {**kwargs, "env": None}


def run(args, **kwargs) -> subprocess.CompletedProcess:
    """:func:`subprocess.run`, in the sandbox when it is on."""
    args, kwargs = _wrap(args, kwargs)
    return subprocess.run(args, **kwargs)


def Popen(args, **kwargs) -> subprocess.Popen:  # noqa: N802 - the name of subprocess.Popen
    """:class:`subprocess.Popen`, in the sandbox when it is on."""
    args, kwargs = _wrap(args, kwargs)
    return subprocess.Popen(args, **kwargs)
