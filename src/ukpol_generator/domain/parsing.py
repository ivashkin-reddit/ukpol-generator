"""Robust parsing and normalisation of social-media contact values.

Every value is parsed with :mod:`urllib.parse` and the platform is identified
solely from the URL host (exact hosts, their subdomains, and verified typo
domains). Per-platform handlers turn the URL path into the AutoModerator match
fragment (``url_path``) and a bare ``handle``. All functions here are pure and
free of I/O.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ukpol_generator.domain.models import RawContact, SocialAccount
from ukpol_generator.domain.platforms import (
    MASTODON,
    PLATFORM_HOSTS,
    RESERVED_SEGMENTS,
    platform_from_host,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from urllib.parse import ParseResult

# Minimum path segments required for platforms that nest the handle under a
# sub-path (e.g. ``/profile/<handle>``, ``/in/<handle>``).
_MIN_HANDLE_SEGMENTS = 2
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Conservative handle charset: covers every real handle in the live dump
# (letters, digits, dot, underscore, hyphen). Anything outside it is either
# malformed or would need YAML quoting downstream - reject at the boundary.
_HANDLE_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


def _normalise_host(host: str) -> str:
    """Strip a leading ``www.``/``m.`` label from an already-parsed hostname.

    ``urlparse(...).hostname`` is already lower-case with port and userinfo
    removed; the lowering here is defensive idempotence.
    """
    host = host.lower().strip()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def _host_of(parsed: ParseResult) -> str | None:
    """Extract the normalised hostname, rejecting credentialed URLs.

    ``hostname`` (not ``netloc``) strips any port and userinfo, so
    ``https://twitter.com:443/x`` resolves to ``twitter.com``. URLs carrying
    userinfo are rejected outright: published contact URLs never legitimately
    contain credentials, and ``https://real.host@evil.example`` is a spoofing
    shape.
    """
    if parsed.username is not None or parsed.password is not None:
        return None
    return _normalise_host(parsed.hostname or "")


def _ensure_url(value: str) -> str:
    """Ensure a value is parseable as a URL.

    Bare values such as ``twitter.com/foo`` (no scheme) are given an
    ``https://`` scheme so :func:`urllib.parse.urlparse` populates ``netloc``.

    Args:
        value: The raw URL or host/path string.

    Returns:
        A URL string guaranteed to contain a scheme.
    """
    value = value.strip()
    if "://" not in value:
        return "https://" + value
    return value


def _clean_segments(path: str) -> list[str]:
    """Split a URL path into non-empty segments."""
    return [seg for seg in path.split("/") if seg]


# Facebook /people/<name>/<numeric id> needs all three segments.
_FACEBOOK_PEOPLE_SEGMENTS = 3


def _facebook_namespace(segments: list[str]) -> tuple[str, str] | None:
    """Resolve Facebook's ``/p/<slug>`` and ``/people/<name>/<id>`` page shapes.

    These are namespace URLs: the first segment is chrome, not a handle.
    Incomplete forms (a bare ``/p/``, or ``/people/<name>`` without the
    numeric profile id) are rejected rather than guessed at.
    """
    first = segments[0].lower()
    if first == "p" and len(segments) >= _MIN_HANDLE_SEGMENTS:
        return segments[1], f"/p/{segments[1]}"
    if first == "people" and len(segments) >= _FACEBOOK_PEOPLE_SEGMENTS and segments[2].isdigit():
        return segments[1], f"/people/{segments[1]}/{segments[2]}"
    return None


def _handle_facebook(segments: list[str]) -> tuple[str, str] | None:
    """Resolve a Facebook vanity path, ``/@handle``, or a namespace page shape.

    Numeric ``profile.php`` IDs are handled separately, ``/p/...`` and
    ``/people/...`` namespace pages via :func:`_facebook_namespace`. The
    published ``@`` form is preserved in the match fragment because
    submissions link it.
    """
    first = segments[0]
    if first.lower() in ("p", "people"):
        return _facebook_namespace(segments)
    handle = first[1:] if first.startswith("@") else first
    if handle.lower() in RESERVED_SEGMENTS:
        return None
    return handle, f"/{first}"


def _handle_bluesky(segments: list[str]) -> tuple[str, str] | None:
    """Resolve ``bsky.app/profile/<handle>``."""
    if segments[0].lower() == "profile" and len(segments) >= _MIN_HANDLE_SEGMENTS:
        handle = segments[1]
        return handle, f"/profile/{handle}"
    return None


def _handle_linkedin(segments: list[str]) -> tuple[str, str] | None:
    """Resolve ``linkedin.com/{in,company,school}/<handle>``."""
    first = segments[0].lower()
    if first in ("in", "company", "school") and len(segments) >= _MIN_HANDLE_SEGMENTS:
        handle = segments[1]
        return handle, f"/{first}/{handle}"
    return None


def _handle_youtube(segments: list[str]) -> tuple[str, str] | None:
    """Resolve YouTube ``@handle``, ``channel/``, ``c/``, ``user/`` or vanity."""
    first = segments[0]
    low = first.lower()
    if first.startswith("@"):
        return first[1:], f"/{first}"
    if low in ("channel", "c", "user") and len(segments) >= _MIN_HANDLE_SEGMENTS:
        handle = segments[1]
        return handle, f"/{low}/{handle}"
    if low in RESERVED_SEGMENTS:
        return None
    return first, f"/{first}"


def _handle_at_prefixed(segments: list[str]) -> tuple[str, str] | None:
    """Resolve platforms whose profiles are ``/@handle`` (TikTok, Threads, Mastodon)."""
    first = segments[0]
    if not first.startswith("@"):
        return None
    handle = first[1:]
    if handle.lower() in RESERVED_SEGMENTS:
        return None
    return handle, f"/@{handle}"


def _handle_flat(segments: list[str]) -> tuple[str, str] | None:
    """Resolve a flat-namespace profile (Twitter, Instagram, and the default)."""
    first = segments[0]
    if first.lower() in RESERVED_SEGMENTS:
        return None
    handle = first[1:] if first.startswith("@") else first
    return handle, f"/{handle}"


# A handler maps the path segments of a profile URL to (handle, url_path).
_HANDLERS: dict[str, Callable[[list[str]], tuple[str, str] | None]] = {
    "Facebook": _handle_facebook,
    "Bluesky": _handle_bluesky,
    "LinkedIn": _handle_linkedin,
    "YouTube": _handle_youtube,
    "TikTok": _handle_at_prefixed,
    "Threads": _handle_at_prefixed,
    MASTODON: _handle_at_prefixed,
}


def _resolve_handle(platform: str, segments: list[str]) -> tuple[str, str] | None:
    """Dispatch to the platform handler and validate the resulting handle.

    Rejects empty handles (which would render as a rule-disabling ``- /``
    whitelist line) and handles containing characters that are unsafe inside
    an unquoted YAML scalar.
    """
    result = _HANDLERS.get(platform, _handle_flat)(segments)
    if result is None:
        return None
    handle, _url_path = result
    if _HANDLE_PATTERN.fullmatch(handle) is None:
        return None
    return result


def _is_facebook_numeric_case(segments: list[str]) -> bool:
    """Return whether a Facebook URL points at a numeric ``profile.php`` ID."""
    return not segments or segments[0].lower() == "profile.php"


def _facebook_numeric_account(query: str, raw: str) -> SocialAccount | None:
    """Build a Facebook account from a ``profile.php?id=<digits>`` query string."""
    for part in query.split("&"):
        if part.lower().startswith("id="):
            fb_id = part.split("=", 1)[1]
            if fb_id.isdigit():
                return SocialAccount(
                    platform="Facebook",
                    handle=fb_id,
                    url_path=f"/profile.php?id={fb_id}",
                    canonical_url=f"https://www.facebook.com/profile.php?id={fb_id}",
                    raw=raw,
                )
    return None


def _build_account(
    platform: str,
    handle: str,
    url_path: str,
    host: str,
    raw: str,
) -> SocialAccount:
    """Assemble a :class:`SocialAccount` with a canonical URL for the platform.

    Mastodon identity is per-instance, so its whitelist fragment is
    host-qualified (``instance.tld/@handle``); every other platform keeps a
    path-only fragment under its canonical host.
    """
    if platform == MASTODON:
        return SocialAccount(
            platform=platform,
            handle=handle,
            url_path=f"{host}{url_path}",
            canonical_url=f"https://{host}{url_path}",
            raw=raw,
        )
    canonical_host = PLATFORM_HOSTS.get(platform, (host,))[0]
    return SocialAccount(
        platform=platform,
        handle=handle,
        url_path=url_path,
        canonical_url=f"https://{canonical_host}{url_path}",
        raw=raw,
    )


def _prepare(value: str) -> tuple[str, ParseResult, str, str] | None:
    """Validate a value and resolve its platform, parse result, host and raw form.

    Returns:
        A ``(platform, parsed, host, raw)`` tuple, or ``None`` when the value is
        empty, has no host, or belongs to no known platform.
    """
    if not value or not value.strip():
        return None
    raw = value.strip()
    parsed = urlparse(_ensure_url(raw))
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    host = _host_of(parsed)
    if not host:
        return None
    platform = platform_from_host(host)
    if platform is None:
        return None
    return platform, parsed, host, raw


def parse_url(value: str) -> SocialAccount | None:
    """Parse a single URL/value into a :class:`SocialAccount`.

    Args:
        value: The raw URL or host/path string (e.g. a contact's ``line1``).

    Returns:
        The normalised account, or ``None`` if the value is not a recognised
        social-media profile URL.
    """
    prepared = _prepare(value)
    if prepared is None:
        return None

    platform, parsed, host, raw = prepared
    segments = _clean_segments(parsed.path)
    if platform == "Facebook" and _is_facebook_numeric_case(segments):
        return _facebook_numeric_account(parsed.query, raw)
    if not segments:
        return None

    result = _resolve_handle(platform, segments)
    if result is None:
        return None

    handle, url_path = result
    return _build_account(platform, handle, url_path, host, raw)


def parse_contact(contact: RawContact) -> SocialAccount | None:
    """Parse a narrowed contact record into a :class:`SocialAccount`.

    The URL is taken from ``line1`` (the API convention for web contacts),
    falling back to ``website``. Platform identity comes solely from the URL
    host; ``type_id`` is deliberately not consulted, so an unknown host can
    never become a platform account.

    Args:
        contact: The narrowed contact record.

    Returns:
        The normalised account, or ``None`` if the contact is not a
        social-media account.
    """
    for value in (contact.line1, contact.website):
        if value is not None and value.strip():
            account = parse_url(value)
            if account is not None:
                return account
    return None
