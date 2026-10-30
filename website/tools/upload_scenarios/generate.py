#!/usr/bin/env python3
"""Write the data sets of the bounded upload scenarios.

Usage: generate.py <data set> <output folder> [options]. Run `generate.py --help` for the
data sets and `generate.py <data set> --help` for the options of one data set.

Each data set is a folder tree. The upload clients select its top folder, so the upload
paths start with the name of that folder. A data set can also write a `begin` body as
JSON when the scenario sends names that a Linux disk cannot hold.

The script refuses an output folder that exists, and it refuses an output folder inside
a Git working tree, because the data sets must stay out of the repository. It also
refuses options that write more than `MAX_FILES` files or `MAX_BYTES` bytes, the limits
of one scenario.
File contents come from a seeded generator, so two runs with one seed write the same
bytes. Every file gets the modification time `MTIME`.
"""
import argparse
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import zipfile

#: The modification time of every written file, in seconds since 1970.
MTIME = 1792500000
#: The longest name in a path of the upload routes (`website/common/src/uploads.rs`).
MAX_SEGMENT_BYTES = 255
#: The body limit of the `begin` route.
MANIFEST_MAX_BYTES = 16 * 1024 * 1024
#: The largest number of files and bytes of one data set.
MAX_FILES = 1000
MAX_BYTES = 512 * 1024 * 1024
#: The size of one block that `random_bytes` writes at a time.
BLOCK = 4 * 1024 * 1024


def random_bytes(seed, size):
    """Yield `size` bytes from a generator seeded with `seed`, in blocks of `BLOCK`."""
    rng = random.Random(seed)
    left = size
    while left > 0:
        n = min(BLOCK, left)
        yield rng.randbytes(n)
        left -= n


def random_text(seed, size):
    """Yield `size` bytes of seeded hexadecimal text in lines of 64 characters. Text keeps
    the content sniffer from reading a small file as audio, an image or an archive."""
    rng = random.Random(seed)
    out = bytearray()
    while len(out) < size:
        out += rng.randbytes(32).hex().encode() + b"\n"
    yield bytes(out[:size])


def write_file(path, chunks):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as out:
        for chunk in chunks:
            out.write(chunk)
    os.utime(path, (MTIME, MTIME))


#: The word that every smoke file holds, so one search finds all of them.
SMOKE_WORD = "quokkasmoke"


def smoke(out, files, seed):
    """Smoke: `files` text files in 3 folder levels. Every file holds `SMOKE_WORD` and the
    word `quokkasmoke<n>` with its own number."""
    for i in range(files):
        parts = [f"level1_{i % 3}", f"level2_{i % 5}"]
        text = f"{SMOKE_WORD} {SMOKE_WORD}{i:03d} {hashlib.sha256(f'{seed}:{i}'.encode()).hexdigest()}\n"
        write_file(os.path.join(out, *parts, f"smoke{i:03d}.txt"), [text.encode()])


def many_small(out, files, folders, size, seed):
    """T1, R3: `files` text files of `size` bytes, spread over `folders` folders."""
    for i in range(files):
        folder = f"d{i % folders:04d}"
        write_file(os.path.join(out, folder, f"f{i:06d}.txt"),
                   random_text(f"{seed}:{i}", size))


def one_large(out, size, seed):
    """T2: one file of `size` random bytes."""
    write_file(os.path.join(out, "large.bin"), random_bytes(seed, size))


def begin_body(request_id, collection, folder, files):
    """The `begin` body as the page sends it: compact JSON, non-ASCII characters as UTF-8."""
    body = {"request_id": request_id, "collection": collection, "folder": folder,
            "files": [{"path": p, "size": s, "last_modified_ms": MTIME * 1000} for p, s in files]}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


#: M2: one path for each rule, and the text that the page and `begin` show for it.
PATH_RULE_CASES = [
    ("rules/control\x01name.txt", "The name holds a control character."),
    ("rules/../escape.txt", "A name in the path is . or .."),
    ("rules/" + "n" * 256 + ".txt", "A name in the path is longer than 255 bytes."),
    ("rules/" + "/".join(f"s{i}" for i in range(63)) + "/deep.txt", "The path has more than 64 parts."),
    ("rules/.hoover4-upload-x.hoover4-part", "The name is reserved for the upload service."),
]


def path_rules(out, collection):
    """M2: a disk tree with the rule cases that a Linux disk can hold, and `begin.json`
    with all five cases. `cases.json` lists each path with its rule text."""
    os.makedirs(out, exist_ok=True)
    for path, _message in PATH_RULE_CASES:
        names = path.split("/")
        if ".." in names or any(len(n.encode()) > MAX_SEGMENT_BYTES for n in names):
            continue
        write_file(os.path.join(out, "disk", *names), [b"rule case\n"])
    with open(os.path.join(out, "begin.json"), "wb") as handle:
        handle.write(begin_body("m2-path-rules", collection, "/m2",
                                [(p, 10) for p, _ in PATH_RULE_CASES]))
    with open(os.path.join(out, "cases.json"), "w") as handle:
        json.dump([{"path": p, "message": m} for p, m in PATH_RULE_CASES], handle,
                  ensure_ascii=False, indent=1)


def large_manifest(out, collection, files):
    """M3: two `begin` bodies of `files` empty files with long ASCII paths. `below.json`
    is exactly 16 MiB, the largest body that the route accepts, and `above.json` is 1 byte
    above it. Spaces before the end of the file list fill each body to its size, because
    the paths of `MAX_FILES` files are much shorter. `sizes.json` records both sizes."""
    os.makedirs(out, exist_ok=True)
    listed = [f"m3/{'a' * 250}/{'b' * 250}/{'c' * 250}/f{i:06d}.txt" for i in range(files)]
    compact = begin_body("m3-large-manifest", collection, "/", [(p, 0) for p in listed])
    if not compact.endswith(b"]}") or len(compact) >= MANIFEST_MAX_BYTES:
        raise SystemExit("internal error: the compact body does not fit below the limit")

    def body(size):
        return compact[:-2] + b" " * (size - len(compact)) + b"]}"

    below, above = body(MANIFEST_MAX_BYTES), body(MANIFEST_MAX_BYTES + 1)
    for name, data in (("above.json", above), ("below.json", below)):
        with open(os.path.join(out, name), "wb") as handle:
            handle.write(data)
    with open(os.path.join(out, "sizes.json"), "w") as handle:
        json.dump({"below": len(below), "above": len(above), "files": files}, handle)


def _member_zip(handle, members, member_bytes, seed, prefix):
    with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for i in range(members):
            info = zipfile.ZipInfo(f"{prefix}{i // 1000:03d}/m{i:06d}.txt",
                                   date_time=(2026, 10, 1, 0, 0, 0))
            data = hashlib.sha256(f"{seed}:{prefix}:{i}".encode()).hexdigest().encode()
            archive.writestr(info, (data * (member_bytes // len(data) + 1))[:member_bytes])


def many_members(out, members, member_bytes, seed):
    """T3: one zip of `members` members of `member_bytes` bytes each, in folders of 1,000."""
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "members.zip")
    with open(path, "wb") as handle:
        _member_zip(handle, members, member_bytes, seed, "part")
    os.utime(path, (MTIME, MTIME))


def nested_archives(out, inner, members, member_bytes, seed):
    """T3: one zip that holds `inner` zips of `members` members each."""
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "nested.zip")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as outer:
        for z in range(inner):
            buffer = io.BytesIO()
            _member_zip(buffer, members, member_bytes, f"{seed}:{z}", f"inner{z:02d}_")
            info = zipfile.ZipInfo(f"inner{z:02d}.zip", date_time=(2026, 10, 1, 0, 0, 0))
            outer.writestr(info, buffer.getvalue())
    os.utime(path, (MTIME, MTIME))


def shared_path(out, seed):
    """C1: two selections `first` and `second` that share the file `shared/report.txt`
    relative to their top folders, so both give one destination in one upload folder."""
    for top in ("first", "second"):
        write_file(os.path.join(out, top, "shared", "report.txt"), [f"{seed} shared\n".encode()])
        write_file(os.path.join(out, top, f"only-{top}.txt"), [f"{seed} {top}\n".encode()])


def no_space(out, files, size):
    """S1: `files` sparse files of `size` bytes."""
    os.makedirs(out, exist_ok=True)
    for i in range(files):
        path = os.path.join(out, f"part{i}.bin")
        with open(path, "wb") as handle:
            handle.truncate(size)
        os.utime(path, (MTIME, MTIME))


def size_arg(text):
    """A byte count: a whole number with an optional suffix K, M, G (powers of 1,000) or
    Ki, Mi, Gi (powers of 1,024)."""
    units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "K": 1000, "M": 1000 ** 2, "G": 1000 ** 3}
    for suffix in ("Ki", "Mi", "Gi", "K", "M", "G"):
        if text.endswith(suffix):
            return int(text[: -len(suffix)]) * units[suffix]
    return int(text)


def inside_git_tree(path):
    probe = os.path.dirname(os.path.abspath(path))
    while not os.path.isdir(probe):
        probe = os.path.dirname(probe)
    result = subprocess.run(["git", "-C", probe, "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def check_bounds(name, args):
    """Refuse options that write more than one scenario allows."""
    files = getattr(args, "files", 1)
    size = getattr(args, "size", 0)
    total = {"smoke": files * 100, "many_small": files * size, "one_large": size,
             "no_space": 0}.get(name, 0)
    if files > MAX_FILES or total > MAX_BYTES:
        raise SystemExit(f"{name} would write more than {MAX_FILES} files or {MAX_BYTES} bytes.")
    members = getattr(args, "members", 0) * getattr(args, "inner", 1)
    if members * getattr(args, "member_size", 0) > MAX_BYTES:
        raise SystemExit(f"{name} would write more than {MAX_BYTES} bytes of members.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sets = parser.add_subparsers(dest="data_set", required=True)

    def add(name, help_text):
        sub = sets.add_parser(name, help=help_text)
        sub.add_argument("out", help="output folder; it must not exist")
        sub.add_argument("--seed", default=name)
        return sub

    sub = add("smoke", "smoke: a few text files in 3 folder levels with searchable words")
    sub.add_argument("--files", type=int, default=30)
    sub = add("many_small", "T1, R3: many small files in a few folders")
    sub.add_argument("--files", type=int, default=1000)
    sub.add_argument("--folders", type=int, default=10)
    sub.add_argument("--size", type=size_arg, default=1024)
    sub = add("one_large", "T2: one large file of random bytes")
    sub.add_argument("--size", type=size_arg, default=256 * 1024 ** 2)
    sub = add("path_rules", "M2: one path for each path rule")
    sub.add_argument("--collection", required=True)
    sub = add("large_manifest", "M3: begin bodies at and above the 16 MiB limit")
    sub.add_argument("--collection", required=True)
    sub.add_argument("--files", type=int, default=1000)
    sub = add("many_members", "T3: a zip of many small members")
    sub.add_argument("--members", type=int, default=1000)
    sub.add_argument("--member-size", type=size_arg, default=100)
    sub = add("nested_archives", "T3: a zip of zips")
    sub.add_argument("--inner", type=int, default=2)
    sub.add_argument("--members", type=int, default=100)
    sub.add_argument("--member-size", type=size_arg, default=100)
    add("shared_path", "C1: two selections with one shared path")
    sub = add("no_space", "S1: sparse files larger than a small file system")
    sub.add_argument("--files", type=int, default=2)
    sub.add_argument("--size", type=size_arg, default=16 * 1024 ** 2)
    args = parser.parse_args()

    if os.path.exists(args.out):
        raise SystemExit(f"{args.out} exists. Choose a new folder.")
    if inside_git_tree(args.out):
        raise SystemExit(f"{args.out} is inside a Git working tree. Choose a folder outside it.")
    name = args.data_set
    check_bounds(name, args)
    if name == "smoke":
        smoke(args.out, args.files, args.seed)
    elif name == "many_small":
        many_small(args.out, args.files, args.folders, args.size, args.seed)
    elif name == "one_large":
        one_large(args.out, args.size, args.seed)
    elif name == "path_rules":
        path_rules(args.out, args.collection)
    elif name == "large_manifest":
        large_manifest(args.out, args.collection, args.files)
    elif name == "many_members":
        many_members(args.out, args.members, args.member_size, args.seed)
    elif name == "nested_archives":
        nested_archives(args.out, args.inner, args.members, args.member_size, args.seed)
    elif name == "shared_path":
        shared_path(args.out, args.seed)
    elif name == "no_space":
        no_space(args.out, args.files, args.size)
    print(f"{name} written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
