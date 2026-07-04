"""Tests for the JSON contact store round-trip serialisation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ukpol_generator.adapters.json_store import JsonContactStore

if TYPE_CHECKING:
    from pathlib import Path

    from ukpol_generator.domain.models import Member


def test_save_then_load_round_trips_members(tmp_path: Path, sample_members: list[Member]) -> None:
    """Members saved to disk are reloaded with identical field values."""
    store = JsonContactStore(path=tmp_path / "nested" / "raw.json")
    written = store.save_members(sample_members)
    assert written.exists()

    reloaded = store.load_members()
    assert reloaded == sample_members


def test_save_leaves_no_temp_file(tmp_path: Path, sample_members: list[Member]) -> None:
    """A successful save replaces the temp file rather than leaving it behind."""
    path = tmp_path / "raw.json"
    _ = JsonContactStore(path=path).save_members(sample_members)

    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()


def test_failed_save_preserves_previous_cache(
    tmp_path: Path,
    sample_members: list[Member],
) -> None:
    """A save that dies before the atomic rename leaves the old cache intact.

    The failure is injected through the real filesystem boundary - a
    directory squatting on the temp path makes the write itself fail - never
    by patching shared stdlib state, which would leak into pytest plugins
    that serialise JSON while the patch is live.
    """
    path = tmp_path / "raw.json"
    store = JsonContactStore(path=path)
    _ = store.save_members(sample_members)
    good_content = path.read_text(encoding="utf-8")

    path.with_name(path.name + ".tmp").mkdir()
    with pytest.raises(OSError, match=r"raw\.json\.tmp"):
        _ = store.save_members(sample_members)

    assert path.read_text(encoding="utf-8") == good_content


def test_load_skips_records_without_id(tmp_path: Path) -> None:
    """Records lacking an integer id are dropped on load."""
    path = tmp_path / "raw.json"
    _ = path.write_text('[{"name": "No Id"}, {"id": 3, "name": "Kept"}]', encoding="utf-8")
    store = JsonContactStore(path=path)

    members = store.load_members()
    assert len(members) == 1
    assert members[0].id == 3
    assert members[0].name == "Kept"


def test_load_rejects_non_array_root(tmp_path: Path) -> None:
    """A cache whose root is not a JSON array fails clearly."""
    path = tmp_path / "raw.json"
    _ = path.write_text('{"id": 3, "name": "Wrong root"}', encoding="utf-8")
    store = JsonContactStore(path=path)

    with pytest.raises(TypeError, match=r"list|array"):
        _ = store.load_members()
