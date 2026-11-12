"""The pinned source tree of a deployment. Standard library only.

deploy-k3s runs every script and renderer of an up or a down from one exported commit, not from the working files of
the checkout. export() writes `git archive <commit>` once into k3s/private/build/<commit>/, the folder that
../images/build-hoover.py builds the images from. The stamp .hoover-build-commit names the commit. The link
k3s/private of the tree points to the private folder of the checkout, so the scripts of the tree find the site file,
the secrets and the operator state. A local change of the checkout stays unchanged and out of the tree.
fingerprint() is the SHA-256 of every file of the tree except the private link. The record of a run keeps it, and a
resume refuses a tree that changed.
"""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

STAMP = '.hoover-build-commit'


class SourceError(RuntimeError):
    """The tree of a commit cannot be written or has changed."""


def tree_folder(private, commit):
    return Path(private) / 'build' / commit


def is_export(folder):
    """The commit of an exported tree, or None for a checkout."""
    stamp = Path(folder) / STAMP
    return stamp.read_text().strip() if stamp.exists() else None


def export(repo, private, commit):
    """Write the tree of a full commit id once and return its folder."""
    if len(commit) != 40:
        raise SourceError(f'{commit} is not a full commit id')
    tree = tree_folder(private, commit)
    if is_export(tree) == commit:
        link(tree, private)
        return tree
    partial = tree.with_name(commit + '.partial')
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    archive = subprocess.Popen(['git', '-C', str(repo), 'archive', commit], stdout=subprocess.PIPE)
    extract = subprocess.run(['tar', '-x', '-C', str(partial)], stdin=archive.stdout)
    if archive.wait() or extract.returncode:
        shutil.rmtree(partial, ignore_errors=True)
        raise SourceError(f'git archive of {commit} from {repo} failed')
    (partial / STAMP).write_text(commit)
    shutil.rmtree(tree, ignore_errors=True)
    os.replace(partial, tree)
    link(tree, private)
    return tree


def link(tree, private):
    """Point k3s/private of the tree to the private folder of the checkout."""
    path = Path(tree) / 'k3s' / 'private'
    path.parent.mkdir(exist_ok=True)
    # An absolute link: the operator portal mounts the k3s folder of the tree and an empty folder over its private
    # link. A relative link resolves to the root of the container there, and the container runtime refuses the mount.
    target = str(Path(private).resolve())
    if path.is_symlink() and os.readlink(path) == target:
        return
    if path.is_symlink() or path.exists():
        path.unlink()
    path.symlink_to(target)


def fingerprint(tree):
    """The SHA-256 of the paths and contents of the tree, without the private link."""
    tree = Path(tree)
    digest = hashlib.sha256()
    for root, dirs, files in os.walk(tree):
        # Python writes __pycache__ folders into the tree when a step imports a module. They are not source.
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        rel_root = Path(root).relative_to(tree)
        if rel_root == Path('k3s'):
            dirs[:] = [d for d in dirs if d != 'private']
        for name in sorted(files):
            path = Path(root) / name
            rel = path.relative_to(tree)
            if rel == Path('k3s/private'):
                continue
            digest.update(str(rel).encode() + b'\0')
            if path.is_symlink():
                digest.update(b'link:' + os.readlink(path).encode())
            else:
                with open(path, 'rb') as f:
                    while chunk := f.read(1 << 20):
                        digest.update(chunk)
            digest.update(b'\0')
    return digest.hexdigest()
