"""Tests for the application use-case services using in-memory port doubles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ukpol_generator.application.fetch_contacts import FetchContactsService
from ukpol_generator.application.generate_rules import GenerateRulesService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ukpol_generator.domain.models import Member


@dataclass
class _StubSource:
    """A contact source returning a fixed member list."""

    members: list[Member]

    def load_members(self) -> list[Member]:
        """Return the preconfigured members."""
        return self.members


@dataclass
class _RecordingSink:
    """A sink that records the members it was asked to persist."""

    saved: list[Member] = field(default_factory=list)

    def save_members(self, members: Sequence[Member]) -> Path:
        """Record the members and return a fixed destination path."""
        self.saved.extend(members)
        return Path("raw.json")


@dataclass
class _RecordingOutput:
    """An output that captures the rendered document."""

    documents: list[str] = field(default_factory=list)

    def write(self, document: str) -> Path:
        """Record the document and return a fixed destination path."""
        self.documents.append(document)
        return Path("output/generated-social-rules.yaml")


def test_fetch_service_persists_and_counts(sample_members: list[Member]) -> None:
    """The fetch service persists members and reports member/contact counts."""
    sink = _RecordingSink()
    result = FetchContactsService(source=_StubSource(members=sample_members), sink=sink).run()

    assert sink.saved == sample_members
    assert result.member_count == 2
    assert result.contact_count == 3
    assert result.output_path == Path("raw.json")


def test_generate_service_renders_and_counts(sample_members: list[Member]) -> None:
    """The generate service writes a document and reports per-platform counts."""
    output = _RecordingOutput()
    result = GenerateRulesService(source=_StubSource(members=sample_members), output=output).run()

    assert len(output.documents) == 1
    assert "# Rule GEN-TWITTER" in output.documents[0]
    assert result.accounts_per_platform == {"Twitter": 1, "Facebook": 1}
    assert result.output_path == Path("output/generated-social-rules.yaml")
