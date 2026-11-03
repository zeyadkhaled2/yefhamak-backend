# Brief handoff log

## 2026-11-03 — PostgreSQL integration tests
- Added opt-in assertion-based suite and `python -m tests.integration` runner. Explicit loopback TEST_DATABASE_URL/test DB name required; no .env fallback or remote target. Migrates a disposable DB, resets its application tables, and reuses the demo seed per test.
- CI adds PostgreSQL 16 service after offline tests. Covers last-item races, release/expiry, order confirmation/rollback, seller isolation, durable replay/concurrent claims. Model access forbidden. Neon and local app data are untouched; no local Docker installation required.
- Guide: `docs/database-tests.md`; hosted test output saved as postgres-test-results artifacts (14 days).
- Inspection for the isolation tests found reservation creation checked the variant's seller but not the conversation's seller. Added an atomic same-seller conversation condition before changing stock; the new test asserts cross-seller attachment is refused.

## 2026-11-01 — CI (plan step 1)
- Added GitHub Actions checks on pushes, PRs, and manual dispatch. Backend: Python 3.12 compilation + offline unit suite; frontend: Node 24 locked install + tests + production build. Read-only permissions, pinned action commits, timeouts, cancel superseded runs, test-log artifacts retained 14 days.
- No model keys, real DB credentials, seeding, live evaluations, or external contact submissions. PostgreSQL concurrency integration tests and Docker remain later work. CI reports failures but does not gate direct main pushes/Vercel deployment.
- Backend setup/docs: `requirements-dev.txt`, `docs/ci.md`; frontend has a matching guide and `npm test` script.
- First hosted runs passed: backend `41345468393`, frontend `41345478224`; both log artifacts uploaded successfully. Evidence saved in `docs/testing/2026-11-01-ci-runs.json`. Local verification also passed: 37 backend tests, 13 frontend tests, production build; zero model calls or real DB access.

## 2026-11-01 — Public GitHub repositories
- Both `zeyadkhaled2/yefhamak-backend` and `zeyadkhaled2/yefhamak` changed from private to public and verified via GitHub API. Reviewed publishable branch/tag history for configured local secrets and common credential patterns; no findings. Local `.env` remains ignored.
- Discussed CI/Docker as follow-up learning work; no workflows or containers added in this step. Prioritize offline CI, then isolated PostgreSQL integration tests; container packaging can follow. Keep real LLM calls out of default CI.

## 2026-11-01 — Frontend/backend integration (plan step 2)
- Frontend now has explicit Mock/Live modes. Live uses local backend connection, restores DB history, displays real paginated/filterable orders and multi-item details. Read-only seller actions; no simulated mutations in Live mode.
- Demo access key stays in tab memory; never saved in browser storage/build environment. IDs/pending message text use origin-scoped sessionStorage. Mock data remains separate. No automatic model retries; explicit safe same-request checks and rate-limit/error notices.
- Added `GET /api/demo/status` and required message `request_id`. Added durable `chat_requests` claims/cached replies, payload-conflict protection, unique in-flight claim per conversation. Interrupted actions stay blocked rather than being executed again.
- Migration `c68a9e315f22` applied additively to configured DB, local demo key added to ignored `.env` without printing it, live sending remains disabled by default.
- Real-database API smoke passed with one synthetic chat/two messages, verified persistent duplicate replay, zero model calls, no inventory/order changes. See saved output under `docs/testing`; frontend checks/build and browser connection/disabled-sending verified. Preserve evidence for later recordings/portfolio.
- Final checks: 37 backend tests, 13 frontend tests, frontend production build, real frontend-client-to-local-backend status/order read, real PostgreSQL replay smoke, migration SQL generation. Live model reply quality remains untested while quota is limited.

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
