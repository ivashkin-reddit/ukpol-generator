"""Render drop-in AutoModerator whitelist rules from parsed social accounts.

Each generated rule mirrors the existing "Rule K-01 Whitelisted Twitter
Accounts": it reports any link submission to a platform whose account is *not*
in the whitelist of known MP/Lord accounts. All functions here are pure; the
caller is responsible for reading input and writing the rendered document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ukpol_generator.domain.models import Member, WhitelistEntry
from ukpol_generator.domain.parsing import parse_contact
from ukpol_generator.domain.platforms import (
    MASTODON,
    PLATFORM_HOSTS,
    PLATFORM_ORDER,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# platform -> {url_path -> WhitelistEntry}
PlatformWhitelist = dict[str, dict[str, WhitelistEntry]]
_ASCII_CONTROL_LIMIT = 32


def _comment_text(value: str) -> str:
    """Return text safe to place after an inline YAML comment marker."""
    cleaned = "".join(
        " " if character == "#" or ord(character) < _ASCII_CONTROL_LIMIT else character
        for character in value
    )
    return " ".join(cleaned.split())


def _member_part(value: str, fallback: str) -> str:
    """Return a sanitized member label part, falling back when it is blank."""
    return _comment_text(value) or fallback


def _member_label(member: Member) -> str:
    """Format a member as ``Name | Party | Constituency-or-House`` for a comment.

    Comment-breaking characters are normalized so the label is safe inside an
    inline YAML comment.
    """
    name = _member_part(member.name, "Unknown")
    party = _member_part(member.party, "Unknown")
    where = _comment_text(member.constituency or member.house or "")
    parts = [name, party]
    if where:
        parts.append(where)
    return " | ".join(parts)


def _collect_member(member: Member, labels: dict[str, dict[str, list[str]]]) -> None:
    """Accumulate one member's social accounts into the shared label index.

    Args:
        member: The member whose contacts are parsed.
        labels: Mutable ``platform -> url_path -> [member labels]`` index that is
            updated in place. Duplicate ``(platform, url_path)`` pairs for the
            same member are collapsed, and each label is added at most once.
    """
    label = _member_label(member)
    seen: set[tuple[str, str]] = set()
    for contact in member.contacts:
        account = parse_contact(contact)
        if account is None:
            continue
        key = (account.platform, account.url_path)
        if key in seen:
            continue
        seen.add(key)
        members_for_path = labels.setdefault(account.platform, {}).setdefault(account.url_path, [])
        if label not in members_for_path:
            members_for_path.append(label)


def _freeze(labels: dict[str, dict[str, list[str]]]) -> PlatformWhitelist:
    """Convert the mutable label index into immutable whitelist entries."""
    return {
        platform: {
            url_path: WhitelistEntry(url_path=url_path, members=tuple(members))
            for url_path, members in entries.items()
        }
        for platform, entries in labels.items()
    }


def collect(members: Sequence[Member]) -> PlatformWhitelist:
    """Parse all members and group whitelist entries by platform.

    Args:
        members: The members to parse.

    Returns:
        A mapping ``platform -> {url_path -> WhitelistEntry}``, deduplicated by
        ``(platform, url_path)`` with all member labels merged onto the shared
        entry.
    """
    labels: dict[str, dict[str, list[str]]] = {}
    for member in members:
        _collect_member(member, labels)
    return _freeze(labels)


def _domain_list(platform: str, entries: dict[str, WhitelistEntry]) -> list[str]:
    """Build the plain ``domain`` check values for a platform's rule.

    Emits the documented ``domain`` check (exact domain or subdomain) instead
    of ``domain (regex)``, whose match placement AutoModerator does not
    document. For Mastodon - which has no fixed host - the gate lists the
    instance hosts present in the whitelist entries themselves (fragments are
    ``host/@handle``), so the rule examines exactly the instances that host a
    whitelisted account.
    """
    if platform == MASTODON:
        return sorted({url_path.split("/", 1)[0] for url_path in entries})
    return list(PLATFORM_HOSTS.get(platform, ()))


def _render_entry_lines(entries: dict[str, WhitelistEntry]) -> list[str]:
    """Render the whitelisted ``url_path`` lines with their member comments."""
    lines: list[str] = []
    for url_path in sorted(entries, key=str.lower):
        comment = "; ".join(
            _comment_text(member) or "Unknown" for member in entries[url_path].members
        )
        lines.append(f"        - {url_path}  # {comment}")
    return lines


def render_rule(platform: str, entries: dict[str, WhitelistEntry]) -> str:
    """Render a single K-01-style whitelist rule for one platform.

    Args:
        platform: The canonical platform name.
        entries: The whitelisted accounts for that platform.

    Returns:
        The rule as a YAML fragment. ``set_flair`` values are deliberate
        placeholders meant to be replaced during manual review.
    """
    slug = platform.upper()
    domain_str = ", ".join(_domain_list(platform, entries))
    lines = [
        f"    # Rule GEN-{slug} Whitelisted {platform} Accounts "
        f"({len(entries)} accounts, auto-generated)",
        "    moderators_exempt: false",
        "    type: link submission",
        f"    domain: [{domain_str}]",
        "    ~domain+url (includes):",
    ]
    lines.extend(_render_entry_lines(entries))
    lines.extend(
        [
            "",
            f"    action_reason: {platform} Account Review - "
            f"Non-Whitelisted {platform} account (rUKPolitics - Rule GEN-{slug})",
            "    action: report",
            "    set_flair:",
            f'        text: "{slug}_FLAIR_TEXT_PLACEHOLDER"',
            f'        css_class: "{platform.lower()}_flair_css_placeholder"',
            f'        template_id: "REPLACE_ME_{slug}_TEMPLATE_ID"',
        ]
    )
    return "\n".join(lines)


def _document_header(by_platform: PlatformWhitelist) -> list[str]:
    """Build the explanatory comment header for the generated document."""
    total_accounts = sum(len(entries) for entries in by_platform.values())
    return [
        "# =====================================================================",
        "# AUTO-GENERATED social-media whitelist rules for r/ukpolitics AutoMod.",
        "#",
        "# Generated by ukpol-generator from the UK Parliament Members API.",
        "# DO NOT edit by hand - regenerate instead. This is a DROP-IN file; it is",
        "# not wired into ukpolitics-automod.yaml. Review, replace the placeholder",
        "# set_flair values, then paste the rules you want into the main config.",
        "#",
        "# Each rule REPORTS (flags for review) any link submission to the platform",
        "# whose account is NOT in the whitelist below (mirrors Rule K-01).",
        "#",
        f"# Platforms: {len(by_platform)}   Total whitelisted accounts: {total_accounts}",
        "# =====================================================================",
        "",
    ]


def render_document(by_platform: PlatformWhitelist) -> str:
    """Render the full drop-in YAML document for all platforms.

    Args:
        by_platform: The whitelist produced by :func:`collect`.

    Returns:
        The complete YAML document, with platforms emitted in
        :data:`PLATFORM_ORDER` and separated by ``---`` document markers.
    """
    blocks: list[str] = []
    for platform in PLATFORM_ORDER:
        entries = by_platform.get(platform)
        if not entries:
            continue
        blocks.append(render_rule(platform, entries))

    header = "\n".join(_document_header(by_platform))
    return header + "\n---\n\n".join(f"{block}\n" for block in blocks)
