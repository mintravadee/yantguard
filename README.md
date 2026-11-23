# Yant Guard

Enterprise AI governance gateway (Senior Project I). Employees reach external AI
services only through Yant Guard, so IT can control **who** uses **which** model,
see what it **costs**, and keep sensitive data from leaving the company.

Status: Phase 1 (gateway, users, API keys, permissions, request log) works.
Cost tracking, monthly budgets, the prompt security filter and the dashboard are done. The desktop window is in testing; token optimization and memory are next.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and roadmap.

## Project layout

```
yantguard/
├── app/                  Backend (FastAPI)
│   ├── main.py             App entry point
│   ├── gateway/            Provider clients, routes, schemas (Gemini, Groq)
│   ├── governance/         Users, keys, permissions, request log, budgets, security filter (SQLite)
│   └── dashboard/          Dashboard page served at /dashboard (HTML + JS)
├── tests/                Automated tests (pytest)
├── scripts/              Launchers and admin tools
│   ├── run_gateway.bat     Start the server (Windows, double-click)
│   ├── admin.bat           Admin menu: users, keys, permissions, budgets, security
│   ├── open_dashboard.bat  Open the dashboard in the browser
│   ├── run_desktop.bat     Run the desktop app (window)
│   ├── build_desktop.bat   Build YantGuard.exe
│   ├── run_gateway.ps1, admin_menu.py, manage.py, show_log.py
├── desktop/              Desktop app: window + PyInstaller recipe
├── docs/                 Architecture and design notes
├── data/                 Local SQLite database (ignored by Git)
├── .env.example          Template for local settings
└── requirements.txt
```

## Quick start (Windows)

1. Copy `.env.example` to `.env` and fill in `GEMINI_API_KEY` and/or `GROQ_API_KEY`
   (each setting appears once, written as `NAME=value`).
2. Double-click `scripts\run_gateway.bat`. The first run installs packages; the API docs
   open at http://127.0.0.1:8000/docs.
3. Double-click `scripts\admin.bat`, create a user (option 1) and copy the key it prints.
4. Allow the user's department to use a provider (option 7).
5. In `/docs`, click **Authorize**, paste the key, and send a request to
   `POST /api/gateway/request`:

```json
{"provider": "groq", "prompt": "Say hello in one short sentence."}
```

Or from PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/gateway/request `
  -Headers @{"X-API-Key"="yg-YOUR-KEY"} -ContentType "application/json" `
  -Body '{"provider":"groq","prompt":"Hello"}'
```

6. Open the dashboard at http://127.0.0.1:8000/dashboard (or double-click
   `scripts\open_dashboard.bat`). The first time, it asks you to create the administrator
   account. After that you sign in with it. The **Manage** tab lets you add departments and
   users, issue and revoke API keys, choose which providers each department may use, set
   budgets and change the security rules, so the console admin menu is optional.
7. Prefer a normal app window? Double-click `scripts\run_desktop.bat` (see desktop/README.md).

Restart the server after changing `.env` (Uvicorn `--reload` does not reload it).

## Manual setup (macOS / Linux)

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then add your keys
python -m uvicorn app.main:app --reload
python scripts/admin_menu.py    # admin menu
```

## How a request is handled

1. `X-API-Key` must belong to an active user (otherwise `401`).
2. The user's department must be allowed to use the requested provider (otherwise `403`).
   Default is deny.
3. The request is forwarded to the provider. Failures return safe messages: `503` for key
   or model problems, `429` for rate limits, `504` for timeouts, `502` otherwise. Raw provider
   messages and API keys are never returned or logged.
4. Every request is recorded (user, provider, model, tokens, status, latency). The prompt
   text is never stored.

Gemini gets 60 seconds per attempt and retries once after a temporary error; set
`GEMINI_TIMEOUT_SECONDS` (above 0, at most 300) to change it. Provider models are set with
`GEMINI_MODEL` and `GROQ_MODEL`; if a model returns "not found", pick one that is available
for your key. Set `YANTGUARD_REQUIRE_KEY=false` only for quick local experiments.

## Tests

```sh
python -m pytest -q
```

## Roadmap

1. Request log, users and API keys, permissions (done)
2. Cost per request, monthly budgets and alerts (done)
3. Security filter (mask, block) and audit log (done; approval step later)
4. Usage and cost dashboard, built into the gateway at /dashboard (done)
5. Desktop application shell
6. Token optimization (cheaper-model routing)
7. Memory system (semantic search of past work)
