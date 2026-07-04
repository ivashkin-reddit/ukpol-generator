"""Shared pytest fixtures for ukpol_generator tests."""

from __future__ import annotations

import pytest

from ukpol_generator.domain.models import Member, RawContact


def _contact(line1: str) -> RawContact:
    """Build a URL-only contact record for fixtures."""
    return RawContact(type_id=None, line1=line1, website=None)


@pytest.fixture
def sample_members() -> list[Member]:
    """Two members, one Twitter account shared between them, plus a Facebook one."""
    return [
        Member(
            id=1,
            name="Ms Diane Abbott",
            party="Independent",
            house="Commons",
            constituency="Hackney North and Stoke Newington",
            contacts=(
                _contact("https://twitter.com/HackneyAbbott"),
                _contact("https://www.facebook.com/shockatadam"),
            ),
        ),
        Member(
            id=2,
            name="Some Peer",
            party="Crossbench",
            house="Lords",
            constituency=None,
            contacts=(_contact("https://x.com/HackneyAbbott/"),),
        ),
    ]
