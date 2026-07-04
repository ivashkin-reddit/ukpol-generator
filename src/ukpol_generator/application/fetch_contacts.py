"""Use case: fetch member contacts from a source and persist them to a sink."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ukpol_generator.ports.contacts import MemberContactSink, MemberContactSource


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a fetch-and-store run.

    Attributes:
        output_path: Where the raw records were persisted.
        member_count: Number of members fetched.
        contact_count: Total contact records across all members.
    """

    output_path: Path
    member_count: int
    contact_count: int


@dataclass(frozen=True)
class FetchContactsService:
    """Fetch members from a source and persist them to a durable sink.

    Attributes:
        source: The contact source (e.g. the Parliament API adapter).
        sink: The durable store to persist the records to.
    """

    source: MemberContactSource
    sink: MemberContactSink

    def run(self) -> FetchResult:
        """Fetch all members, persist them, and report what was written."""
        members = self.source.load_members()
        output_path = self.sink.save_members(members)
        contact_count = sum(len(member.contacts) for member in members)
        return FetchResult(
            output_path=output_path,
            member_count=len(members),
            contact_count=contact_count,
        )
