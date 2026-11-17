
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai.errors import ClientError, ServerError
from groq import APIConnectionError, APIStatusError, APITimeoutError

from app.main import app
from app.gateway import gemini_client, groq_client

client = TestClient(app)
URL = "/api/gateway/request"


def test_get_request_help():
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json()["method"] == "POST"
    assert response.json()["docs"] == "/docs"


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_repeated_key_assignment(monkeypatch, provider):
    key_name = f"{provider.upper()}_API_KEY"
    monkeypatch.setenv(key_name, f"{key_name}=SECRET_TEST_API_KEY")
    response = client.post(URL, json={"provider": provider, "prompt": "Hello"})
    assert response.status_code == 503
    assert "remove the repeated variable name" in response.json()["detail"]
    assert "SECRET_TEST_API_KEY" not in response.text


# --------------------------------
# Helper: Fake successful AI answer
# --------------------------------

def mock_provider(monkeypatch, provider="groq"):

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    async def fake_generate(prompt):
        return {
            "provider": provider,
            "model": "test-model",
            "answer": "Test AI response",
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 10,
                "total_tokens": 15
            }
        }

    if provider == "groq":
        monkeypatch.setattr(
            groq_client, "generate", fake_generate
        )
    else:
        monkeypatch.setattr(
            gemini_client, "generate", fake_generate
        )


# --------------------------------
# 1. Health Check
# --------------------------------

def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


# --------------------------------
# 2. Normal requests
# --------------------------------

@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_success(monkeypatch, provider):
    mock_provider(monkeypatch, provider)

    response = client.post(
        URL,
        json={
            "provider": provider,
            "prompt": "Hello"
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert data["provider"] == provider
    assert data["answer"] == "Test AI response"
    assert data["usage"]["total_tokens"] == 15


# --------------------------------
# 3. Invalid providers
# --------------------------------

@pytest.mark.parametrize(
    "provider",
    ["openai", "claude", "unknown", "", None, 123]
)
def test_invalid_provider(provider):
    response = client.post(
        URL,
        json={
            "provider": provider,
            "prompt": "Hello"
        }
    )

    assert response.status_code == 422


# --------------------------------
# 4. Empty or whitespace prompts
# --------------------------------

@pytest.mark.parametrize(
    "prompt, expected_status",
    [
        ("", 422),
        (" ", 422),
        ("   ", 422),
        ("\n\t ", 422),
    ]
)
def test_empty_or_whitespace_prompt(
    monkeypatch, prompt, expected_status
):
    mock_provider(monkeypatch)

    response = client.post(
        URL,
        json={
            "provider": "groq",
            "prompt": prompt
        }
    )

    assert response.status_code == expected_status


# --------------------------------
# 5. Prompt length boundaries
# --------------------------------

@pytest.mark.parametrize(
    "length, expected_status",
    [
        (1, 200),
        (3999, 200),
        (4000, 200),
        (4001, 422),
        (10000, 422),
    ]
)
def test_prompt_length(
    monkeypatch, length, expected_status
):
    mock_provider(monkeypatch)

    response = client.post(
        URL,
        json={
            "provider": "groq",
            "prompt": "A" * length
        }
    )

    assert response.status_code == expected_status


# --------------------------------
# 6. Missing required fields
# --------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"provider": "groq"},
        {"prompt": "Hello"},
        {"provider": "groq", "prompt": None},
    ]
)
def test_missing_fields(payload):
    response = client.post(URL, json=payload)

    assert response.status_code == 422


# --------------------------------
# 7. Missing API keys
# --------------------------------

@pytest.mark.parametrize(
    "provider, key_name",
    [
        ("gemini", "GEMINI_API_KEY"),
        ("groq", "GROQ_API_KEY"),
    ]
)
def test_missing_api_key(
    monkeypatch, provider, key_name
):
    monkeypatch.delenv(key_name, raising=False)

    response = client.post(
        URL,
        json={
            "provider": provider,
            "prompt": "Hello"
        }
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Provider not configured"
    )


# --------------------------------
# 8. Provider timeout
# --------------------------------

@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_provider_timeout(monkeypatch, provider):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    async def fake_timeout(prompt):
        raise asyncio.TimeoutError()

    module = (
        gemini_client
        if provider == "gemini"
        else groq_client
    )

    monkeypatch.setattr(module, "generate", fake_timeout)

    response = client.post(
        URL,
        json={
            "provider": provider,
            "prompt": "Hello"
        }
    )

    assert response.status_code == 504
    assert response.json()["detail"] == (
        "AI provider timed out"
    )


# --------------------------------
# 9. Provider error / secret leakage
# --------------------------------

def test_provider_error_does_not_leak_key(monkeypatch):
    monkeypatch.setenv(
        "GROQ_API_KEY", "SECRET_TEST_API_KEY"
    )

    async def fake_failure(prompt):
        raise RuntimeError(
            "Provider error: SECRET_TEST_API_KEY"
        )

    monkeypatch.setattr(
        groq_client, "generate", fake_failure
    )

    response = client.post(
        URL,
        json={
            "provider": "groq",
            "prompt": "Hello"
        }
    )

    assert response.status_code == 502

    assert "SECRET_TEST_API_KEY" not in response.text

    assert response.json()["detail"] == (
        "AI provider request failed"
    )


# --------------------------------
# 10. Invalid provider response
# --------------------------------

def test_invalid_response(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    async def fake_invalid(prompt):
        return {
            "provider": "groq",
            "model": "test-model",
            "answer": None,
            "usage": {}
        }

    monkeypatch.setattr(
        groq_client, "generate", fake_invalid
    )

    response = client.post(
        URL,
        json={
            "provider": "groq",
            "prompt": "Hello"
        }
    )

    assert response.status_code == 502


# --------------------------------
# 11. Non-JSON request
# --------------------------------

def test_invalid_json():
    response = client.post(
        URL,
        content="{invalid-json",
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize(
    "upstream_status, expected_status, detail_fragment",
    [
        (400, 502, "rejected the request"),
        (401, 503, "rejected the API key or denied access"),
        (403, 503, "rejected the API key or denied access"),
        (404, 503, "model was not found or is unavailable"),
        (429, 429, "rate limit or quota exceeded"),
        (500, 502, "AI provider request failed"),
        (503, 503, "temporarily unavailable"),
        (504, 504, "AI provider timed out"),
    ],
)
def test_provider_api_errors(
    monkeypatch, caplog, provider, upstream_status, expected_status, detail_fragment
):
    secret = "SECRET_TEST_API_KEY"
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", secret)
    raw_message = f"Private prompt and API key: {secret}"
    if provider == "gemini":
        error_class = ClientError if upstream_status < 500 else ServerError
        error = error_class(upstream_status, {"error": {"message": raw_message}})
        module = gemini_client
    else:
        error = APIStatusError(
            raw_message,
            response=httpx.Response(
                upstream_status,
                request=httpx.Request("POST", "https://example.com", headers={"Authorization": secret}),
            ),
            body={"message": raw_message},
        )
        module = groq_client

    async def fake_failure(prompt):
        raise error

    monkeypatch.setattr(module, "generate", fake_failure)
    response = client.post(URL, json={"provider": provider, "prompt": "Hello"})

    assert response.status_code == expected_status
    assert detail_fragment in response.json()["detail"]
    assert secret not in response.text + caplog.text
    assert "Private prompt" not in response.text + caplog.text
    assert f"{provider} returned HTTP {upstream_status}" in caplog.text


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize("failure", ["timeout", "connection"])
def test_provider_transport_errors(monkeypatch, caplog, provider, failure):
    secret = "SECRET_TEST_API_KEY"
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", secret)
    request = httpx.Request("POST", f"https://example.com/?key={secret}")
    if provider == "gemini":
        error_class = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        error = error_class(f"Private prompt: {secret}", request=request)
        module = gemini_client
    else:
        error = (
            APITimeoutError(request=request)
            if failure == "timeout"
            else APIConnectionError(message=f"Private prompt: {secret}", request=request)
        )
        module = groq_client

    async def fake_failure(prompt):
        raise error

    monkeypatch.setattr(module, "generate", fake_failure)
    response = client.post(URL, json={"provider": provider, "prompt": "Hello"})

    assert response.status_code == (504 if failure == "timeout" else 502)
    assert ("timed out" if failure == "timeout" else "Could not connect") in response.json()["detail"]
    assert secret not in response.text + caplog.text
    assert "Private prompt" not in response.text + caplog.text
