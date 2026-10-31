"""Split archives: name schemes, the volume set of a file, and its completeness.

7-Zip finds the later volumes of a split archive from the name of the first volume, in
the same folder. The plan download names each file by its hash, so the archive stage
writes every volume of the set under its own name into a temporary folder first.

A **volume set** is resolved from the live `vfs_files` rows of one dataset: the rows in
the same container and folder whose names have the same stem and scheme. Its descriptor
holds the dataset, container, folder, scheme, the entry volume (the one that 7-Zip
opens), the ordered names and the ordered hashes. The extracted members belong to the
entry hash as their container, which is the identity that the folder tree and the search
index already use.

Rules that the archive stage applies (`parse_archives.extract_archive_batch`):

* A file whose names have no volume scheme is extracted as before.
* A name with a volume scheme but without a sibling of its set is a standalone file. A
  numbered `.001` file without the bytes of an archive is skipped, not an error.
* The entry volume extracts the complete set. A gap in the indexes, a missing entry, a
  missing final `.zip` of a spanned zip, and a 7-Zip diagnostic about a missing or
  truncated volume raise `SplitArchiveIncomplete`, which names the missing volume when the
  names allow it.
* A later volume extracts the complete set too, when its entry volume is not in the same
  stage batch. This makes a volume that arrives later, or that replaces an earlier one,
  refresh the members. Members of the earlier extraction that the new one lacks are
  tombstoned.
* One entry hash can occur in several folders. When those occurrences resolve to more
  than one distinct complete set, the stage raises `SplitArchiveAmbiguous` and chooses no
  set. Incomplete occurrences beside one complete set do not block it, because the
  container and the error of a file are both keyed by its hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

#: The error types of the archive stage for split sets.
SPLIT_ARCHIVE_INCOMPLETE = "SplitArchiveIncomplete"
SPLIT_ARCHIVE_AMBIGUOUS = "SplitArchiveAmbiguous"

NUMBERED = "numbered"
RAR_PART = "rar_part"
RAR_OLD = "rar_old"
ZIP_SPAN = "zip_span"

_NUMBERED = re.compile(r"^(?P<stem>.+)\.(?P<index>\d{3,})$")
_RAR_PART = re.compile(r"^(?P<stem>.+)\.part(?P<index>\d+)\.rar$", re.IGNORECASE)
_RAR_OLD_LATER = re.compile(r"^(?P<stem>.+)\.r(?P<index>\d{2,})$", re.IGNORECASE)
_ZIP_SPAN_LATER = re.compile(r"^(?P<stem>.+)\.z(?P<index>\d{2,})$", re.IGNORECASE)

#: The first bytes of the archive formats that 7-Zip splits: 7z, zip and RAR.
ARCHIVE_SIGNATURES = (b"7z\xbc\xaf\x27\x1c", b"PK\x03\x04", b"PK\x07\x08", b"PK\x05\x06", b"Rar!\x1a\x07")


@dataclass(frozen=True)
class Volume:
    """The place of one name in a split scheme. `order` sorts the volumes of a set."""

    stem: str
    scheme: str
    order: int
    entry: bool


def volume_of(name: str) -> Optional[Volume]:
    """The volume that `name` is, or None for a name without a split scheme.

    `x.7z.001` and `x.001` are numbered volumes, entry `001`. `x.part1.rar` and
    `x.part01.rar` are RAR part volumes, entry part 1. `x.rar` with `x.r00` is an old RAR
    set, entry `x.rar`. `x.z01` with `x.zip` is a spanned zip, entry `x.zip`, which is the
    last volume. A plain `x.rar` or `x.zip` is an entry candidate that needs siblings.
    """
    match = _RAR_PART.match(name)
    if match:
        index = int(match.group("index"))
        return Volume(match.group("stem").lower(), RAR_PART, index, index == 1)
    match = _NUMBERED.match(name)
    if match:
        index = int(match.group("index"))
        return Volume(match.group("stem").lower(), NUMBERED, index, index == 1)
    match = _RAR_OLD_LATER.match(name)
    if match:
        return Volume(match.group("stem").lower(), RAR_OLD, int(match.group("index")) + 1, False)
    match = _ZIP_SPAN_LATER.match(name)
    if match:
        return Volume(match.group("stem").lower(), ZIP_SPAN, int(match.group("index")), False)
    lowered = name.lower()
    if lowered.endswith(".rar"):
        return Volume(name[:-4].lower(), RAR_OLD, 0, True)
    if lowered.endswith(".zip"):
        # The spanned zip's own `.zip` is its last volume and the one that 7-Zip opens.
        return Volume(name[:-4].lower(), ZIP_SPAN, 10 ** 6, True)
    return None


def is_volume_name(names: Sequence[str]) -> bool:
    """Whether any name has a split scheme other than a plain `.rar` or `.zip`."""
    for name in names:
        volume = volume_of(name)
        if volume is not None and not (volume.entry and volume.scheme in (RAR_OLD, ZIP_SPAN)):
            return True
    return False


def has_archive_signature(head: bytes) -> bool:
    return any(head.startswith(signature) for signature in ARCHIVE_SIGNATURES)


@dataclass
class VolumeSet:
    """The descriptor of one occurrence of a split set."""

    collection_dataset: str
    container_hash: str
    folder: str
    scheme: str
    stem: str
    #: `(order, name, hash, size, s3_path)` of each present volume, in order.
    volumes: List[Tuple[int, str, str, int, str]] = field(default_factory=list)

    @property
    def names(self) -> List[str]:
        return [v[1] for v in self.volumes]

    @property
    def hashes(self) -> List[str]:
        return [v[2] for v in self.volumes]

    @property
    def size(self) -> int:
        return sum(v[3] for v in self.volumes)

    @property
    def entry(self) -> Optional[Tuple[int, str, str, int, str]]:
        for volume in self.volumes:
            if volume_of(volume[1]).entry:
                return volume
        return None

    def has_siblings(self) -> bool:
        return len(self.volumes) > 1

    def missing(self) -> List[str]:
        """The names of the volumes that the indexes show as missing."""
        orders = [v[0] for v in self.volumes]
        sample = self.volumes[0][1] if self.volumes else ""
        missing: List[str] = []
        if self.scheme in (NUMBERED, RAR_PART):
            width = len(re.search(r"(\d+)(?:\.rar)?$", sample, re.IGNORECASE).group(1)) if sample else 3
            last = max(orders) if orders else 1
            for index in range(1, last + 1):
                if index not in orders:
                    missing.append(_volume_name(self, index, width))
        elif self.scheme == RAR_OLD:
            last = max(orders) if orders else 0
            for order in range(0, last + 1):
                if order not in orders:
                    missing.append(f"{self.stem}.rar" if order == 0 else f"{self.stem}.r{order - 1:02d}")
        elif self.scheme == ZIP_SPAN:
            parts = [o for o in orders if o < 10 ** 6]
            for index in range(1, (max(parts) if parts else 0) + 1):
                if index not in parts:
                    missing.append(f"{self.stem}.z{index:02d}")
            if 10 ** 6 not in orders:
                missing.append(f"{self.stem}.zip")
        return missing

    def next_name(self) -> str:
        """The name of the volume after the last present one, for a missing final volume."""
        if not self.volumes:
            return ""
        last = self.volumes[-1]
        if self.scheme in (NUMBERED, RAR_PART):
            width = len(re.search(r"(\d+)(?:\.rar)?$", last[1], re.IGNORECASE).group(1))
            return _volume_name(self, last[0] + 1, width)
        if self.scheme == RAR_OLD:
            return f"{self.stem}.r{last[0]:02d}"
        return ""

    def key(self) -> Tuple[str, ...]:
        return tuple(self.hashes)


def _volume_name(volume_set: VolumeSet, index: int, width: int) -> str:
    sample = volume_set.volumes[0][1]
    if volume_set.scheme == RAR_PART:
        prefix = sample[:re.search(r"\.part\d+\.rar$", sample, re.IGNORECASE).start()]
        return f"{prefix}.part{index:0{width}d}.rar"
    prefix = sample[:sample.rindex(".")]
    return f"{prefix}.{index:0{width}d}"


def group_volume_sets(rows: Sequence[Tuple[str, str, str, int, str]], collection_dataset: str) -> List[VolumeSet]:
    """Volume sets from `(container_hash, path, hash, size, s3_path)` rows of live files.

    Rows group by container, folder, stem and scheme. A plain `.rar` joins an old RAR set
    and a plain `.zip` joins a spanned zip set only when that set has later volumes.
    """
    sets: Dict[Tuple[str, str, str, str], VolumeSet] = {}
    for container, path, file_hash, size, s3_path in rows:
        folder, _, name = path.rpartition("/")
        volume = volume_of(name)
        if volume is None:
            continue
        key = (container, folder, volume.stem, volume.scheme)
        target = sets.setdefault(key, VolumeSet(collection_dataset, container, folder or "/",
                                                volume.scheme, volume.stem))
        target.volumes.append((volume.order, name, file_hash, int(size or 0), s3_path or ""))
    result = []
    for volume_set in sets.values():
        volume_set.volumes.sort(key=lambda v: v[0])
        result.append(volume_set)
    return result


def resolve_volume_sets(client, collection_dataset: str, file_hash: str) -> List[VolumeSet]:
    """Every set that an occurrence of `file_hash` belongs to, from live rows only.

    A set without a sibling is left out, so a file without one is a standalone file.
    """
    rows = client.query(
        "SELECT f.container_hash, f.path, f.hash, f.file_size_bytes, b.s3_path FROM vfs_files AS f FINAL "
        "LEFT JOIN (SELECT blob_hash, any(s3_path) AS s3_path FROM blobs WHERE collection_dataset = {cd:String} "
        "GROUP BY blob_hash) AS b ON b.blob_hash = f.hash "
        "WHERE f.collection_dataset = {cd:String} AND f.is_deleted = 0 "
        "AND (f.container_hash, substring(f.path, 1, length(f.path) - position(reverse(f.path), '/') + 1)) IN ("
        "SELECT container_hash, substring(path, 1, length(path) - position(reverse(path), '/') + 1) "
        "FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND hash = {h:String} AND is_deleted = 0)",
        parameters={"cd": collection_dataset, "h": file_hash}).result_rows
    sets = group_volume_sets([(r[0], r[1], r[2], r[3], r[4]) for r in rows], collection_dataset)
    return [s for s in sets if file_hash in s.hashes and s.has_siblings()]


def safe_volume_name(name: str) -> str:
    """The exact name for the temporary folder. A name with a path separator or a
    parent reference is refused."""
    if not name or "/" in name or "\x00" in name or name in (".", "..") or "\\" in name:
        raise ValueError(f"unsafe volume name {name!r}")
    return name
