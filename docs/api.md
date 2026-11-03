# Local demo API

This API connects the existing store and agent to the frontend's explicit Live mode. Mock mode remains browser-local and calls no backend. This is a single Demo Store workspace, not a multi-user production seller API.

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
- `GET /api/demo/status` — verify the key and Demo Store, and read the `live_chat_enabled` flag; no model call.
- `GET /api/demo/conversations/{id}` — conversation metadata; excludes internal agent state.
- `GET /api/demo/conversations/{id}/messages?limit=50&offset=0` — messages in chronological order, paginated from the oldest. Returns `items`, `limit`, `offset`; each message has `id`, `direction` (`IN` or `OUT`), `body`, `created_at`. Increase offset to page forward; limit is 1–100.
- `POST /api/demo/conversations/{id}/messages` — send `{"request_id":"<UUID>","text":"عايز هودي اسود"}` through the existing agent. Requires `LIVE_CHAT_ENABLED=true` and a working OpenRouter key. Nonblank text only, at most 600 characters; extra fields are rejected. Reuse the exact UUID/text only when checking/retrying this same request.
- `GET /api/demo/orders?status=PENDING&q=Ahmed&limit=25&offset=0` — latest orders first, optional status/name/phone filter. Returns `items`, `total`, `limit`, `offset`; limit is 1–100. Status values are `PENDING`, `CONFIRMED`, `CANCELLED`. Search uses literal substrings, not SQL wildcard patterns.
- `GET /api/demo/orders/{id}` — order details including product name/code, variant color/size, quantity, and saved unit price.

Order money fields (`unit_price`, `delivery_fee`, `total`) are decimal **strings** in EGP to preserve precision. The real API's `CONFIRMED` status is not the mock UI's `reviewed` label. Reset endpoints are not exposed.

Seller review actions (same bearer key, no body, no model calls):

- `POST /api/demo/orders/{id}/confirm`: PENDING -> CONFIRMED. Subtracts item quantities from stock and reserved atomically. Returns updated OrderOut without items.
- `POST /api/demo/orders/{id}/cancel`: PENDING or CONFIRMED -> CANCELLED. Pending releases reserved quantities; confirmed returns sold stock. Linked reservations become RELEASED. Returns updated OrderOut without items.

Cancellation is final; cancelled orders cannot reopen. Repeating the current terminal action returns 200 with no inventory effects. Order-row locks serialize concurrent reviews; inventory and status commit together or roll back together. Customer confirmation in chat creates a PENDING order with CONFIRMED reservations; seller confirmation is the later step that consumes those units. No migration needed. No notifications, payment, shipping, or returns workflow is implemented.

Errors: 404 `order_not_found` for absent/other-seller orders; 409 `invalid_order_transition` for confirmation after cancellation; 409 `order_inventory_conflict` for inconsistent items/linked holds or counters (nothing saved). Inspect inconsistent data before retrying. The Live details dialog supports these actions, disables controls while busy, asks for a second cancellation click, and refreshes the list. A failed response triggers a best-effort status read, never an automatic mutation retry. Close/reopen details to inspect the latest status; repeating the same action is safe.

The web demo reuses the existing `WHATSAPP` customer channel enum with a `web-demo-` identifier; it does not send WhatsApp messages. Step 2 adds the `chat_requests` table and migration `c68a9e315f22`; run `alembic upgrade head` before using message sending. This migration was applied to the current configured database on 2026-11-01 without resetting data.

## Message outcomes and retries

The send response contains `request_id`, `conversation_id`, `status`, `reply` (nullable), `outcome`, and `rate_limited`.

- `reply`: normal response, including canned guard responses.
- `handoff`: the conversation is handled by a person; the agent can return no reply.
- `provider_error`: a recognized provider/network/empty-answer error occurred. `rate_limited=true` identifies rate limits; raw provider error details are not exposed.
- `application_error`: an error captured by the agent was not classified as a recognized provider problem.

Provider/application outcomes return HTTP 200 because the existing agent saves the input and a fallback reply. This does **not** mean the requested shopping action succeeded. Read `outcome`; do not automatically resend. Tools may have committed a reservation or order before a later model error. Inspect history and orders before deciding what to retry.

Closed conversations return 409. A durable claim is committed before running the agent; completed request IDs replay the saved response without running tools/model calls again. Reusing an ID with different content/conversation returns 409 `request_id_reused`. An unfinished same request returns 409 `request_in_progress`; another pending request in the conversation returns 409 `conversation_busy` (also enforced by a partial unique database index). The in-process guard rejects overlapping same-worker sends early. Continue running one worker for the local MVP.

If the process crashes or saving the final result fails, the durable claim stays unfinished: the system deliberately does not replay uncertain actions. Inspect history/orders. The Live UI can check the same request again, or explicitly leave that conversation after a warning. Leaving does not cancel backend actions or clear its claim. Recovery of an interrupted claim is an operator task after inspecting persisted effects; never delete a claim and blindly resend. A completed provider-error response is also cached: another attempt to ask the model is a new, intentional request, not a transport retry.

## Errors

- 401 `invalid_demo_api_key`: missing/wrong bearer key.
- 503 `demo_api_key_not_configured`: set a local access key.
- 503 `demo_store_not_seeded`: seed a dedicated demo database if appropriate.
- 503 `live_chat_disabled`: intentionally prevents model requests by default.
- 404 `conversation_not_found` / `order_not_found`: absent or outside this seller's workspace.
- 409 `conversation_closed` / `conversation_busy` / `request_in_progress` / `request_id_reused`.
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

Only enable live chat when intentionally using available model quota. There is no model-backed mock endpoint; frontend Mock mode remains the quota-free UI path.

## Frontend connection

In the frontend (`D:\yefhamak`), run `npm run dev`, open `/demo` or `/seller/orders`, select **Live · your backend**, and enter `http://127.0.0.1:8000` and your local `DEMO_API_KEY`. The local key is configured in the ignored backend `.env`; never use your OpenRouter key here. Connection, history, orders, and seller review actions need no LLM quota. Message input is disabled when the backend reports live sending is off. Restart the backend after changing `.env` settings.

The access key stays only in JavaScript tab memory (and the password input while mounted). It is reused across client-side chat/seller navigation, and forgotten on reload or Disconnect. Conversation IDs and uncertain request IDs/text are stored in sessionStorage, scoped to the backend origin, to restore history and safely check an interrupted send. Use synthetic customer details. Mock order storage is separate. In Live mode orders use real backend statuses (`PENDING`, `CONFIRMED`, `CANCELLED`) and multi-item details; seller actions persist real backend changes; database reset is not exposed.

## Frontend access and hosting

CORS allows `http://localhost:3000`, `http://127.0.0.1:3000`, and `https://yefhamak.vercel.app` by default. Override `CORS_ORIGINS` with a JSON list if needed. CORS is not authentication and does not make a local backend public.

Prefer the local frontend for integration with the local backend. The deployed Vercel frontend remains usable in mock mode; connecting an HTTPS public page to a loopback backend can encounter browser private-network/mixed-content restrictions. Other visitors cannot access the backend on your machine. Public deployment, per-user authentication, and real customer data are later work.

## Saved evidence and follow-up

Run `python -m unittest discover -s tests -v` for offline verification. See [step 1 results](testing/2026-11-01-backend-api.txt) and [step 2 results](testing/2026-11-01-step2-backend.txt). Most tests mock database/model calls; the durable-claim tests use an isolated local SQLite table. These tests do not validate live model quality.

An explicit `python -m scripts.check_api` check exercises the configured real database through FastAPI, creates one synthetic conversation/two messages, verifies guard-blocked input and duplicate replay, and forbids model calls with a test stub. It never resets the store or changes inventory/orders. [The recorded run](testing/2026-11-01-live-database-api.txt) passed. Do not run this as a production health probe because it writes a synthetic chat.

Keep docs/testing evidence for future recordings and portfolio work. No video recording or portfolio work is part of this step. Next: validate actual model conversations when quota permits, containerize FastAPI and plan multi-user access controls.
