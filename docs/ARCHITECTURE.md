# Architecture

## Request flow

```
Client / desktop app
        │  POST /api/gateway/request   (X-API-Key header)
        ▼
RequestLogMiddleware  (app/governance/request_log.py)
   1. authenticate the key            → 401 if invalid
   2. check department → provider     → 403 if not allowed
   3. forward to the gateway route    (app/gateway/routes.py, Gemini / Groq clients)
   4. write one row to the request log
        ▼
External AI provider
```

The governance layer wraps the gateway routes, so the provider code and the
governance code can be developed independently.

## Packages

| Path | Responsibility |
|---|---|
| `app/gateway/` | Provider clients, request and response schemas, error mapping |
| `app/governance/db.py` | SQLite connection and schema |
| `app/governance/users.py` | Departments, users, API keys, provider permissions |
| `app/governance/request_log.py` | Middleware: key check, permission check, logging |
| `scripts/` | Launchers and admin tools |
| `app/dashboard/` | Usage and cost dashboard served by the gateway at `/dashboard` (plain HTML/JS, no extra server) |
| `desktop/` | Desktop app: starts the gateway and shows the dashboard in a window (pywebview); PyInstaller recipe |

## Data (SQLite, `data/yantguard.db`)

| Table | Purpose |
|---|---|
| `departments`, `users` | Who may use the gateway |
| `api_keys` | Hashed keys (SHA-256), prefix for display, revoked flag |
| `department_providers` | Which providers a department may use (default deny) |
| `requests` | One row per gateway request: user, provider, model, tokens, status, latency |

Prompt text and raw API keys are never stored.

## Next

Cost per request (price table), budgets and alerts, security filter with audit log,
token optimization, memory system.
