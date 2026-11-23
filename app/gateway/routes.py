
import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from google.genai.errors import APIError as GeminiAPIError
from groq import APIConnectionError, APIStatusError, APITimeoutError

from app.gateway.schemas import (
    GatewayRequest,
    GatewayResponse,
)
from app.gateway import gemini_client, groq_client

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/gateway",
    tags=["AI Gateway"]
)


def provider_http_error(provider: str, status_code: int) -> HTTPException:
    """Explain provider failures without returning their raw messages or keys."""
    name = provider.capitalize()
    if status_code in (401, 403):
        return HTTPException(
            status_code=503,
            detail=f"{name} rejected the API key or denied access. "
            "Check the key, API restrictions, and project permissions.",
        )
    if status_code == 404:
        return HTTPException(
            status_code=503,
            detail=f"{name} model was not found or is unavailable for this API key. "
            f"Set {provider.upper()}_MODEL to a supported model and restart the server.",
        )
    if status_code == 429:
        return HTTPException(
            status_code=429,
            detail=f"{name} rate limit or quota exceeded. "
            "Check the project's quota and billing, or retry later.",
        )
    if status_code == 400:
        return HTTPException(
            status_code=502,
            detail=f"{name} rejected the request. "
            "Check the API key, model, and project configuration.",
        )
    if status_code in (408, 504):
        return HTTPException(status_code=504, detail="AI provider timed out")
    if status_code == 503:
        return HTTPException(
            status_code=503,
            detail=f"{name} is temporarily unavailable after retries. "
            "Keep your existing API key and try again later.",
            headers={"Retry-After": "30"},
        )
    return HTTPException(status_code=502, detail="AI provider request failed")


@router.get("/request")
async def gateway_request_help():
    return {
        "message": "Send a POST request with a JSON body to generate an AI response.",
        "method": "POST",
        "example": {"provider": "groq", "prompt": "Hello"},
        "docs": "/docs",
    }


@router.post(
    "/request",
    response_model=GatewayResponse
)
async def gateway_request(request: GatewayRequest):

    # Validate prompt
    if not request.prompt.strip():
        raise HTTPException(
            status_code=422,
            detail="Prompt cannot be empty"
        )

    # Select approved provider
    if request.provider == "gemini":
        key_name = "GEMINI_API_KEY"
        generate = gemini_client.generate

    elif request.provider == "groq":
        key_name = "GROQ_API_KEY"
        generate = groq_client.generate

    else:
        raise HTTPException(
            status_code=400,
            detail="Provider not approved"
        )

    # Check API key before sending
    api_key = os.getenv(key_name, "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Provider not configured"
        )

    if api_key.startswith(f"{key_name}="):
        raise HTTPException(
            status_code=503,
            detail=f"Invalid {key_name} configuration: remove the repeated variable name"
        )

    timeout_seconds = 35.0
    if request.provider == "gemini":
        try:
            timeout_seconds = gemini_client.get_gateway_timeout_seconds()
        except ValueError:
            raise HTTPException(
                status_code=503,
                detail="Invalid GEMINI_TIMEOUT_SECONDS: use a number greater than 0 and at most 300.",
            ) from None

    try:
        # Forward request to provider
        result = await asyncio.wait_for(
            generate(request.prompt),
            timeout=timeout_seconds
        )

        return GatewayResponse(**result)

    except (asyncio.TimeoutError, httpx.TimeoutException, APITimeoutError):
        logger.warning("AI provider %s timed out", request.provider)
        raise HTTPException(
            status_code=504,
            detail="AI provider timed out"
        ) from None

    except (GeminiAPIError, APIStatusError) as exc:
        status_code = exc.code if isinstance(exc, GeminiAPIError) else exc.status_code
        # Raw SDK messages, URLs, and tracebacks can contain credentials or prompts.
        logger.warning("AI provider %s returned HTTP %s", request.provider, status_code)
        raise provider_http_error(request.provider, status_code) from None

    except (httpx.RequestError, APIConnectionError):
        logger.warning("Could not connect to AI provider %s", request.provider)
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the AI provider. Check network access and proxy settings.",
        ) from None

    except Exception as exc:
        logger.warning(
            "AI provider %s request failed (%s)", request.provider, type(exc).__name__
        )
        raise HTTPException(
            status_code=502,
            detail="AI provider request failed"
        ) from None
