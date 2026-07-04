"""Tests for narrowing loosely typed API JSON into typed domain models."""

from __future__ import annotations

import pytest
import requests

from ukpol_generator.adapters.parliament_api import (
    ParliamentApiContactSource,
    member_summary,
    raw_contact,
)
from ukpol_generator.ports.contacts import ContactSourceError


def test_member_summary_narrows_search_item() -> None:
    """A well-formed search item is narrowed into a member summary."""
    item: object = {
        "value": {
            "id": 172,
            "nameDisplayAs": "Ms Diane Abbott",
            "latestParty": {"name": "Independent"},
            "latestHouseMembership": {"membershipFrom": "Hackney North and Stoke Newington"},
        }
    }
    summary = member_summary(item, "Commons")
    assert summary is not None
    assert summary.id == 172
    assert summary.name == "Ms Diane Abbott"
    assert summary.party == "Independent"
    assert summary.house == "Commons"
    assert summary.constituency == "Hackney North and Stoke Newington"


def test_member_summary_defaults_missing_fields() -> None:
    """Missing name/party fields fall back to 'Unknown'."""
    summary = member_summary({"value": {"id": 5}}, "Lords")
    assert summary is not None
    assert summary.name == "Unknown"
    assert summary.party == "Unknown"
    assert summary.constituency is None


def test_member_summary_requires_integer_id() -> None:
    """An item without an integer id aborts the fetch instead of vanishing."""
    with pytest.raises(ContactSourceError, match="no integer id"):
        _ = member_summary({"value": {"id": "abc"}}, "Commons")
    with pytest.raises(ContactSourceError, match="no integer id"):
        _ = member_summary({}, "Commons")


def test_raw_contact_narrows_fields() -> None:
    """A raw contact object is narrowed to type id and URL fields."""
    contact = raw_contact({"typeId": 7, "line1": "https://twitter.com/foo", "website": None})
    assert contact.type_id == 7
    assert contact.line1 == "https://twitter.com/foo"
    assert contact.website is None


def test_raw_contact_rejects_boolean_type_id() -> None:
    """A boolean typeId is not treated as an integer hint."""
    contact = raw_contact({"typeId": True, "line1": "x"})
    assert contact.type_id is None


def _search_page(members: list[dict[str, object]], total: object) -> dict[str, object]:
    """Build a Members/Search page payload (omit total by passing None)."""
    page: dict[str, object] = {"items": [{"value": m} for m in members]}
    if total is not None:
        page["totalResults"] = total
    return page


def _member_value(member_id: int, name: str) -> dict[str, object]:
    """Build the inner ``value`` object for one search item."""
    return {
        "id": member_id,
        "nameDisplayAs": name,
        "latestParty": {"name": "Independent"},
        "latestHouseMembership": {"membershipFrom": "Somewhere"},
    }


def _contacts_payload(line1: str) -> dict[str, object]:
    """Build a Members/{id}/Contact payload with one web contact."""
    return {"value": [{"typeId": None, "line1": line1, "website": None}]}


def _install_fake_api(
    monkeypatch: pytest.MonkeyPatch,
    search_pages: list[dict[str, object]],
    contacts_by_id: dict[int, dict[str, object]],
    error_ids: set[int],
) -> None:
    """Replace ParliamentApiContactSource._get_json with an offline fake."""
    pages = iter(search_pages)

    def fake_get_json(
        _self: ParliamentApiContactSource,
        _session: requests.Session,
        url: str,
        _params: dict[str, str | int | bool] | None = None,
    ) -> object:
        if "/Members/Search" in url:
            return next(pages)
        member_id = int(url.rstrip("/").split("/")[-2])
        if member_id in error_ids:
            message = "boom"
            raise requests.Timeout(message)
        return contacts_by_id.get(member_id, {"value": []})

    monkeypatch.setattr(ParliamentApiContactSource, "_get_json", fake_get_json)


def _api() -> ParliamentApiContactSource:
    """A single-house, page-size-1, non-sleeping adapter for tests."""
    return ParliamentApiContactSource(page_size=1, houses=("Commons",), sleep=lambda _seconds: None)


def test_load_members_paginates_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Members spread across multiple search pages are all returned."""
    _install_fake_api(
        monkeypatch,
        search_pages=[
            _search_page([_member_value(1, "One")], total=2),
            _search_page([_member_value(2, "Two")], total=2),
        ],
        contacts_by_id={
            1: _contacts_payload("https://twitter.com/one"),
            2: _contacts_payload("https://twitter.com/two"),
        },
        error_ids=set(),
    )
    members = _api().load_members()
    assert [m.id for m in members] == [1, 2]
    assert members[0].contacts[0].line1 == "https://twitter.com/one"


def test_load_members_paginates_when_total_results_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent totalResults must not stop paging after the first page."""
    _install_fake_api(
        monkeypatch,
        search_pages=[
            _search_page([_member_value(1, "One")], total=None),
            _search_page([_member_value(2, "Two")], total=None),
            _search_page([], total=None),
        ],
        contacts_by_id={},
        error_ids=set(),
    )
    members = _api().load_members()
    assert [m.id for m in members] == [1, 2]


def test_load_members_raises_after_exhausted_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member whose contact fetch keeps failing aborts the whole fetch."""
    _install_fake_api(
        monkeypatch,
        search_pages=[_search_page([_member_value(1, "One")], total=1)],
        contacts_by_id={},
        error_ids={1},
    )
    with pytest.raises(ContactSourceError, match="after 3 attempts"):
        _ = _api().load_members()


def test_load_members_retries_transient_contact_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contact fetch that fails twice then succeeds recovers with backoff."""
    fail_times = {1: 2}

    def fake_get_json(
        _self: ParliamentApiContactSource,
        _session: requests.Session,
        url: str,
        _params: dict[str, str | int | bool] | None = None,
    ) -> object:
        if "/Members/Search" in url:
            return _search_page([_member_value(1, "One")], total=1)
        member_id = int(url.rstrip("/").split("/")[-2])
        if fail_times.get(member_id, 0) > 0:
            fail_times[member_id] -= 1
            message = "boom"
            raise requests.Timeout(message)
        return _contacts_payload("https://twitter.com/one")

    monkeypatch.setattr(ParliamentApiContactSource, "_get_json", fake_get_json)
    delays: list[float] = []
    source = ParliamentApiContactSource(page_size=1, houses=("Commons",), sleep=delays.append)

    members = source.load_members()

    assert [m.id for m in members] == [1]
    assert members[0].contacts[0].line1 == "https://twitter.com/one"
    assert delays[:2] == [2.0, 4.0]


@pytest.mark.parametrize(
    "payload",
    [
        "not an object",
        {},
        {"value": None},
        {"value": {"nested": "object"}},
    ],
)
def test_load_members_rejects_malformed_contact_payload(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    """A 200 contact response with a drifted schema aborts without retries."""

    def fake_get_json(
        _self: ParliamentApiContactSource,
        _session: requests.Session,
        url: str,
        _params: dict[str, str | int | bool] | None = None,
    ) -> object:
        if "/Members/Search" in url:
            return _search_page([_member_value(1, "One")], total=1)
        return payload

    monkeypatch.setattr(ParliamentApiContactSource, "_get_json", fake_get_json)
    delays: list[float] = []
    source = ParliamentApiContactSource(page_size=1, houses=("Commons",), sleep=delays.append)

    with pytest.raises(ContactSourceError, match="Contact response"):
        _ = source.load_members()
    assert delays == []


@pytest.mark.parametrize(
    "payload",
    [
        "not an object",
        {},
        {"items": "nope"},
    ],
)
def test_load_members_rejects_malformed_search_page(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    """A malformed Members/Search page aborts instead of truncating the list."""

    def fake_get_json(
        _self: ParliamentApiContactSource,
        _session: requests.Session,
        _url: str,
        _params: dict[str, str | int | bool] | None = None,
    ) -> object:
        return payload

    monkeypatch.setattr(ParliamentApiContactSource, "_get_json", fake_get_json)
    with pytest.raises(ContactSourceError, match="Members/Search page"):
        _ = _api().load_members()


def _http_error(status_code: int) -> requests.HTTPError:
    """Build an HTTPError carrying a response with the given status."""
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


def _install_contact_error_api(
    monkeypatch: pytest.MonkeyPatch,
    errors_then_success: list[requests.RequestException],
) -> None:
    """Fake a one-member API whose contact endpoint pops the given errors."""

    def fake_get_json(
        _self: ParliamentApiContactSource,
        _session: requests.Session,
        url: str,
        _params: dict[str, str | int | bool] | None = None,
    ) -> object:
        if "/Members/Search" in url:
            return _search_page([_member_value(1, "One")], total=1)
        if errors_then_success:
            raise errors_then_success.pop(0)
        return _contacts_payload("https://twitter.com/one")

    monkeypatch.setattr(ParliamentApiContactSource, "_get_json", fake_get_json)


def test_load_members_fails_immediately_on_permanent_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 contact response aborts on the first attempt with no backoff."""
    _install_contact_error_api(monkeypatch, [_http_error(404)])
    delays: list[float] = []
    source = ParliamentApiContactSource(page_size=1, houses=("Commons",), sleep=delays.append)

    with pytest.raises(ContactSourceError, match="permanent error"):
        _ = source.load_members()
    assert delays == []


def test_load_members_retries_server_errors_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 503 is transient: retried with backoff, then the fetch succeeds."""
    _install_contact_error_api(monkeypatch, [_http_error(503)])
    delays: list[float] = []
    source = ParliamentApiContactSource(page_size=1, houses=("Commons",), sleep=delays.append)

    members = source.load_members()

    assert [m.id for m in members] == [1]
    assert delays[0] == 2.0


def test_load_members_wraps_search_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing Members/Search request surfaces as ContactSourceError."""

    def fake_get_json(
        _self: ParliamentApiContactSource,
        _session: requests.Session,
        _url: str,
        _params: dict[str, str | int | bool] | None = None,
    ) -> object:
        message = "search down"
        raise requests.RequestException(message)

    monkeypatch.setattr(ParliamentApiContactSource, "_get_json", fake_get_json)
    with pytest.raises(ContactSourceError, match="member search failed"):
        _ = _api().load_members()
