from __future__ import annotations

import hashlib

import pytest

from interview_edit.adapters.verified_copy import copy_verified
from interview_edit.errors import PreflightError


def test_bad_resource_does_not_replace_existing_destination(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"wrong")
    destination.write_bytes(b"existing")
    with pytest.raises(PreflightError):
        copy_verified(source, destination, hashlib.sha256(b"expected").hexdigest())
    assert destination.read_bytes() == b"existing"
    assert {p.name for p in tmp_path.iterdir()} == {"source", "destination"}


def test_interrupted_copy_cleans_only_its_temporary_file(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"source")

    def interrupt(*args):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        copy_verified(source, destination, hashlib.sha256(b"source").hexdigest(), interrupt)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == [source]


def test_copied_resource_can_be_edited_without_mutating_source(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"source")
    updates = []
    copy_verified(
        source,
        destination,
        hashlib.sha256(b"source").hexdigest(),
        lambda current, total: updates.append((current, total)),
    )
    destination.write_bytes(b"changed")
    assert source.read_bytes() == b"source"
    assert updates[-1] == (6, 6)
