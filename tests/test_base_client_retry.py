import asyncio

import httpx
import pytest
from rfc9457 import BadRequestProblem

from basic_api.base_client import REQUEST_ATTEMPTS, BaseClient
from basic_api.types import BaseClientIn


class _Client(BaseClient):
    def process_response(self, response_data, schema):
        return response_data


class _ScriptedClient:
    def __init__(self, outcomes: list):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def request(self, method, url, headers=None, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aclose(self):
        return None


def _client(outcomes: list) -> tuple[_Client, _ScriptedClient]:
    client = _Client(
        BaseClientIn(
            api_key="secret",
            header_name="api-key",
            base_url="https://api.example.test/api",
        )
    )
    http = _ScriptedClient(outcomes)
    client._http_client = http
    return client, http


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    async def _sleep(_delay):
        return None

    monkeypatch.setattr("basic_api.base_client.asyncio.sleep", _sleep)


def test_retries_transport_error_then_returns_response():
    client, http = _client(
        [
            httpx.ReadError("peer closed connection"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    response = _run(client._make_request("GET", "https://api.example.test/cars"))

    assert response.status_code == 200
    assert http.calls == 2


def test_retries_server_error_then_returns_response():
    client, http = _client(
        [
            httpx.Response(503, content=b"unavailable"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    response = _run(
        client._make_request(
            "GET",
            "https://api.example.test/api/db/cars/deleted",
            params={"date_from": "2026-10-11"},
        )
    )

    assert response.status_code == 200
    assert http.calls == 2


def test_gives_up_after_retryable_transport_failures():
    client, http = _client(
        [httpx.RemoteProtocolError("incomplete chunked read")] * REQUEST_ATTEMPTS
    )

    with pytest.raises(BadRequestProblem) as exc_info:
        _run(
            client._make_request("GET", "https://api.example.test/api/db/cars/deleted")
        )

    assert http.calls == REQUEST_ATTEMPTS
    assert "RemoteProtocolError: incomplete chunked read" in exc_info.value.detail
    assert "attempt 3/3 (not retrying)" in exc_info.value.detail
    assert "https://api.example.test/api/db/cars/deleted" in exc_info.value.detail


def test_does_not_retry_client_error_response():
    client, http = _client([httpx.Response(404, content=b"missing")])

    response = _run(client._make_request("GET", "https://api.example.test/cars/1"))

    assert response.status_code == 404
    assert http.calls == 1


def test_does_not_retry_non_request_exception():
    client, http = _client([RuntimeError("programmer error")])

    with pytest.raises(RuntimeError, match="programmer error"):
        _run(client._make_request("GET", "https://api.example.test/cars"))

    assert http.calls == 1


def test_does_not_retry_non_transport_http_error():
    client, http = _client([httpx.UnsupportedProtocol("bad scheme")])

    with pytest.raises(BadRequestProblem) as exc_info:
        _run(client._make_request("GET", "https://api.example.test/cars"))

    assert http.calls == 1
    assert "UnsupportedProtocol: bad scheme" in exc_info.value.detail
    assert "not retrying" in exc_info.value.detail
