"""Ports for reading and persisting member contact records.

These Protocols let the application services depend on abstract seams rather than
concrete adapters, so the Parliament API, a cached JSON file, or a test double
are all interchangeable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ukpol_generator.domain.models import Member


class ContactSourceError(RuntimeError):
    """Raised when a source cannot produce a complete member data set.

    Part of the :class:`MemberContactSource` contract: callers must treat this
    as "do not use any partial result", so an interrupted fetch can never
    silently shrink the generated whitelist.
    """


@runtime_checkable
class MemberContactSource(Protocol):
    """A source of member contact records (e.g. the API or a cached file)."""

    def load_members(self) -> list[Member]:
        """Return all members with their narrowed contact records.

        Raises:
            ContactSourceError: If the source cannot produce the complete
                member set; implementations must not return partial data.
        """
        ...


@runtime_checkable
class MemberContactSink(Protocol):
    """A durable store that persists fetched member contact records."""

    def save_members(self, members: Sequence[Member]) -> Path:
        """Persist members and return the path written.

        Args:
            members: The members to persist.

        Returns:
            The filesystem path the records were written to.
        """
        ...
