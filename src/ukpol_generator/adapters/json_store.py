"""JSON file adapter that both caches and reloads raw member contact records.

Implements :class:`MemberContactSource` (reload a cached dump) and
:class:`MemberContactSink` (persist a freshly fetched dump). Keeping the raw
records on disk makes the fetch step (which hits the network) independent from
the offline rule-generation step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ukpol_generator.adapters.json_narrowing import (
    coerce_int,
    coerce_str,
    mapping_get,
    sequence,
)
from ukpol_generator.domain.models import Member, RawContact

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _contact_to_dict(contact: RawContact) -> dict[str, object]:
    """Serialise a contact record to a JSON-friendly dict."""
    return {
        "typeId": contact.type_id,
        "line1": contact.line1,
        "website": contact.website,
    }


def _member_to_dict(member: Member) -> dict[str, object]:
    """Serialise a member and its contacts to a JSON-friendly dict."""
    return {
        "id": member.id,
        "name": member.name,
        "party": member.party,
        "house": member.house,
        "constituency": member.constituency,
        "contacts": [_contact_to_dict(contact) for contact in member.contacts],
    }


def _contact_from_obj(item: object) -> RawContact:
    """Narrow a serialised contact object back into a :class:`RawContact`."""
    return RawContact(
        type_id=coerce_int(mapping_get(item, "typeId")),
        line1=coerce_str(mapping_get(item, "line1")),
        website=coerce_str(mapping_get(item, "website")),
    )


def _member_from_obj(item: object) -> Member | None:
    """Narrow a serialised member object back into a :class:`Member`.

    Returns:
        The member, or ``None`` when the record has no integer ``id``.
    """
    member_id = coerce_int(mapping_get(item, "id"))
    if member_id is None:
        return None
    contacts = tuple(
        _contact_from_obj(contact) for contact in sequence(mapping_get(item, "contacts"))
    )
    return Member(
        id=member_id,
        name=coerce_str(mapping_get(item, "name")) or "Unknown",
        party=coerce_str(mapping_get(item, "party")) or "Unknown",
        house=coerce_str(mapping_get(item, "house")) or "Unknown",
        constituency=coerce_str(mapping_get(item, "constituency")),
        contacts=contacts,
    )


@dataclass(frozen=True)
class JsonContactStore:
    """Read and write the raw member contact dump at ``path``.

    Attributes:
        path: The JSON file used as the durable source of truth.
    """

    path: Path

    def save_members(self, members: Sequence[Member]) -> Path:
        """Persist members atomically, creating parent directories.

        The payload is written to a sibling temporary file which then
        replaces the target via ``Path.replace`` (atomic same-directory
        rename), so an interrupted save can never truncate or corrupt a
        previously saved cache. Durability against OS-level write-back loss
        (``fsync``) is deliberately not attempted: the data is refetchable.
        """
        payload = [_member_to_dict(member) for member in members]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(self.path.name + ".tmp")
        _ = temp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _ = temp_path.replace(self.path)
        return self.path

    def load_members(self) -> list[Member]:
        """Load members from the JSON dump, skipping records without an ``id``."""
        decoded: object = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(decoded, list):
            message = "Cached contacts JSON must be a list of member records."
            raise TypeError(message)
        items = cast("list[object]", decoded)
        return [member for item in items if (member := _member_from_obj(item)) is not None]
