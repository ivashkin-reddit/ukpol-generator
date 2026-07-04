"""Tests for whitelist collection and AutoModerator rule rendering."""

from __future__ import annotations

from ukpol_generator.domain.models import Member, RawContact, WhitelistEntry
from ukpol_generator.domain.rules import collect, render_document, render_rule


def test_collect_deduplicates_shared_account(sample_members: list[Member]) -> None:
    """A Twitter account used by two members becomes one entry with both labels."""
    whitelist = collect(sample_members)
    twitter = whitelist["Twitter"]
    assert set(twitter) == {"/HackneyAbbott"}
    entry = twitter["/HackneyAbbott"]
    assert entry.members == (
        "Ms Diane Abbott | Independent | Hackney North and Stoke Newington",
        "Some Peer | Crossbench | Lords",
    )


def test_collect_groups_by_platform(sample_members: list[Member]) -> None:
    """Accounts are grouped under their platform keys."""
    whitelist = collect(sample_members)
    assert set(whitelist) == {"Twitter", "Facebook"}
    assert set(whitelist["Facebook"]) == {"/shockatadam"}


def test_render_rule_contains_expected_fields(sample_members: list[Member]) -> None:
    """A rendered rule includes the header, whitelist entry, and placeholders."""
    whitelist = collect(sample_members)
    rule = render_rule("Twitter", whitelist["Twitter"])
    assert "# Rule GEN-TWITTER Whitelisted Twitter Accounts" in rule
    assert "        - /HackneyAbbott  # Ms Diane Abbott" in rule
    assert "TWITTER_FLAIR_TEXT_PLACEHOLDER" in rule
    assert "action: report" in rule


def test_render_rule_uses_documented_domain_check(sample_members: list[Member]) -> None:
    """Fixed-host rules gate on the documented plain domain check, not regex."""
    whitelist = collect(sample_members)
    rule = render_rule("Twitter", whitelist["Twitter"])
    assert "    domain: [twitter.com, x.com, mobile.twitter.com]" in rule
    assert "domain (regex)" not in rule


def test_render_rule_sanitizes_collected_member_labels() -> None:
    """Collected member labels stay on one YAML comment line."""
    member = Member(
        id=1,
        name="Name #One\nInjected",
        party="Party\tName",
        house="Commons",
        constituency="Place\rName",
        contacts=(RawContact(type_id=None, line1="https://twitter.com/dirty", website=None),),
    )

    rule = render_rule("Twitter", collect([member])["Twitter"])
    entry_lines = [line for line in rule.splitlines() if "/dirty" in line]

    assert entry_lines == ["        - /dirty  # Name One Injected | Party Name | Place Name"]
    assert entry_lines[0].count("#") == 1
    assert not any(line.startswith("Injected") for line in rule.splitlines())


def test_render_rule_sanitizes_direct_entry_members() -> None:
    """Direct whitelist entries also get one-line safe comments."""
    entries = {
        "/direct": WhitelistEntry(
            url_path="/direct",
            members=("Member #One\nInjected",),
        )
    }

    rule = render_rule("Twitter", entries)
    entry_lines = [line for line in rule.splitlines() if "/direct" in line]

    assert entry_lines == ["        - /direct  # Member One Injected"]
    assert entry_lines[0].count("#") == 1
    assert not any(line.startswith("Injected") for line in rule.splitlines())


def test_render_document_lists_all_platforms(sample_members: list[Member]) -> None:
    """The document header reports platform and account totals."""
    whitelist = collect(sample_members)
    document = render_document(whitelist)
    assert "Platforms: 2" in document
    assert "Total whitelisted accounts: 2" in document
    assert "# Rule GEN-TWITTER" in document
    assert "# Rule GEN-FACEBOOK" in document


def test_render_document_omits_empty_platforms() -> None:
    """Platforms with no whitelisted accounts are not emitted."""
    document = render_document({})
    assert "Platforms: 0" in document
    assert "# Rule GEN-" not in document


def test_render_rule_mastodon_covers_known_instance() -> None:
    """The Mastodon rule's domain gate lists the entries' instance hosts."""
    entries = {
        "mastodonapp.uk/@someone": WhitelistEntry(
            url_path="mastodonapp.uk/@someone",
            members=("A | Party | Place",),
        )
    }
    rule = render_rule("Mastodon", entries)
    assert "    domain: [mastodonapp.uk]" in rule
    assert "domain (regex)" not in rule


def test_render_rule_mastodon_gate_is_sorted_and_deduplicated() -> None:
    """Entries across instances yield a sorted, unique domain gate."""
    entries = {
        "mstdn.io/@b": WhitelistEntry(url_path="mstdn.io/@b", members=("B",)),
        "mastodon.social/@a": WhitelistEntry(url_path="mastodon.social/@a", members=("A",)),
        "mastodon.social/@c": WhitelistEntry(url_path="mastodon.social/@c", members=("C",)),
    }
    rule = render_rule("Mastodon", entries)
    assert "    domain: [mastodon.social, mstdn.io]" in rule


def test_collect_keeps_mastodon_instances_distinct() -> None:
    """The same handle on two instances yields two separate entries."""
    members = [
        Member(
            id=1,
            name="A One",
            party="Party",
            house="Commons",
            constituency="Place",
            contacts=(
                RawContact(type_id=None, line1="https://mastodon.social/@alice", website=None),
            ),
        ),
        Member(
            id=2,
            name="B Two",
            party="Party",
            house="Commons",
            constituency="Elsewhere",
            contacts=(RawContact(type_id=None, line1="https://mstdn.io/@alice", website=None),),
        ),
    ]

    whitelist = collect(members)["Mastodon"]

    assert set(whitelist) == {"mastodon.social/@alice", "mstdn.io/@alice"}
    assert whitelist["mastodon.social/@alice"].members == ("A One | Party | Place",)
    assert whitelist["mstdn.io/@alice"].members == ("B Two | Party | Elsewhere",)
