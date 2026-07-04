"""Tests for the CLI driving adapter's argument dispatch."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ukpol_generator.cli import main
from ukpol_generator.domain.models import Member, RawContact
from ukpol_generator.ports.contacts import ContactSourceError

if TYPE_CHECKING:
    from pathlib import Path

_RAW_MEMBERS: list[dict[str, object]] = [
    {
        "id": 1,
        "name": "Ms Diane Abbott",
        "party": "Independent",
        "house": "Commons",
        "constituency": "Hackney North",
        "contacts": [
            {"typeId": None, "line1": "https://twitter.com/HackneyAbbott", "website": None}
        ],
    }
]


def test_generate_writes_rules_file(tmp_path: Path) -> None:
    """`generate` reads the cached dump and writes the rules document."""
    raw_path = tmp_path / "raw.json"
    _ = raw_path.write_text(json.dumps(_RAW_MEMBERS), encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(["generate", "--input", str(raw_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    written = output_dir / "generated-social-rules.yaml"
    assert written.exists()
    assert "# Rule GEN-TWITTER" in written.read_text(encoding="utf-8")


def test_generate_respects_custom_filename(tmp_path: Path) -> None:
    """The --filename flag controls the output document name."""
    raw_path = tmp_path / "raw.json"
    _ = raw_path.write_text(json.dumps(_RAW_MEMBERS), encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "generate",
            "--input",
            str(raw_path),
            "--output-dir",
            str(output_dir),
            "--filename",
            "custom.yaml",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "custom.yaml").exists()


def test_missing_subcommand_exits_with_error() -> None:
    """Invoking with no subcommand makes argparse exit non-zero."""
    with pytest.raises(SystemExit) as exc:
        _ = main([])
    assert exc.value.code == 2


def test_run_fetches_and_generates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`run` caches fetched members and writes the generated rules."""
    members = [
        Member(
            id=1,
            name="Ms Diane Abbott",
            party="Independent",
            house="Commons",
            constituency="Hackney North",
            contacts=(
                RawContact(
                    type_id=None,
                    line1="https://twitter.com/HackneyAbbott",
                    website=None,
                ),
            ),
        )
    ]

    def fake_load_members(_self: object) -> list[Member]:
        return members

    monkeypatch.setattr(
        "ukpol_generator.cli.ParliamentApiContactSource.load_members",
        fake_load_members,
    )
    raw_path = tmp_path / "raw.json"
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "run",
            "--output",
            str(raw_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert raw_path.exists()
    written = output_dir / "generated-social-rules.yaml"
    assert written.exists()
    assert "# Rule GEN-TWITTER" in written.read_text(encoding="utf-8")


def _install_failing_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the API adapter's load_members raise ContactSourceError."""

    def failing_load_members(_self: object) -> list[Member]:
        message = "contact fetch failed after 3 attempts"
        raise ContactSourceError(message)

    monkeypatch.setattr(
        "ukpol_generator.cli.ParliamentApiContactSource.load_members",
        failing_load_members,
    )


def test_fetch_exits_nonzero_on_incomplete_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`fetch` returns 1 and writes no cache when the source aborts."""
    _install_failing_source(monkeypatch)
    raw_path = tmp_path / "raw.json"

    exit_code = main(["fetch", "--output", str(raw_path)])

    assert exit_code == 1
    assert not raw_path.exists()


def test_run_exits_nonzero_on_incomplete_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run` returns 1 and generates nothing when the fetch aborts."""
    _install_failing_source(monkeypatch)
    raw_path = tmp_path / "raw.json"
    output_dir = tmp_path / "out"

    exit_code = main(["run", "--output", str(raw_path), "--output-dir", str(output_dir)])

    assert exit_code == 1
    assert not raw_path.exists()
    assert not (output_dir / "generated-social-rules.yaml").exists()
