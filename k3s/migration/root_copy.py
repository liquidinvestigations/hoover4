#!/usr/bin/env python3
"""Copy one stopped Compose volume folder into one mounted target volume, and verify the copy. Run it as root.

migrate.py runs this script with sudo for each folder of the migration plan, while every source container is stopped
and no pod uses the target volume.

copy   Copies every file, folder and symbolic link of the source into the empty target. Each entry keeps its mode and
       its modification time. Its owner changes from the host id of the source runtime to the id inside the
       container, with the uid and gid maps of that runtime (rootless Podman writes the files of a container user with
       a host id of its subordinate range). Each file is hashed while it is read, and the manifest gets one JSON line
       for it: path, size, sha256, the source owner, the target owner and the mode. A hard link becomes a copy.
       A target that is not empty is refused, so an interrupted copy starts again after `clear`.
verify Reads every file of the target again and compares its size, hash, owner and mode with the manifest. It prints
       the number of entries and of differences, and exits with 1 on a difference or on a target entry that the
       manifest does not name.
clear  Removes every entry of the target folder. migrate.py uses it before a new copy of an interrupted folder.
Usage: root_copy.py copy <source> <target> <uid map> <gid map> <manifest>
       root_copy.py verify <target> <manifest>
       root_copy.py clear <target>
A map file holds the lines of /proc/<pid>/uid_map of the source runtime: inside, outside, count.
"""
import hashlib
import json
import os
import shutil
import stat
import sys

CHUNK = 4 * 1024 * 1024


def parse_map(text):
    """The rows (inside, outside, count) of a uid_map or gid_map text."""
    rows = []
    for line in text.splitlines():
        if line.strip():
            inside, outside, count = (int(x) for x in line.split())
            rows.append((inside, outside, count))
    return rows


def inside_id(host_id, rows):
    """The id inside the container of a host id. A host id outside every range keeps its value."""
    for inside, outside, count in rows:
        if outside <= host_id < outside + count:
            return inside + host_id - outside
    return host_id


def copy_file(source, target):
    digest = hashlib.sha256()
    size = 0
    with open(source, 'rb') as reader, open(target, 'wb') as writer:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
            writer.write(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with open(path, 'rb') as reader:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def copy(source, target, uid_rows, gid_rows, manifest):
    if [n for n in os.listdir(target) if n != 'lost+found']:
        raise SystemExit(f'the target {target} is not empty. Run clear first.')
    entries = 0
    directories = []
    with open(manifest, 'w') as out:
        for root, dirs, files in os.walk(source):
            dirs.sort()
            relative_root = os.path.relpath(root, source)
            for name in sorted(dirs) + sorted(files):
                src = os.path.join(root, name)
                rel = os.path.normpath(os.path.join(relative_root, name))
                dst = os.path.join(target, rel)
                info = os.lstat(src)
                uid, gid = inside_id(info.st_uid, uid_rows), inside_id(info.st_gid, gid_rows)
                row = {'path': rel, 'mode': stat.S_IMODE(info.st_mode), 'source_owner': [info.st_uid, info.st_gid],
                       'owner': [uid, gid]}
                if stat.S_ISLNK(info.st_mode):
                    os.symlink(os.readlink(src), dst)
                    row.update(kind='link', link=os.readlink(src))
                elif stat.S_ISDIR(info.st_mode):
                    os.mkdir(dst)
                    directories.append((dst, info))
                    row.update(kind='dir')
                elif stat.S_ISREG(info.st_mode):
                    size, digest = copy_file(src, dst)
                    if size != info.st_size:
                        raise SystemExit(f'{src} changed during the copy. Stop every source writer, then copy again.')
                    row.update(kind='file', size=size, sha256=digest)
                else:
                    # Sockets and FIFOs hold no data. A store creates them again at start.
                    row.update(kind='special')
                    out.write(json.dumps(row) + '\n')
                    entries += 1
                    continue
                os.lchown(dst, uid, gid)
                if not stat.S_ISLNK(info.st_mode):
                    os.chmod(dst, stat.S_IMODE(info.st_mode))
                    if not stat.S_ISDIR(info.st_mode):
                        os.utime(dst, ns=(info.st_atime_ns, info.st_mtime_ns))
                out.write(json.dumps(row) + '\n')
                entries += 1
        info = os.lstat(source)
        os.chown(target, inside_id(info.st_uid, uid_rows), inside_id(info.st_gid, gid_rows))
        os.chmod(target, stat.S_IMODE(info.st_mode))
        out.write(json.dumps({'path': '.', 'kind': 'dir', 'mode': stat.S_IMODE(info.st_mode),
                              'source_owner': [info.st_uid, info.st_gid],
                              'owner': [inside_id(info.st_uid, uid_rows), inside_id(info.st_gid, gid_rows)]}) + '\n')
        out.flush()
        os.fsync(out.fileno())
    # A folder gets its modification time after its entries, which change it.
    for dst, info in reversed(directories):
        os.utime(dst, ns=(info.st_atime_ns, info.st_mtime_ns))
    # One sync of the target file system writes every copied file, which is faster than a sync after each file.
    fd = os.open(target, os.O_RDONLY)
    try:
        os.fsync(fd)
        if hasattr(os, 'syncfs'):
            os.syncfs(fd)
        else:
            os.sync()
    finally:
        os.close(fd)
    print(json.dumps({'copied': entries, 'source': source, 'target': target}))


def verify(target, manifest):
    rows = [json.loads(line) for line in open(manifest)]
    named = {r['path'] for r in rows}
    differences = []
    for row in rows:
        path = os.path.join(target, row['path'])
        if row['kind'] == 'special':
            continue
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            differences.append({'path': row['path'], 'problem': 'missing'})
            continue
        if [info.st_uid, info.st_gid] != row['owner']:
            differences.append({'path': row['path'], 'problem': 'owner', 'found': [info.st_uid, info.st_gid], 'wanted': row['owner']})
        if row['kind'] != 'link' and stat.S_IMODE(info.st_mode) != row['mode']:
            differences.append({'path': row['path'], 'problem': 'mode'})
        if row['kind'] == 'file':
            size, digest = hash_file(path)
            if (size, digest) != (row['size'], row['sha256']):
                differences.append({'path': row['path'], 'problem': 'content'})
        if row['kind'] == 'link' and os.readlink(path) != row['link']:
            differences.append({'path': row['path'], 'problem': 'link'})
    for root, dirs, files in os.walk(target):
        for name in dirs + files:
            rel = os.path.normpath(os.path.relpath(os.path.join(root, name), target))
            if rel not in named and rel != 'lost+found' and not rel.startswith('lost+found/'):
                differences.append({'path': rel, 'problem': 'not in the manifest'})
    files = sum(1 for r in rows if r['kind'] == 'file')
    total = sum(r.get('size', 0) for r in rows)
    print(json.dumps({'target': target, 'entries': len(rows), 'files': files, 'bytes': total,
                      'differences': len(differences), 'first': differences[:10]}))
    return not differences


def clear(target):
    for name in os.listdir(target):
        if name == 'lost+found':
            continue
        path = os.path.join(target, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)


def main(argv):
    if len(argv) == 6 and argv[0] == 'copy':
        _, source, target, uid_map, gid_map, manifest = argv
        copy(source, target, parse_map(open(uid_map).read()), parse_map(open(gid_map).read()), manifest)
    elif len(argv) == 3 and argv[0] == 'verify':
        sys.exit(0 if verify(argv[1], argv[2]) else 1)
    elif len(argv) == 2 and argv[0] == 'clear':
        clear(argv[1])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
