#!/usr/bin/env python3
"""Check the source folders of a Compose import on the source node, and measure them. Run it as root. It changes nothing.

import_compose.py sends this script to Python on standard input of the source node (sudo -n python3 -), with one JSON
argument:
  root      the data root of the source node (data_root of the site file)
  folder    the Compose volume folder, relative to the root
  volumes   the names of the Compose volume folders that the import copies. A missing folder is an empty volume.
  required  the names of the store folders that must exist
  datasets  {name: folder relative to the root} of the writable dataset folders
Each folder must resolve below the root, also through symbolic links. The script prints one JSON object: the absolute
path, the size in bytes and the owner of each existing folder, and the problems.

Usage: probe.py '<json>'
"""
import json
import os
import sys


def below(root, path):
    """True when the real path of path is the real root or a path below it."""
    real, top = os.path.realpath(path), os.path.realpath(root)
    return real == top or real.startswith(top.rstrip('/') + '/')


def size(path):
    total = 0
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


def measure(path):
    info = os.lstat(path)
    return {'path': os.path.realpath(path), 'bytes': size(path), 'owner': [info.st_uid, info.st_gid]}


def probe(request):
    root, problems = request['root'], []
    out = {'volumes': {}, 'datasets': {}, 'problems': problems}
    if not os.path.isdir(root):
        problems.append(f'the data root {root} of the source node is not a folder.')
        return out
    volume_folder = os.path.join(root, request['folder'])
    if not below(root, volume_folder):
        problems.append(f'the folder {request["folder"]} leaves the data root {root} through a symbolic link.')
        return out
    if not os.path.isdir(volume_folder):
        problems.append(f'the folder {request["folder"]} does not exist below the data root {root}.')
        return out
    for name in request['volumes']:
        path = os.path.join(volume_folder, name)
        if not os.path.lexists(path):
            if name in request['required']:
                problems.append(f'the store folder {name} does not exist in {request["folder"]}.')
            continue
        if not below(root, path):
            problems.append(f'the folder {name} of {request["folder"]} leaves the data root through a symbolic link.')
        elif not os.path.isdir(path):
            problems.append(f'{name} in {request["folder"]} is not a folder.')
        else:
            out['volumes'][name] = measure(path)
    for name, folder in sorted(request.get('datasets', {}).items()):
        path = os.path.join(root, folder)
        if not below(root, path):
            problems.append(f'the dataset folder {folder} of {name} leaves the data root through a symbolic link.')
        elif not os.path.isdir(path):
            problems.append(f'the dataset folder {folder} of {name} does not exist below the data root {root}.')
        elif below(volume_folder, path) or below(path, volume_folder):
            problems.append(f'the dataset folder {folder} of {name} overlaps the volume folder {request["folder"]}.')
        else:
            out['datasets'][name] = measure(path)
    paths = sorted(set(v['path'] for v in list(out['volumes'].values()) + list(out['datasets'].values())))
    for i, first in enumerate(paths):
        for second in paths[i + 1:]:
            if second.startswith(first.rstrip('/') + '/'):
                problems.append(f'the folders {first} and {second} overlap, so the copy is ambiguous.')
    return out


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    print(json.dumps(probe(json.loads(argv[0]))))


if __name__ == '__main__':
    main(sys.argv[1:])
