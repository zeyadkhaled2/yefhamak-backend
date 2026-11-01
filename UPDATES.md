# Brief handoff log

## 2026-11-01 — Backend endpoints (plan step 1)
- Added `/api/demo` conversation creation/metadata/history/send and read-only seller order list/details. Uses existing models and agent; no schema migration. Demo Store scoping, validated/paginated contracts, decimal-string money, hidden agent state/provider traces.
- Separate bearer `DEMO_API_KEY` required. `LIVE_CHAT_ENABLED=false` by default prevents accidental quota use. CORS includes local frontend and `https://yefhamak.vercel.app`. Run one local worker; overlapping sends return 409. Durable idempotency and frontend integration remain next.
- API documentation: `docs/api.md`; saved offline results: `docs/testing/2026-11-01-backend-api.txt`. Tests use mocked DB/model; no live API calls, database resets, or live DB verification.
- Verification: all 30 offline tests passed; Python compilation and diff whitespace checks passed.
- Preserve docs/testing evidence for later demos, recordings, and portfolio. Portfolio/videos deferred; backend stays local for now and hosted frontend remains mock mode.

## 2026-11-01 — Structure optimization
- Grouped settings under `app/core`, database base/session under `app/db`, HTTP routes under `app/api/routes`, demo seed/fixtures under `app/demo`.
- Moved developer commands to `scripts`, LLM evaluations to `evals`, offline tests to `tests/unit`, explicit database checks to `tests/integration`, and historical notes to `docs`.
- Removed evaluations' dependency on a manual check module; shared conversation fixture now lives under `app/demo`. Existing guard checks are discoverable unittest assertions.
- Updated all imports, Alembic environment, README commands/layout; added safe `.env.example` and ignored future generated transcripts. Database schema, `/health`, `/health/db`, and `uvicorn app.main:app` are unchanged. Old CLI module names have been replaced by documented commands.
- No live model requests or database mutations used for verification.
- Verification passed: 11 offline tests, 9 phone/area checks, 15 module imports, Python compilation, eval CLI help, Alembic head lookup and offline migration SQL generation.

## 2026-11-01 — Frontend mock workspace
- Follow-up: demo screens now reuse landing brand tokens, Cairo typography, exact teal/cream/navy/yellow palette, and existing logo. Mock flow remains temporary; can connect locally before backend hosting, while public Vercel integration needs an online backend.
- Frontend is a separate checkout at `D:\yefhamak`. Added `/demo` chat and `/seller/orders` with scripted Arabic order flow, browser-local persistence, seller filters/details/status actions, responsive layout, and landing demo link. No live backend/API integration yet; see its `FRONTEND_UPDATES.md`.
- Verified frontend production build, 7 mock-flow tests, and browser order/review/search flow. Patched its existing Next.js 16.4.0 to 16.4.3; install audit reports zero vulnerabilities. No OpenRouter requests used.

## 2026-11-01 — README refreshed
- Documented current features, architecture, setup, CLI/API entry points, offline checks, quota-conscious live evaluation, honest validation status, and MVP next steps. Mock UI responses are a proposed development approach, not an existing feature.

## 2026-11-01 — Step 5b applied
- Scope: local CV/demo MVP; deployment and WhatsApp integration deferred.
- Applied supplied Step 5b files to `app/agent/loop.py` and `app/evals/run.py`.
- Empty provider responses get at most 3 attempts, then `EmptyProviderResponse`; error traces include file/line.
- Eval API errors are skipped; code crashes fail, including when both occur in one case.
- Daily `per-day` rate limit stops immediately after the affected turn and stops the suite; partial results and remaining runs (including interrupted case/repeats) are saved to JSON.
- Added 7 offline regression checks in `tests/test_provider_resilience.py`; all passed. Eval CLI help and diff whitespace check passed. No live API calls or database resets performed.
- Prior evidence: user supplied quick run had 7 passed / 1 error; full 36-case validation remains incomplete. Empty-response cause of earlier TypeErrors is suspected, not proven.
- Next: after quota reset, run `.\.venv\Scripts\python.exe -m evals.run --case full-order`, then small categories across available quota; investigate actual crashes/failures. Evals reset Demo Store data. Then build local chat + seller orders UI, improve README/architecture, record short demo.
- Offline verification: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
