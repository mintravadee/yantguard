"""Middleware for POST /api/gateway/request: API-key check + request log.

It wraps Min's route, so the route code stays unchanged.
- Step 2: every request is recorded in SQLite (prompt text is never stored).
- Step 5: the cost in USD is calculated from the token counts (see pricing.py).
- Step 6: a department that used up its monthly budget gets HTTP 429.
- Step 7: prompts are scanned; secrets/cards are blocked (400), emails/phones/IDs masked.
- Step 3: the X-API-Key header must belong to an active user.
- Step 4: the user's department must be allowed to use the requested provider.
  Set
  YANTGUARD_REQUIRE_KEY=false to switch the check off for local experiments.
A logging failure never breaks a request.
"""
import json
import logging
import os
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.governance.budgets import budget_status
from app.governance.db import init_db, log_request
from app.governance.pricing import calculate_cost
from app.governance.security import filter_enabled, scan_prompt, write_audit
from app.governance.users import KNOWN_PROVIDERS, authenticate, is_provider_allowed

logger = logging.getLogger(__name__)

GATEWAY_PATH = "/api/gateway/request"


def key_required() -> bool:
    return os.getenv("YANTGUARD_REQUIRE_KEY", "true").strip().lower() not in ("0", "false", "no")


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "POST" or request.url.path != GATEWAY_PATH:
            return await call_next(request)

        started = time.perf_counter()
        provider = None
        payload = None
        try:
            payload = json.loads(await request.body())
            provider = payload.get("provider")
        except Exception:
            pass

        user_name = None
        warning = None
        department = None
        if key_required():
            who = authenticate(request.headers.get("x-api-key"))
            if who is None:
                # Same answer for a missing, wrong, revoked or disabled key.
                self._safe_log(provider, None, 401, b"", started, "Missing or invalid API key")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid API key. Send it in the X-API-Key header."},
                )
            user_name = who["user"]
            request.state.user = who
            department = who["department"]

            # Step 4: default deny. Unknown provider names fall through to Min's validation (422).
            if isinstance(provider, str) and provider.lower() in KNOWN_PROVIDERS:
                if not is_provider_allowed(who["department"], provider):
                    self._safe_log(
                        provider, user_name, 403, b"", started,
                        f"Department '{who['department']}' may not use '{provider.lower()}'",
                    )
                    return JSONResponse(
                        status_code=403,
                        content={"detail": f"Your department is not allowed to use '{provider.lower()}'. Ask an admin for access."},
                    )

            # Step 6: monthly budget. A budget problem must never crash the gateway.
            try:
                budget = budget_status(who["department"])
            except Exception as exc:
                logger.warning("Budget check failed (%s)", type(exc).__name__)
                budget = None
            if budget and budget["state"] == "exceeded":
                self._safe_log(
                    provider, user_name, 429, b"", started,
                    f"Department '{who['department']}' used its monthly budget (${budget['limit']:.2f})",
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Your department's monthly budget (${budget['limit']:.2f}) is used up. Ask an admin to raise it."},
                )
            if budget and budget["state"] == "warning":
                warning = f"{budget['percent']}% of the monthly budget is used"

        # Step 7: security filter (runs even when API keys are switched off).
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        if filter_enabled() and isinstance(prompt, str):
            try:
                result = scan_prompt(prompt)
            except Exception as exc:  # fail closed: never send an unchecked prompt
                logger.warning("Security filter failed (%s)", type(exc).__name__)
                self._safe_log(provider, user_name, 503, b"", started, "Security filter error")
                return JSONResponse(status_code=503, content={"detail": "Security filter error. Request not sent."})
            try:
                write_audit(user_name, department, provider, result["findings"])
            except Exception as exc:
                logger.warning("Could not write audit log (%s)", type(exc).__name__)
            if result["blocked"]:
                rules = ", ".join(result["blocked"])
                self._safe_log(provider, user_name, 400, b"", started, f"Blocked by security filter: {rules}")
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Your prompt was blocked by the security filter ({rules}). "
                                       "Remove the sensitive data and try again."},
                )
            masked = [f for f in result["findings"] if f["action"] == "mask"]
            if masked:
                payload["prompt"] = result["text"]
                new_body = json.dumps(payload).encode("utf-8")

                async def receive():
                    return {"type": "http.request", "body": new_body, "more_body": False}

                request._receive = receive
                request._body = new_body
                note = ", ".join(f"{f['rule']} x{f['count']}" for f in masked)
                filter_note = f"masked: {note}"
            else:
                filter_note = None
        else:
            filter_note = None

        response = await call_next(request)
        raw = b"".join([chunk async for chunk in response.body_iterator])
        self._safe_log(provider, user_name, response.status_code, raw, started)

        headers = dict(response.headers)
        if warning:
            headers["X-Budget-Warning"] = warning.rstrip("; ")
        if filter_note:
            headers["X-Security-Filter"] = filter_note
        return Response(
            content=raw,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    def _safe_log(self, provider, user_name, status_code, raw, started, error=None):
        try:
            self._record(
                provider, user_name, status_code, raw,
                int((time.perf_counter() - started) * 1000), error,
            )
        except Exception as exc:  # logging must never break a request
            logger.warning("Could not write request log (%s)", type(exc).__name__)

    @staticmethod
    def _record(provider, user_name, status_code, raw, latency_ms, error=None):
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}

        ok = status_code == 200
        usage = data.get("usage") if ok and isinstance(data.get("usage"), dict) else {}
        if not ok and error is None:
            detail = data.get("detail")
            error = detail if isinstance(detail, str) else "request failed"

        model = data.get("model") if ok else None
        cost = calculate_cost(model, usage.get("prompt_tokens"), usage.get("completion_tokens"))

        init_db()
        log_request(
            user_name=user_name,
            provider=data.get("provider", provider) if ok else provider,
            model=model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            cost_usd=cost,
            status_code=status_code,
            success=ok,
            latency_ms=latency_ms,
            error=error[:200] if error else None,
        )
