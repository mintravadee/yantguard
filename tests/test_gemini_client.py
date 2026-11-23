import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.gateway import gemini_client


SUCCESS = {
    "candidates": [{
        "content": {"role": "model", "parts": [{"text": "OK"}]},
        "finishReason": "STOP",
    }],
    "usageMetadata": {
        "promptTokenCount": 5,
        "candidatesTokenCount": 2,
        "totalTokenCount": 7,
    },
}
URL = "/api/gateway/request"


class TrackingTransport(httpx.MockTransport):
    is_closed = False

    async def aclose(self):
        self.is_closed = True
        await super().aclose()


@pytest.fixture
def mock_gemini_http(monkeypatch):
    """Run the real SDK and gateway against an in-memory HTTP transport."""
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET_TEST_API_KEY")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "60")
    monkeypatch.setattr(gemini_client, "RETRY_DELAY_SECONDS", 0)
    original_client = gemini_client.genai.Client
    sdk_clients = []

    def install(handler):
        http_clients = []

        def create_client(*, api_key, http_options):
            transport = TrackingTransport(handler)
            http_clients.append(transport)
            http_options.async_client_args = {"transport": transport}
            client = original_client(api_key=api_key, http_options=http_options)
            sdk_clients.append(client)
            return client

        monkeypatch.setattr(gemini_client.genai, "Client", create_client)
        return http_clients

    yield install
    for client in sdk_clients:
        client.close()


@pytest.mark.parametrize("upstream_status", [408, 500, 502, 503, 504])
def test_gemini_recovers_from_temporary_server_error(mock_gemini_http, caplog, upstream_status):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(upstream_status, json={
                "error": {"message": "Private prompt SECRET_TEST_API_KEY"},
            })
        return httpx.Response(200, json=SUCCESS)

    http_clients = mock_gemini_http(handler)
    with TestClient(app) as client:
        response = client.post(URL, json={"provider": "gemini", "prompt": "Hello"})

    assert response.status_code == 200
    assert response.json()["answer"] == "OK"
    assert len(requests) == 2
    assert all(request.headers["X-Server-Timeout"] == "60" for request in requests)
    assert all(request.extensions["timeout"]["read"] == 60 for request in requests)
    assert all(client.is_closed for client in http_clients)
    assert "SECRET_TEST_API_KEY" not in caplog.text + response.text
    assert "Private prompt" not in caplog.text + response.text


@pytest.mark.parametrize("error_class", [httpx.ReadTimeout, httpx.ConnectError])
def test_gemini_recovers_from_transport_error(mock_gemini_http, error_class, caplog):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise error_class("Private prompt SECRET_TEST_API_KEY", request=request)
        return httpx.Response(200, json=SUCCESS)

    http_clients = mock_gemini_http(handler)
    response = asyncio.run(gemini_client.generate("Hello"))

    assert response["answer"] == "OK"
    assert len(requests) == 2
    assert all(client.is_closed for client in http_clients)
    assert "SECRET_TEST_API_KEY" not in caplog.text
    assert "Private prompt" not in caplog.text


def test_gemini_stops_after_bounded_server_timeouts(mock_gemini_http):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(504, json={"error": {"status": "DEADLINE_EXCEEDED"}})

    http_clients = mock_gemini_http(handler)
    with TestClient(app) as client:
        response = client.post(URL, json={"provider": "gemini", "prompt": "Hello"})

    assert response.status_code == 504
    assert response.json()["detail"] == "AI provider timed out"
    assert len(requests) == gemini_client.MAX_ATTEMPTS
    assert all(client.is_closed for client in http_clients)


@pytest.mark.parametrize("upstream_status, expected_status", [(400, 502), (403, 503), (404, 503), (429, 429)])
def test_gemini_does_not_retry_configuration_or_quota_errors(
    mock_gemini_http, upstream_status, expected_status
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(upstream_status, json={"error": {"message": "Failed"}})

    http_clients = mock_gemini_http(handler)
    with TestClient(app) as client:
        response = client.post(URL, json={"provider": "gemini", "prompt": "Hello"})

    assert response.status_code == expected_status
    assert len(requests) == 1
    assert all(client.is_closed for client in http_clients)


def test_gemini_cancels_each_attempt_that_exceeds_deadline(mock_gemini_http, monkeypatch):
    requests = []
    cancelled = []

    async def handler(request):
        requests.append(request)
        try:
            await asyncio.sleep(1)
            return httpx.Response(200, json=SUCCESS)
        except asyncio.CancelledError:
            cancelled.append(request)
            raise

    http_clients = mock_gemini_http(handler)
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "0.01")
    with TestClient(app) as client:
        response = client.post(URL, json={"provider": "gemini", "prompt": "Hello"})

    assert response.status_code == 504
    assert len(requests) == len(cancelled) == gemini_client.MAX_ATTEMPTS
    assert all(client.is_closed for client in http_clients)


def test_gateway_cancellation_closes_gemini_without_retry(mock_gemini_http, monkeypatch):
    requests = []
    cancelled = []

    async def handler(request):
        requests.append(request)
        try:
            await asyncio.sleep(1)
            return httpx.Response(200, json=SUCCESS)
        except asyncio.CancelledError:
            cancelled.append(request)
            raise

    http_clients = mock_gemini_http(handler)
    monkeypatch.setattr(gemini_client, "get_gateway_timeout_seconds", lambda: 0.01)
    with TestClient(app) as client:
        response = client.post(URL, json={"provider": "gemini", "prompt": "Hello"})

    assert response.status_code == 504
    assert len(requests) == len(cancelled) == 1
    assert all(client.is_closed for client in http_clients)


@pytest.mark.parametrize("value", ["invalid", "0", "-1", "301", "nan", "inf"])
def test_invalid_gemini_timeout_is_a_configuration_error(monkeypatch, value):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET_TEST_API_KEY")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", value)
    with TestClient(app) as client:
        response = client.post(URL, json={"provider": "gemini", "prompt": "Hello"})

    assert response.status_code == 503
    assert "Invalid GEMINI_TIMEOUT_SECONDS" in response.json()["detail"]


def test_gemini_recovers_on_last_attempt_with_backoff(mock_gemini_http, monkeypatch):
    requests = []
    delays = []

    def handler(request):
        requests.append(request)
        if len(requests) < gemini_client.MAX_ATTEMPTS:
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})
        return httpx.Response(200, json=SUCCESS)

    async def record_sleep(delay):
        delays.append(delay)

    mock_gemini_http(handler)
    monkeypatch.setattr(gemini_client, "RETRY_DELAY_SECONDS", 1.0)
    monkeypatch.setattr(gemini_client.asyncio, "sleep", record_sleep)
    result = asyncio.run(gemini_client.generate("Hello"))

    assert result["answer"] == "OK"
    assert len(requests) == 4
    assert len(delays) == 3
    assert all(low <= delay <= high for delay, low, high in zip(delays, [0.5, 1, 2], [1, 2, 4]))
    assert gemini_client.get_gateway_timeout_seconds() == 252


def test_persistent_unavailability_keeps_key_and_advises_retry(mock_gemini_http):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})

    mock_gemini_http(handler)
    with TestClient(app) as client:
        response = client.post(URL, json={"provider": "gemini", "prompt": "Hello"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert "Keep your existing API key" in response.json()["detail"]
    assert len(requests) == gemini_client.MAX_ATTEMPTS
    assert all(request.headers["x-goog-api-key"] == "SECRET_TEST_API_KEY" for request in requests)


@pytest.mark.parametrize(
    "configured, expected",
    [(None, "gemini-3.8-flash"), ("", "gemini-3.8-flash"), ("custom-model", "custom-model")],
)
def test_gemini_model_selection(mock_gemini_http, monkeypatch, configured, expected):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=SUCCESS)

    mock_gemini_http(handler)
    if configured is None:
        monkeypatch.delenv("GEMINI_MODEL")
    else:
        monkeypatch.setenv("GEMINI_MODEL", configured)

    result = asyncio.run(gemini_client.generate("Hello"))

    assert result["model"] == expected
    assert requests[0].url.path.endswith(f"/models/{expected}:generateContent")
