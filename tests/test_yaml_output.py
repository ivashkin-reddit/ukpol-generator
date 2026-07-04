"""Tests for the YAML rule output adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ukpol_generator.adapters.yaml_output import YamlRuleOutput

if TYPE_CHECKING:
    from pathlib import Path


def test_write_creates_output_directory_and_file(tmp_path: Path) -> None:
    """Writing creates the output directory and returns the file path."""
    output = YamlRuleOutput(directory=tmp_path / "output", filename="rules.yaml")
    destination = output.write("# generated rules\n")

    assert destination == tmp_path / "output" / "rules.yaml"
    assert destination.read_text(encoding="utf-8") == "# generated rules\n"
