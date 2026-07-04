"""Platform identification constants used by the parsing domain logic.

Platform identity is derived solely from the URL host: exact platform hosts,
their subdomains, and an explicit allowlist of verified misspelled domains.
The Parliament Members API ``typeId`` field is deliberately not used - it is
unreliable for newer platforms and must never turn an unknown host into a
platform account.
"""

from __future__ import annotations

# Canonical platform name -> tuple of hostnames (without any leading "www."/"m.").
PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "Twitter": ("twitter.com", "x.com", "mobile.twitter.com"),
    "Facebook": ("facebook.com", "fb.com", "fb.me", "fb.watch"),
    "Instagram": ("instagram.com", "instagr.am"),
    "Bluesky": ("bsky.app", "bsky.social"),
    "LinkedIn": ("linkedin.com",),
    "YouTube": ("youtube.com", "youtu.be"),
    "TikTok": ("tiktok.com",),
    "Threads": ("threads.net", "threads.com"),
}

# Misspelled platform domains observed in Parliament's published contact
# data, remapped to their real platform. Deliberately NOT part of
# PLATFORM_HOSTS: these hosts must never appear in the generated rules'
# ``domain`` gate, and ``_build_account`` canonicalises remapped accounts
# onto the real platform host. Only add an entry after manually verifying
# the misspelled domain redirects to the real platform
# (instragram.com -> instagram.com verified 2026-07-04).
TYPO_HOSTS: dict[str, str] = {
    "instragram.com": "Instagram",
}

# Mastodon is instance-based (no single host). A host is treated as a
# Mastodon instance when its FIRST DNS label matches a conventional instance
# name (mastodon.social, mstdn.io, toot.wales, ...) or when it is in the
# exact-host allowlist below. First-label matching replaced the old substring
# hints, which wrongly matched e.g. ``notmastodon.example`` and mid-host
# labels; see plans/004-mastodon-detection-findings.md for the earlier
# ``.social`` history.
MASTODON_LABELS: frozenset[str] = frozenset({"mastodon", "mstdn", "toot"})

# A candidate instance host needs at least two DNS labels (name + TLD), so a
# bare ``mastodon`` host does not match.
_MIN_INSTANCE_LABELS = 2

# Synthetic platform key for instance-based Mastodon accounts.
MASTODON: str = "Mastodon"

# Known Mastodon instance hosts that the prefix hints above do not catch
# (e.g. ``mastodonapp.uk`` — ``mastodon.`` with its trailing dot is not a
# substring of ``mastodonapp``). Matched as exact hosts; extend as needed.
MASTODON_INSTANCES: frozenset[str] = frozenset({"mastodonapp.uk"})

# Order in which platform rules are emitted by the renderer.
PLATFORM_ORDER: tuple[str, ...] = (*PLATFORM_HOSTS.keys(), MASTODON)

# Path segments that are never account handles (platform chrome / reserved words).
RESERVED_SEGMENTS: frozenset[str] = frozenset(
    {
        "",
        "home",
        "share",
        "sharer",
        "sharer.php",
        "intent",
        "hashtag",
        "explore",
        "watch",
        "search",
        "help",
        "about",
        "login",
        "signup",
        "i",
        "pages",
        "p",  # Facebook/Instagram namespace (extracted specially for Facebook)
        "people",  # Facebook namespace (extracted specially for Facebook)
        "profile.php",  # handled specially for Facebook numeric IDs
    }
)


def platform_from_host(host: str) -> str | None:
    """Return the canonical platform for a normalised host, if known.

    A host matches a platform when it equals one of the platform's known
    hosts or is a subdomain of one (dot-anchored, so ``evilfacebook.com``
    does not match). Verified misspelled domains in :data:`TYPO_HOSTS` are
    remapped to their real platform.

    Args:
        host: A host already lower-cased and stripped of any ``www.``/``m.``
            prefix.

    Returns:
        The canonical platform name, ``"Mastodon"`` for a known instance host
        or a host whose first DNS label is a conventional instance name, or
        ``None`` when the host is not a known platform.
    """
    for platform, hosts in PLATFORM_HOSTS.items():
        for candidate in hosts:
            if host == candidate or host.endswith("." + candidate):
                return platform
    typo_platform = TYPO_HOSTS.get(host)
    if typo_platform is not None:
        return typo_platform
    if host in MASTODON_INSTANCES:
        return MASTODON
    labels = host.split(".")
    if len(labels) >= _MIN_INSTANCE_LABELS and labels[0] in MASTODON_LABELS:
        return MASTODON
    return None
