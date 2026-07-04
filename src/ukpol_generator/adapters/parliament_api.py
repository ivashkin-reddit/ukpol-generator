"""Parliament Members API adapter implementing :class:`MemberContactSource`.

This is a boundary adapter: it performs the only network I/O in the system and
narrows the loosely typed JSON returned by the API into the strongly typed
:class:`Member`/:class:`RawContact` domain models. No ``dict``-shaped API payload
is allowed to escape this module.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import requests

from ukpol_generator.adapters.json_narrowing import (
    coerce_int,
    coerce_str,
    mapping_get,
)
from ukpol_generator.domain.models import Member, RawContact
from ukpol_generator.ports.contacts import ContactSourceError

if TYPE_CHECKING:
    from collections.abc import Callable

_logger = logging.getLogger(__name__)

BASE_URL = "https://members-api.parliament.uk/api"
PAGE_SIZE = 20  # Maximum page size allowed by the API.
REQUEST_TIMEOUT_SECONDS = 30.0

_BATCH_SIZE = 10
_PAGE_DELAY_SECONDS = 0.3
_ITEM_DELAY_SECONDS = 0.2
_BATCH_DELAY_SECONDS = 1.0
_CONTACT_FETCH_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR_MIN = 500


def _is_retryable(error: requests.RequestException) -> bool:
    """Return whether a request error is plausibly transient.

    Connection failures and timeouts are transient. HTTP responses are
    transient only for 429 (rate limit) and 5xx (server fault). Everything
    else - 404/401/403, malformed JSON bodies - is permanent: retrying
    cannot change the outcome, so the run should fail immediately.
    """
    if isinstance(error, requests.HTTPError):
        response = error.response
        return response is not None and (
            response.status_code == _TOO_MANY_REQUESTS or response.status_code >= _SERVER_ERROR_MIN
        )
    return isinstance(error, requests.ConnectionError | requests.Timeout)


def _require_mapping(value: object, context: str) -> dict[str, object]:
    """Narrow to a JSON object, failing the fetch on schema drift."""
    if not isinstance(value, dict):
        message = f"{context}: expected a JSON object, got {type(value).__name__}"
        raise ContactSourceError(message)
    return cast("dict[str, object]", value)


def _require_list_field(payload: object, key: str, context: str) -> list[object]:
    """Read a required list field, failing the fetch when absent or mistyped.

    An empty list is valid (a member with no contacts, or the final empty
    search page); a missing or non-list field is schema drift and must abort
    the run rather than silently shrink the whitelist.
    """
    value = _require_mapping(payload, context).get(key)
    if not isinstance(value, list):
        message = f"{context}: required field {key!r} is missing or not a list"
        raise ContactSourceError(message)
    return cast("list[object]", value)


@dataclass(frozen=True)
class _MemberSummary:
    """Basic member info fetched before their contact records."""

    id: int
    name: str
    party: str
    house: str
    constituency: str | None


def member_summary(item: object, house: str) -> _MemberSummary:
    """Narrow one Members/Search ``items`` entry into a :class:`_MemberSummary`.

    Args:
        item: A single search-result item (expected to wrap a ``value`` object).
        house: The house being queried, stored on the summary.

    Returns:
        The narrowed summary.

    Raises:
        ContactSourceError: If the entry has no integer ``id``. A member must
            never be silently dropped from the fetched set.
    """
    value = mapping_get(item, "value")
    member_id = coerce_int(mapping_get(value, "id"))
    if member_id is None:
        name = coerce_str(mapping_get(value, "nameDisplayAs")) or "<unknown>"
        message = f"Members/Search item for {name!r} ({house}) has no integer id"
        raise ContactSourceError(message)
    party = mapping_get(mapping_get(value, "latestParty"), "name")
    membership = mapping_get(value, "latestHouseMembership")
    return _MemberSummary(
        id=member_id,
        name=coerce_str(mapping_get(value, "nameDisplayAs")) or "Unknown",
        party=coerce_str(party) or "Unknown",
        house=house,
        constituency=coerce_str(mapping_get(membership, "membershipFrom")),
    )


def raw_contact(item: object) -> RawContact:
    """Narrow one raw contact object into a :class:`RawContact`."""
    return RawContact(
        type_id=coerce_int(mapping_get(item, "typeId")),
        line1=coerce_str(mapping_get(item, "line1")),
        website=coerce_str(mapping_get(item, "website")),
    )


def _to_member(summary: _MemberSummary, contacts: tuple[RawContact, ...]) -> Member:
    """Combine a summary with its fetched contacts into a :class:`Member`."""
    return Member(
        id=summary.id,
        name=summary.name,
        party=summary.party,
        house=summary.house,
        constituency=summary.constituency,
        contacts=contacts,
    )


@dataclass(frozen=True)
class ParliamentApiContactSource:
    """Fetch current MPs and Lords with their contacts from the Members API.

    Attributes:
        base_url: The API base URL.
        page_size: The Members/Search page size.
        request_timeout: Per-request timeout in seconds.
        houses: The houses to query, in fetch order.
        sleep: Injected sleep function (defaults to time.sleep); override in tests.
    """

    base_url: str = BASE_URL
    page_size: int = PAGE_SIZE
    request_timeout: float = REQUEST_TIMEOUT_SECONDS
    houses: tuple[str, ...] = ("Commons", "Lords")
    sleep: Callable[[float], None] = time.sleep

    def _throttle(self, index: int) -> None:
        """Sleep between per-member requests to stay polite to the API."""
        delay = _BATCH_DELAY_SECONDS if index % _BATCH_SIZE == 0 else _ITEM_DELAY_SECONDS
        self.sleep(delay)

    def load_members(self) -> list[Member]:
        """Fetch every current member with their narrowed contact records.

        Raises:
            ContactSourceError: If the member search fails, any response's
                schema has drifted, or any member's contact fetch still fails
                after retries; no partial member set is ever returned.
        """
        with requests.Session() as session:
            session.headers.update({"Accept": "application/json"})
            try:
                summaries = self._fetch_all_summaries(session)
            except requests.RequestException as error:
                message = "member search failed; fetch aborted"
                raise ContactSourceError(message) from error
            _logger.info("Fetching contacts for %d members...", len(summaries))
            return self._fetch_all_members(session, summaries)

    def _get_json(
        self,
        session: requests.Session,
        url: str,
        params: dict[str, str | int | bool] | None = None,
    ) -> object:
        """Perform a GET request and return the decoded JSON body."""
        response = session.get(url, params=params, timeout=self.request_timeout)
        response.raise_for_status()
        return response.json()

    def _fetch_all_summaries(self, session: requests.Session) -> list[_MemberSummary]:
        """Fetch member summaries for every configured house."""
        summaries: list[_MemberSummary] = []
        for house in self.houses:
            _logger.info("Fetching members from the %s...", house)
            house_summaries = self._fetch_house_summaries(session, house)
            _logger.info("Total %s members fetched: %d", house, len(house_summaries))
            summaries.extend(house_summaries)
        return summaries

    def _fetch_house_summaries(self, session: requests.Session, house: str) -> list[_MemberSummary]:
        """Page through Members/Search for a single house."""
        summaries: list[_MemberSummary] = []
        skip = 0
        while True:
            params: dict[str, str | int | bool] = {
                "House": house,
                "IsCurrentMember": True,
                "skip": skip,
                "take": self.page_size,
            }
            payload = self._get_json(session, f"{self.base_url}/Members/Search", params)
            items = _require_list_field(
                payload, "items", f"Members/Search page (house={house}, skip={skip})"
            )
            if not items:
                break
            summaries.extend(member_summary(item, house) for item in items)
            skip += self.page_size
            total = coerce_int(mapping_get(payload, "totalResults"))
            if total is not None and skip >= total:
                break
            self.sleep(_PAGE_DELAY_SECONDS)
        return summaries

    def _fetch_all_members(
        self, session: requests.Session, summaries: list[_MemberSummary]
    ) -> list[Member]:
        """Fetch contacts for each summary and build the final members."""
        total = len(summaries)
        members: list[Member] = []
        for index, summary in enumerate(summaries, start=1):
            contacts = self._fetch_contacts_with_retry(session, summary, index, total)
            _logger.info(
                "[%d/%d] %s: %d contact record(s)",
                index,
                total,
                summary.name,
                len(contacts),
            )
            members.append(_to_member(summary, contacts))
            self._throttle(index)
        return members

    def _fetch_contacts_with_retry(
        self,
        session: requests.Session,
        summary: _MemberSummary,
        index: int,
        total: int,
    ) -> tuple[RawContact, ...]:
        """Fetch one member's contacts, retrying before failing the run.

        Only plausibly transient errors (per :func:`_is_retryable`) get
        ``_CONTACT_FETCH_ATTEMPTS - 1`` retries with linear backoff through
        the injected ``sleep`` seam; permanent errors abort on the first
        attempt. A member that still fails aborts the whole fetch: a partial
        member set must never silently become the whitelist.
        """
        for attempt in range(1, _CONTACT_FETCH_ATTEMPTS):
            try:
                contacts = self._get_member_contacts(session, summary.id)
            except requests.RequestException as error:
                if not _is_retryable(error):
                    message = (
                        f"contact fetch for {summary.name} (member id "
                        f"{summary.id}) failed with a permanent error"
                    )
                    raise ContactSourceError(message) from error
                _logger.warning(
                    "[%d/%d] %s: contact fetch attempt %d failed - retrying",
                    index,
                    total,
                    summary.name,
                    attempt,
                )
                self.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            else:
                return contacts
        try:
            contacts = self._get_member_contacts(session, summary.id)
        except requests.RequestException as error:
            message = (
                f"contact fetch for {summary.name} (member id {summary.id}) "
                f"failed after {_CONTACT_FETCH_ATTEMPTS} attempts"
            )
            raise ContactSourceError(message) from error
        return contacts

    def _get_member_contacts(
        self, session: requests.Session, member_id: int
    ) -> tuple[RawContact, ...]:
        """Fetch and narrow the contact records for a single member.

        Raises:
            ContactSourceError: If the response schema has drifted. Not a
                :class:`requests.RequestException`, so it deliberately
                bypasses the retry loop - schema drift is not transient.
        """
        payload = self._get_json(session, f"{self.base_url}/Members/{member_id}/Contact")
        items = _require_list_field(payload, "value", f"Members/{member_id}/Contact response")
        return tuple(raw_contact(item) for item in items)
