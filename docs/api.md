# Local demo API

This API connects the existing store and agent to a future frontend integration. It is a single Demo Store workspace, not a multi-user production seller API. The frontend is still in mock mode; this change adds backend endpoints only.

## Run locally

Keep the existing database settings in `.env`. Add a separate local access key and leave live sending disabled:

```dotenv
DEMO_API_KEY=your-random-local-key
LIVE_CHAT_ENABLED=false
```

Generate your own key using `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Do not commit it or confuse it with `OPENROUTER_API_KEY`. Do not put it in public frontend source or a `NEXT_PUBLIC_*` build variable. Swagger's Authorize control accepts this key through the Bearer scheme.

Start from the repository root:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Use one worker for the local MVP. The overlapping-message guard is in-process, not a distributed lock. Do not add `--workers` until message coordination is upgraded.

The Demo Store must already be seeded. If needed, `python -m app.demo.seed` creates it, but **resets its existing chats and orders**. No seeding occurs automatically on server startup or API access.

## Endpoints

All `/api/demo/*` routes require `Authorization: Bearer <DEMO_API_KEY>`. Health endpoints stay public. Seller selection comes from the configured Demo Store name; request bodies cannot select a different seller or customer.

- `POST /api/demo/conversations` — create a fresh anonymous demo customer and conversation; returns 201 with `id`, `status`, and `created_at`. No model call. No request body needed.
- `GET /api/demo/conversations/{id}` — conversation metadata; excludes internal agent state.
- `GET /api/demo/conversations/{id}/messages?limit=50&offset=0` — messages in chronological order, paginated from the oldest. Returns `items`, `limit`, `offset`; each message has `id`, `direction` (`IN` or `OUT`), `body`, `created_at`. Increase offset to page forward; limit is 1–100.
- `POST /api/demo/conversations/{id}/messages` — send `{"text":"عايز هودي اسود"}` through the existing agent. Requires `LIVE_CHAT_ENABLED=true` and a working OpenRouter key. Nonblank text only, at most 600 characters; extra fields are rejected.
- `GET /api/demo/orders?status=PENDING&q=Ahmed&limit=25&offset=0` — latest orders first, optional status/name/phone filter. Returns `items`, `total`, `limit`, `offset`; limit is 1–100. Status values are `PENDING`, `CONFIRMED`, `CANCELLED`. Search uses literal substrings, not SQL wildcard patterns.
- `GET /api/demo/orders/{id}` — order details including product name/code, variant color/size, quantity, and saved unit price.

Order money fields (`unit_price`, `delivery_fee`, `total`) are decimal **strings** in EGP to preserve precision. The real API's `CONFIRMED` status is not the mock UI's `reviewed` label. Order status changes, cancellation, and reset endpoints are intentionally outside this read-only seller step.

The web demo reuses the existing `WHATSAPP` customer channel enum with a `web-demo-` identifier; it does not send WhatsApp messages. No database migration is needed for these endpoints.

## Message outcomes and retries

The send response contains `conversation_id`, `status`, `reply` (nullable), `outcome`, and `rate_limited`.

- `reply`: normal response, including canned guard responses.
- `handoff`: the conversation is handled by a person; the agent can return no reply.
- `provider_error`: a recognized provider/network/empty-answer error occurred. `rate_limited=true` identifies rate limits; raw provider error details are not exposed.
- `application_error`: an error captured by the agent was not classified as a recognized provider problem.

Provider/application outcomes return HTTP 200 because the existing agent saves the input and a fallback reply. This does **not** mean the requested shopping action succeeded. Read `outcome`; do not automatically resend. Tools may have committed a reservation or order before a later model error. Inspect history and orders before deciding what to retry.

Closed conversations return 409. Overlapping sends in the same server worker return 409 `conversation_busy`. Sequential repeated POSTs are not deduplicated; durable message idempotency is a follow-up before frontend automatic retries. Disable the UI send action while a request is pending.

## Errors

- 401 `invalid_demo_api_key`: missing/wrong bearer key.
- 503 `demo_api_key_not_configured`: set a local access key.
- 503 `demo_store_not_seeded`: seed a dedicated demo database if appropriate.
- 503 `live_chat_disabled`: intentionally prevents model requests by default.
- 404 `conversation_not_found` / `order_not_found`: absent or outside this seller's workspace.
- 409 `conversation_closed` / `conversation_busy`.
- 422: invalid UUID, message, enum, search, or pagination input.

## Example without a model call

Enter the same local key configured in `.env`:

```powershell
$demoKey = Read-Host 'Local demo API key'
$headers = @{ Authorization = "Bearer $demoKey" }
$conversation = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/demo/conversations' -Headers $headers
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/demo/conversations/$($conversation.id)/messages" -Headers $headers
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/demo/orders' -Headers $headers
```

Only enable live chat when intentionally using available model quota. There is no model-backed mock endpoint; the existing frontend mock mode remains the quota-free UI path.

## Frontend access and hosting

CORS allows `http://localhost:3000`, `http://127.0.0.1:3000`, and `https://yefhamak.vercel.app` by default. Override `CORS_ORIGINS` with a JSON list if needed. CORS is not authentication and does not make a local backend public.

Prefer the local frontend for integration with the local backend. The deployed Vercel frontend remains usable in mock mode; connecting an HTTPS public page to a loopback backend can encounter browser private-network/mixed-content restrictions. Other visitors cannot access the backend on your machine. Public deployment, per-user authentication, and real customer data are later work.

## Saved evidence and follow-up

Run `python -m unittest discover -s tests -v` for offline verification. See [the saved test output](testing/2026-11-01-backend-api.txt). These tests mock the model and database; they establish HTTP contracts and query scoping, not live PostgreSQL or model quality.

Keep docs and test evidence for future recordings and portfolio work. No video recording or portfolio work is part of this step. Next: connect the frontend while retaining explicit mock/live modes and add durable message idempotency before retry automation.
