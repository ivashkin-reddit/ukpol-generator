"""Tests for social-media URL parsing and normalisation."""

from __future__ import annotations

import pytest

from ukpol_generator.domain.models import RawContact
from ukpol_generator.domain.parsing import parse_contact, parse_url


@pytest.mark.parametrize(
    ("value", "expected_platform", "expected_path"),
    [
        ("https://twitter.com/HackneyAbbott", "Twitter", "/HackneyAbbott"),
        ("https://x.com/HackneyAbbott/", "Twitter", "/HackneyAbbott"),
        # An explicit port does not change host identity.
        ("https://twitter.com:443/HackneyAbbott", "Twitter", "/HackneyAbbott"),
        ("https://www.facebook.com/shockatadam", "Facebook", "/shockatadam"),
        # Facebook's /@handle vanity form (two sitting MPs use it): the handle
        # loses the @, but the published @ form stays in the match fragment.
        ("https://www.facebook.com/@LolaMcEvoyMP/", "Facebook", "/@LolaMcEvoyMP"),
        (
            "https://www.facebook.com/@charliemaynardliberaldemocrat",
            "Facebook",
            "/@charliemaynardliberaldemocrat",
        ),
        # Facebook's /p/<slug> and /people/<name>/<id> page namespaces: the
        # first segment is chrome; identity is the slug (plus numeric id).
        (
            "https://www.facebook.com/p/Alex-Baker-for-Aldershot-Farnborough-61554920172107/",
            "Facebook",
            "/p/Alex-Baker-for-Aldershot-Farnborough-61554920172107",
        ),
        (
            "https://www.facebook.com/people/Matt-Bishop-MP/100087163714748/",
            "Facebook",
            "/people/Matt-Bishop-MP/100087163714748",
        ),
        # A trailing chrome segment after a vanity handle stays ignored.
        (
            "https://www.facebook.com/AndrewCooperForMidCheshire/about/",
            "Facebook",
            "/AndrewCooperForMidCheshire",
        ),
        # Subdomains of platform hosts belong to the platform (dot-anchored).
        (
            "https://en-gb.facebook.com/LordAltonofLiverpool/",
            "Facebook",
            "/LordAltonofLiverpool",
        ),
        ("https://uk.linkedin.com/in/lolamcevoy", "LinkedIn", "/in/lolamcevoy"),
        # A verified misspelled platform domain is remapped (see TYPO_HOSTS).
        ("https://www.instragram.com/chriswkane", "Instagram", "/chriswkane"),
        ("https://www.instagram.com/shockatadam/", "Instagram", "/shockatadam"),
        ("http://twitter.com/lukeakehurstmp?ref_src=abc", "Twitter", "/lukeakehurstmp"),
        ("facebook.com/borisjohnson/", "Facebook", "/borisjohnson"),
        (
            "https://www.facebook.com/profile.php?id=100064000000000",
            "Facebook",
            "/profile.php?id=100064000000000",
        ),
        (
            "https://bsky.app/profile/someone.bsky.social",
            "Bluesky",
            "/profile/someone.bsky.social",
        ),
        ("https://www.linkedin.com/in/some-mp-12345/", "LinkedIn", "/in/some-mp-12345"),
        ("https://www.youtube.com/@SomeChannel", "YouTube", "/@SomeChannel"),
        ("https://youtube.com/channel/UC1234567890", "YouTube", "/channel/UC1234567890"),
        ("https://www.tiktok.com/@someone", "TikTok", "/@someone"),
        ("https://www.threads.net/@someone", "Threads", "/@someone"),
        # Mastodon identity is per-instance, so the match fragment is
        # host-qualified rather than a bare path.
        ("https://mastodon.social/@someone", "Mastodon", "mastodon.social/@someone"),
        # A real instance on a bespoke .social host is still detected via the
        # ``mstdn`` first label, not the (long removed) bare ``.social`` substring.
        ("https://mstdn.social/@someone", "Mastodon", "mstdn.social/@someone"),
        ("https://toot.wales/@someone", "Mastodon", "toot.wales/@someone"),
        # A known instance host that no prefix hint catches (mastodon. needs a
        # trailing dot) is detected via the explicit instance allowlist.
        (
            "https://mastodonapp.uk/@PeterLambForCrawley",
            "Mastodon",
            "mastodonapp.uk/@PeterLambForCrawley",
        ),
    ],
)
def test_parse_url_recognises_accounts(
    value: str, expected_platform: str, expected_path: str
) -> None:
    """Recognised profile URLs yield the expected platform and match path."""
    account = parse_url(value)
    assert account is not None
    assert account.platform == expected_platform
    assert account.url_path == expected_path


@pytest.mark.parametrize(
    "value",
    [
        "http://www.dianeabbott.org.uk",
        "mailto:someone@parliament.uk",
        "https://twitter.com/",
        "https://www.facebook.com/profile.php?id=not-a-number",
        # A non-Mastodon site on a .social domain is no longer a false positive.
        "https://not-mastodon-at-all.social/@someone",
        # Instance names match as the FIRST DNS label only - not as a
        # substring and not mid-host.
        "https://nonmastodon.com/@someone",
        "https://notmastodon.example/@someone",
        "https://social.mastodon.example/@someone",
        # Subdomain matching is dot-anchored and matches real subdomains only.
        "https://evilfacebook.com/someone",
        "https://facebook.com.evil.example/someone",
        # Credentialed URLs are rejected; userinfo is a spoofing shape (the
        # last case really points at evil.example, not Twitter).
        "https://user@twitter.com/handle",
        "https://user:secret@twitter.com/handle",
        "https://twitter.com@evil.example/handle",
        # Incomplete Facebook namespace pages are rejected rather than
        # guessed at, and Instagram's /p/ namespace is a post, not a profile.
        "https://www.facebook.com/p/",
        "https://www.facebook.com/people/Some-Name/",
        "https://www.facebook.com/people/Some-Name/not-a-number",
        "https://www.instagram.com/p/AbC123xyz/",
        "",
        "   ",
    ],
)
def test_parse_url_rejects_non_accounts(value: str) -> None:
    """Non-social URLs and handle-less URLs return None."""
    assert parse_url(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "https://www.tiktok.com/foryou",
        "https://www.tiktok.com/tag/politics",
        "https://www.threads.net/someone",
        "https://mastodon.social/users/someone",
    ],
)
def test_parse_url_rejects_at_platform_paths_without_at_prefix(value: str) -> None:
    """At-namespace platforms require an @handle path segment."""
    assert parse_url(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "javascript://twitter.com/evil",
        "ftp://twitter.com/evil",
        "file://twitter.com/evil",
    ],
)
def test_parse_url_rejects_non_http_schemes_with_social_hosts(value: str) -> None:
    """Only web URLs are treated as social-media profile URLs."""
    assert parse_url(value) is None


@pytest.mark.parametrize(
    "value",
    [
        # An empty handle would render as a `- /` whitelist line, which makes
        # the platform's negated substring check never match - silently
        # disabling the entire rule.
        "https://x.com/@",
        "https://twitter.com/@/",
        "https://www.youtube.com/@",
        "https://www.facebook.com/@",
        # Characters that are unsafe inside an unquoted YAML scalar.
        "https://x.com/foo:bar",
        "https://x.com/foo bar",
        "https://x.com/foo'bar",
    ],
)
def test_parse_url_rejects_empty_and_unsafe_handles(value: str) -> None:
    """Empty handles and YAML-unsafe handle characters are rejected."""
    assert parse_url(value) is None


def test_parse_url_rejects_unknown_host() -> None:
    """An unknown host is never treated as a social platform."""
    assert parse_url("https://unknown.example/someone") is None


def test_typo_domain_remap_canonicalises_to_real_host() -> None:
    """A verified misspelled platform domain maps to the real platform."""
    account = parse_url("https://www.instragram.com/chriswkane")
    assert account is not None
    assert account.platform == "Instagram"
    assert account.canonical_url == "https://instagram.com/chriswkane"


def test_parse_contact_prefers_line1_over_website() -> None:
    """parse_contact reads line1 before falling back to website."""
    contact = RawContact(
        type_id=None,
        line1="https://twitter.com/primary",
        website="https://twitter.com/secondary",
    )
    account = parse_contact(contact)
    assert account is not None
    assert account.url_path == "/primary"


def test_parse_contact_falls_back_to_website() -> None:
    """parse_contact uses website when line1 is not a social account."""
    contact = RawContact(
        type_id=None,
        line1="mailto:someone@parliament.uk",
        website="https://twitter.com/fallback",
    )
    account = parse_contact(contact)
    assert account is not None
    assert account.url_path == "/fallback"


def test_parse_contact_ignores_type_id_for_unknown_host() -> None:
    """A type id can no longer turn an unknown host into a platform account."""
    contact = RawContact(type_id=7, line1="https://unknown.example/someone", website=None)
    assert parse_contact(contact) is None
