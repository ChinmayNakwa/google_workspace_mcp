"""Full/incremental sync through the existing list_contacts tool."""

import json
from unittest.mock import MagicMock, Mock

import pytest
from fastmcp import Client, FastMCP
from googleapiclient.errors import HttpError

from core.utils import UserInputError
from gcontacts.contacts_helpers import DEFAULT_PERSON_FIELDS, _format_contact
from gcontacts.contacts_tools import list_contacts


def _unwrap(function):
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__
    return function


async def _call(service, **kwargs):
    return await _unwrap(list_contacts)(
        service=service, user_google_email="user@example.com", **kwargs
    )


def _service(response=None, error=None):
    service = MagicMock()
    execute = (
        service.people.return_value.connections.return_value.list.return_value.execute
    )
    execute.return_value = response or {}
    execute.side_effect = error
    return service


def _request(service):
    return service.people.return_value.connections.return_value.list.call_args.kwargs


def _http_error(status):
    return HttpError(
        Mock(status=status, reason="test error"),
        json.dumps({"error": {"code": status, "message": "test error"}}).encode(),
    )


@pytest.mark.asyncio
async def test_default_listing_preserves_text_and_request_parameters():
    contact = {
        "resourceName": "people/c1",
        "names": [{"displayName": "Example Person"}],
        "emailAddresses": [{"value": "person@example.com", "type": "work"}],
        "phoneNumbers": [{"value": "+12025550123", "type": "mobile"}],
    }
    service = _service(
        {"connections": [contact], "totalPeople": 4, "nextPageToken": "page-2"}
    )
    result = await _call(
        service, page_token="page-1", sort_order="FIRST_NAME_ASCENDING"
    )
    assert result == (
        "Contacts for user@example.com (1 of 4):\n\n"
        + _format_contact(contact)
        + "\n\nNext page token: page-2"
    )
    assert _request(service) == {
        "resourceName": "people/me",
        "personFields": DEFAULT_PERSON_FIELDS,
        "pageSize": 100,
        "pageToken": "page-1",
        "sortOrder": "FIRST_NAME_ASCENDING",
    }


@pytest.mark.asyncio
async def test_empty_default_listing_preserves_text():
    assert await _call(_service()) == "No contacts found for user@example.com."


@pytest.mark.asyncio
async def test_full_sync_preserves_contact_arrays_and_metadata():
    contact = {
        "resourceName": "people/c1",
        "etag": "etag-1",
        "names": [{"displayName": "Example Person", "givenName": "Example"}],
        "nicknames": [{"value": "E."}],
        "emailAddresses": [{"value": "person@example.com", "type": "work"}],
        "phoneNumbers": [{"value": "+12025550123", "type": "mobile"}],
        "organizations": [{"name": "Example", "title": "Engineer"}],
        "metadata": {"sources": [{"type": "CONTACT", "id": "c1"}]},
    }
    service = _service({"connections": [contact], "nextSyncToken": "sync-1"})
    result = await _call(service, request_sync_token=True, page_size=250)
    assert result == {
        "account": "user@example.com",
        "contacts": [contact],
        "page_size": 250,
        "next_page_token": None,
        "next_sync_token": "sync-1",
        "reset_required": False,
    }
    assert _request(service) == {
        "resourceName": "people/me",
        "personFields": DEFAULT_PERSON_FIELDS + ",metadata",
        "pageSize": 250,
        "requestSyncToken": True,
    }
    service.people.return_value.get.assert_not_called()


@pytest.mark.asyncio
async def test_full_sync_pagination_keeps_parameters_and_empty_page_cursor():
    service = _service({"nextPageToken": "page-2"})
    first = await _call(service, request_sync_token=True, page_size=250)
    first_params = _request(service).copy()
    service.people.return_value.connections.return_value.list.return_value.execute.return_value = {
        "nextSyncToken": "sync-1"
    }
    final = await _call(
        service,
        request_sync_token=True,
        page_size=first["page_size"],
        page_token=first["next_page_token"],
    )
    assert first["contacts"] == []
    assert first["next_sync_token"] is None
    assert _request(service) == {**first_params, "pageToken": "page-2"}
    assert final["next_page_token"] is None
    assert final["next_sync_token"] == "sync-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("request_sync_token", [False, True])
async def test_incremental_sync_returns_tombstones_and_requests_new_cursor(
    request_sync_token,
):
    deleted = {"resourceName": "people/c1", "metadata": {"deleted": True}}
    service = _service({"connections": [deleted], "nextSyncToken": "sync-new"})
    result = await _call(
        service, sync_token="sync-old", request_sync_token=request_sync_token
    )
    assert result["contacts"] == [deleted]
    assert result["next_sync_token"] == "sync-new"
    assert _request(service) == {
        "resourceName": "people/me",
        "personFields": DEFAULT_PERSON_FIELDS + ",metadata",
        "pageSize": 100,
        "syncToken": "sync-old",
        "requestSyncToken": True,
    }


@pytest.mark.asyncio
async def test_incremental_pagination_keeps_original_sync_token():
    service = _service({"nextPageToken": "next"})
    page = await _call(service, sync_token="original", page_size=250)
    original_params = _request(service).copy()
    await _call(
        service,
        sync_token="original",
        page_size=page["page_size"],
        page_token=page["next_page_token"],
    )
    assert _request(service) == {**original_params, "pageToken": "next"}


@pytest.mark.asyncio
async def test_expired_sync_token_requires_explicit_full_sync():
    service = _service(error=_http_error(410))
    assert await _call(service, sync_token="expired", page_size=250) == {
        "account": "user@example.com",
        "contacts": [],
        "page_size": 250,
        "next_page_token": None,
        "next_sync_token": None,
        "reset_required": True,
    }
    service.people.return_value.connections.return_value.list.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,sync_token", [(403, "sync"), (429, "sync"), (500, "sync"), (410, None)]
)
async def test_other_errors_are_not_reported_as_successful_empty_sync(
    status, sync_token
):
    service = _service(error=_http_error(status))
    with pytest.raises(HttpError):
        await _call(service, request_sync_token=True, sync_token=sync_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [0, -1])
async def test_invalid_page_size_does_not_call_google(page_size):
    service = _service()
    with pytest.raises(UserInputError, match="page_size"):
        await _call(service, request_sync_token=True, page_size=page_size)
    service.people.assert_not_called()


@pytest.mark.asyncio
async def test_oversized_page_size_is_capped_and_reported():
    service = _service()
    result = await _call(service, request_sync_token=True, page_size=1001)
    assert result["page_size"] == _request(service)["pageSize"] == 1000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sync_options", [{"request_sync_token": True}, {"sync_token": "sync"}]
)
async def test_sync_rejects_sort_order_before_calling_google(sync_options):
    service = _service()
    with pytest.raises(UserInputError, match="sort_order"):
        await _call(service, sort_order="FIRST_NAME_ASCENDING", **sync_options)
    service.people.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("sync_token", ["", "   "])
async def test_empty_sync_token_does_not_fall_back_to_full_listing(sync_token):
    service = _service()
    with pytest.raises(UserInputError, match="sync_token"):
        await _call(service, sync_token=sync_token)
    service.people.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_serializes_both_text_and_structured_sync_without_new_tool():
    service = _service({"nextSyncToken": "sync-1"})
    implementation = _unwrap(list_contacts)
    app = FastMCP("contacts-test")

    @app.tool(name="list_contacts", output_schema=None)
    async def listing(request_sync_token: bool = False) -> str | dict:
        return await implementation(
            service=service,
            user_google_email="user@example.com",
            request_sync_token=request_sync_token,
        )

    async with Client(app) as client:
        assert [tool.name for tool in await client.list_tools()] == ["list_contacts"]
        normal = await client.call_tool("list_contacts", {})
        sync = await client.call_tool("list_contacts", {"request_sync_token": True})
    assert normal.content[0].text == "No contacts found for user@example.com."
    assert sync.structured_content["next_sync_token"] == "sync-1"
    assert sync.structured_content["contacts"] == []
