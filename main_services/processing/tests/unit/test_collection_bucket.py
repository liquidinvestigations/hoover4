"""The bucket name of a collection, from the case file the website tests read too."""

import json
from pathlib import Path

import pytest

from database import s3

_CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "tasks" / "collection_bucket_cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", _CASES, ids=[c["collectionname"] for c in _CASES])
def test_bucket_name_matches_the_shared_case(case):
    expected = s3.COLLECTION_BUCKET_PREFIX + case["bucket"][len("hoover4-c-"):]
    assert s3.collection_bucket(case["collectionname"]) == expected


def test_every_bucket_name_is_a_valid_s3_name():
    for case in _CASES:
        bucket = case["bucket"]
        assert 3 <= len(bucket) <= 63
        assert "_" not in bucket
        assert bucket == bucket.lower()


def test_an_invalid_collection_name_has_no_bucket():
    with pytest.raises(ValueError):
        s3.collection_bucket("bad-name")
