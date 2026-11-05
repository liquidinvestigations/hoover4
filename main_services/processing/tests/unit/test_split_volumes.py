"""Split archive names, set grouping, completeness and routing."""

import pytest

from tasks.P3_parse_files.split_volumes import (
    NUMBERED, RAR_OLD, RAR_PART, ZIP_SPAN, group_volume_sets, is_volume_name, safe_volume_name, volume_of)


@pytest.mark.parametrize("name, scheme, order, entry", [
    ("x.7z.001", NUMBERED, 1, True),
    ("X.7Z.002", NUMBERED, 2, False),
    ("x.zip.029", NUMBERED, 29, False),
    ("plain.001", NUMBERED, 1, True),
    ("a.part1.rar", RAR_PART, 1, True),
    ("a.PART01.RAR", RAR_PART, 1, True),
    ("a.part033.rar", RAR_PART, 33, False),
    ("old.rar", RAR_OLD, 0, True),
    ("old.r00", RAR_OLD, 1, False),
    ("old.R01", RAR_OLD, 2, False),
    ("span.z01", ZIP_SPAN, 1, False),
    ("span.zip", ZIP_SPAN, 10 ** 6, True),
])
def test_volume_schemes(name, scheme, order, entry):
    volume = volume_of(name)
    assert (volume.scheme, volume.order, volume.entry) == (scheme, order, entry)


@pytest.mark.parametrize("name", ["report.001.pdf", "notes.txt", "x.7z", "photo.r2d2", "a.part.rar.txt"])
def test_names_that_only_look_similar(name):
    volume = volume_of(name)
    assert volume is None or volume.scheme == RAR_OLD and name.endswith(".rar")


def test_plain_archives_are_not_volume_names():
    assert not is_volume_name(["a.zip"]) and not is_volume_name(["b.rar"])
    assert is_volume_name(["x.7z.002"]) and is_volume_name(["old.r00"])


def rows(*names, folder="/f", container=""):
    return [(container, f"{folder}/{name}", f"h-{folder}-{name}", 10, "") for name in names]


def test_complete_sets_and_missing_volumes():
    sets = group_volume_sets(rows("x.7z.001", "x.7z.002", "x.7z.003"), "ds")
    assert len(sets) == 1 and sets[0].missing() == [] and sets[0].entry[1] == "x.7z.001"
    gap = group_volume_sets(rows("x.7z.001", "x.7z.003"), "ds")[0]
    assert gap.missing() == ["x.7z.002"] and gap.next_name() == "x.7z.004"
    no_first = group_volume_sets(rows("x.7z.002", "x.7z.003"), "ds")[0]
    assert no_first.entry is None and no_first.missing() == ["x.7z.001"]
    parts = group_volume_sets(rows("a.part01.rar", "a.part03.rar"), "ds")[0]
    assert parts.missing() == ["a.part02.rar"]
    old = group_volume_sets(rows("o.r00", "o.r01"), "ds")[0]
    assert old.missing() == ["o.rar"]
    span = group_volume_sets(rows("s.z01", "s.z02"), "ds")[0]
    assert span.missing() == ["s.zip"]
    assert group_volume_sets(rows("s.z01", "s.zip"), "ds")[0].missing() == []


def test_sets_are_per_folder_and_container():
    sets = group_volume_sets(rows("x.7z.001", "x.7z.002") + rows("x.7z.001", folder="/g")
                             + rows("x.7z.002", container="c1"), "ds")
    assert sorted((s.folder, s.container_hash, len(s.volumes)) for s in sets) == [
        ("/f", "", 2), ("/f", "c1", 1), ("/g", "", 1)]


def test_unsafe_names_are_refused():
    for bad in ["../x.7z.001", "a/b.001", "..", ""]:
        with pytest.raises(ValueError):
            safe_volume_name(bad)
    assert safe_volume_name("x.7z.001") == "x.7z.001"


@pytest.mark.parametrize("names", [
    ("log.20260101", "log.20260102"),
    ("x.001", "x.999999999999999999999999999999"),
    ("x.part1.rar", "x.part999999999999999999999999.rar"),
    ("x.rar", "x.r999999999999999999999999"),
    ("x.z01", "x.z999999999999999999999999"),
])
def test_missing_names_are_bounded_for_extreme_suffixes(names):
    volume_set = group_volume_sets(rows(*names), "ds")[0]
    missing = volume_set.missing()
    assert volume_set.missing_count() >= 20
    assert len(missing) == 20
    assert len("".join(missing)) < 2000
