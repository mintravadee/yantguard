
import asyncio
import logging
import math
import os

import httpx
from google import genai
from google.genai import errors, types

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 1.0
RETRYABLE_STATUS_CODES = {408, 500, 502, 503, 504}


def get_timeout_seconds() -> float:
    timeout = float(os.getenv("GEMINI_TIMEOUT_SECONDS") or "60")
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("GEMINI_TIMEOUT_SECONDS must be greater than 0 and at most 300")
    return timeout


def get_gateway_timeout_seconds() -> float:
    # Allow both attempts, the retry delay, and time to close the SDK client.
    return MAX_ATTEMPTS * get_timeout_seconds() + RETRY_DELAY_SECONDS + 5.0


async def generate(prompt: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash"

    if not api_key:
        raise RuntimeError("Gemini API key is missing")

    timeout_seconds = get_timeout_seconds()
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(timeout_seconds * 1000),
            # Own the retry budget here; avoid nested retries and raw SDK error logs.
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(model=model, contents=prompt),
                    timeout=timeout_seconds,
                )
                break
            except errors.APIError as exc:
                if exc.code not in RETRYABLE_STATUS_CODES or attempt == MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "Gemini returned HTTP %s; retrying (attempt %s/%s)",
                    exc.code, attempt + 1, MAX_ATTEMPTS,
                )
            except (asyncio.TimeoutError, httpx.TransportError) as exc:
                if attempt == MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "Gemini transport failure (%s); retrying (attempt %s/%s)",
                    type(exc).__name__, attempt + 1, MAX_ATTEMPTS,
                )
            await asyncio.sleep(RETRY_DELAY_SECONDS)

        usage = response.usage_metadata
        answer = response.text

        if not isinstance(answer, str) or not answer:
            raise ValueError("Gemini returned no text")

        return {
            "provider": "gemini",
            "model": model,
            "answer": answer,
            "usage": {
                "prompt_tokens": (
                    usage.prompt_token_count if usage else 0
                ),
                "completion_tokens": (
                    usage.candidates_token_count if usage else 0
                ),
                "total_tokens": (
                    usage.total_token_count if usage else 0
                )
            }
        }

    finally:
        await client.aio.aclose()
