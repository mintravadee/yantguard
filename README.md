# yantguard
Senior Project I 

## Run the gateway

Copy `.env.example` to `.env` when setting up a new checkout, then fill in your
provider API keys. Each setting should contain only one assignment, for example
`GEMINI_API_KEY=your-key`. Restart the server after changing `.env`.
Uvicorn's `--reload` does not reload `.env` changes by default.

The Gemini default is `gemini-3.8-flash`. If an older model returns a "model not
found" error, update `GEMINI_MODEL` in `.env` to a model available for your key.

```sh
.venv/bin/python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs to try the gateway, or send JSON using POST:

```sh
curl http://127.0.0.1:8000/api/gateway/request \
  -H 'Content-Type: application/json' \
  -d '{"provider":"groq","prompt":"Hello"}'
```

GET `/api/gateway/request` returns usage instructions. Generation requires POST.
Provider errors return safe diagnostic messages: 503 for key/access or missing
model configuration, 429 for quota/rate limits, 504 for timeouts, and 502 for
connection failures or other failed/invalid responses. Raw provider messages
and API keys are never included in these errors or gateway logs.

Gemini gets 60 seconds per attempt and retries up to three times after a temporary
server error, connection failure, or timeout, using exponential backoff with jitter.
The gateway allows up to 252 seconds in total, including retry delays and client
cleanup. Key/access errors, missing models,
and quota errors are returned immediately.

A persistent upstream 503 returns `Retry-After: 30`. Keep your existing API key:
replacing it does not fix temporary provider unavailability. Retry later or select
another model available to your project and restart the server.

To adjust the per-attempt timeout, set `GEMINI_TIMEOUT_SECONDS=60` in `.env`
(greater than 0 and at most 300), then restart the server. Clients and reverse
proxies should allow at least the full gateway timeout when waiting for a response.
