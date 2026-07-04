"""Typed domain models for the social-media rule pipeline.

These value objects are the internal representation the domain works with. The
loosely typed JSON returned by the Parliament Members API is narrowed into these
models at the adapter boundary so that no ``dict[str, object]`` payloads flow
through the domain or application layers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawContact:
    """A single contact record narrowed to the fields the parser needs.

    Attributes:
        type_id: The API ``typeId`` used only as a platform hint when the URL
            host is ambiguous. ``None`` when absent or non-integer.
        line1: The primary URL/value field for web contacts.
        website: A secondary URL field checked when ``line1`` yields no account.
    """

    type_id: int | None
    line1: str | None
    website: str | None


@dataclass(frozen=True)
class Member:
    """A current MP or Lord together with their raw contact records.

    Attributes:
        id: The Parliament member identifier.
        name: Display name as returned by the API.
        party: Latest party name, or ``"Unknown"`` when unavailable.
        house: ``"Commons"`` or ``"Lords"``.
        constituency: Constituency (Commons) or ``None`` for Lords.
        contacts: The member's narrowed contact records.
    """

    id: int
    name: str
    party: str
    house: str
    constituency: str | None
    contacts: tuple[RawContact, ...]


@dataclass(frozen=True)
class SocialAccount:
    """A normalised social-media account extracted from a contact record.

    Attributes:
        platform: Canonical platform name (e.g. ``"Twitter"``).
        handle: The bare account identifier with no leading ``@`` or path.
        url_path: The AutoModerator ``domain+url (includes)`` match fragment,
            always beginning with ``/``.
        canonical_url: A canonical ``https://`` URL for the account.
        raw: The original raw value the account was parsed from.
    """

    platform: str
    handle: str
    url_path: str
    canonical_url: str
    raw: str


@dataclass(frozen=True)
class WhitelistEntry:
    """One whitelist entry: an account path plus the members who use it.

    Attributes:
        url_path: The AutoModerator match fragment for the account.
        members: Human-readable member labels sharing this account.
    """

    url_path: str
    members: tuple[str, ...]
