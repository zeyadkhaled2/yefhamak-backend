# Yefhamak

[![Backend CI](https://github.com/zeyadkhaled2/yefhamak-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/zeyadkhaled2/yefhamak-backend/actions/workflows/ci.yml)

A conversational shopping assistant for a small Egyptian clothing store. An LLM interprets customer messages and calls backend tools to search products, reserve inventory, and create orders from store data.

The goal is a local CV/demo MVP. The separate frontend checkout (`D:\yefhamak`) has Mock/Live modes for browser chat at `/demo` and seller orders at `/seller/orders`. Live mode connects explicitly to this backend running locally. WhatsApp integration and public backend deployment are deferred.

## Features

- Catalog search with Arabic, English, and Franco-Arabic normalization and clarification for ambiguous products.
- Stock reservations with availability checks, expiration support, and protection against competing reservations.
- Order preview and confirmation, customer detail validation, delivery fees, and duplicate-order protection.
- Tool-based agent with conversation history, input filtering, checks for unsupported numbers, and human handoff.
- Saved questions for the shop team when product information is missing.
- Evaluation harness: 36 conversations covering ambiguity, multilingual input, reservations, order flow, honesty, and safety.
- Empty provider responses retried up to three attempts; error traces include crash locations. Evaluations separate API errors from code failures and stop on daily quota exhaustion.

Guardrails reduce errors; live validation of the full evaluation suite remains incomplete.

## Architecture

```text
Terminal chat / evaluation cases
              |
          Agent loop ---- OpenRouter model (tool calling)
              |
       Validated tool calls
              |
 Catalog / inventory / orders ---- PostgreSQL (Neon)

FastAPI currently exposes health checks and API documentation.
```

Stack: Python, FastAPI, SQLAlchemy, PostgreSQL/psycopg, Alembic, Pydantic Settings, and the OpenAI Python client targeting OpenRouter.

## Project layout

```text
app/
  main.py              FastAPI entry point
  api/routes/          HTTP endpoints
  core/                Settings and environment configuration
  db/                  Declarative base and database sessions
  models.py            SQLAlchemy tables
  services/            Catalog, inventory, and order business rules
  agent/               Model loop, prompts, tools, and guardrails
  demo/                Demo store seed and shared fixtures
scripts/               Terminal chat, seller inbox, and provider probe
evals/                 Live model conversation cases, checks, and runner
tests/
  unit/                Offline tests discovered by unittest
  integration/         Manually invoked checks against the demo database
alembic/               Database migration environment and revision history
docs/                  Historical test notes
eval_results/          Generated model evaluation reports
UPDATES.md             Brief implementation handoff log
```

Routes call application logic; store rules stay in `services/`, and model orchestration stays in `agent/`. Demo commands and checks are outside runtime code. Run all module commands from the repository root.

## Setup

Run `docker compose up -d --build --wait` to start FastAPI and local PostgreSQL together. See [local Docker setup](docs/local-database.md) for the first-time seed and frontend connection. Live chat is off by default.

Use Python 3.10+ and a PostgreSQL database (configured for Neon). From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `.env.example` to `.env` in the project root and fill in your credentials:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
DIRECT_URL=postgresql://USER:PASSWORD@DIRECT_HOST/DATABASE?sslmode=require
OPENROUTER_API_KEY=your-key-here
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
```

`DIRECT_URL` is optional; migrations prefer it when supplied. The API key is required for live chat and model evaluations. Keep `.env` private; it is excluded from Git.

```powershell
alembic upgrade head
python -m app.demo.seed
python -m scripts.chat --new
```

**Seeding resets Demo Store data, including previous chats and orders. Use a dedicated demo database.** Type `exit` to leave chat; omit `--new` to continue the last eligible CLI conversation. Debug output shows tool calls.

Start the API separately:

```powershell
uvicorn app.main:app --reload
```

- [Health](http://127.0.0.1:8000/health)
- [Database health](http://127.0.0.1:8000/health/db)
- [API documentation](http://127.0.0.1:8000/docs)

Conversation, history, chat, connection status, and seller-order read/confirm/cancel endpoints are available under `/api/demo`. They require a separate `DEMO_API_KEY`; live sending defaults to disabled (`LIVE_CHAT_ENABLED=false`) to preserve model quota. The frontend can connect via its Live mode while Mock mode remains quota-free. Sending requires migration `c68a9e315f22` (`alembic upgrade head`) for durable request deduplication. See [API setup, endpoint contracts, and local examples](docs/api.md).

## Checks without model requests

GitHub Actions runs offline tests plus PostgreSQL integration tests on every push and pull request, without model keys or access to the real application database. PostgreSQL starts as a disposable CI service. See [CI workflow and saved results](docs/ci.md) and [database test coverage/safety](docs/database-tests.md). For local development, install test dependencies with `pip install -r requirements-dev.txt`.

These commands use no OpenRouter quota or database connections:

```powershell
python -m unittest discover -s tests -v
```

The regression tests mock the provider and database. They check empty-response retries, crash locations, error classification, immediate daily-limit stopping, and saving partial results. They import project configuration, so a valid `.env` is still needed.

The same command also runs guardrail checks and HTTP health checks with a mocked database. Database integration checks below are not executed by test discovery.

These checks require the demo database and modify its data, but do not call the model:

```powershell
python -m tests.integration.check_catalog_inventory
python -m tests.integration.check_orders
```

To inspect orders and unanswered shop questions:

```powershell
python -m scripts.show_inbox
```

## Live evaluations and limited quota

**Each evaluation case resets the Demo Store. These commands consume API requests.**

For a small tool-calling capability probe, run `python -m scripts.check_provider` (also consumes API requests).

```powershell
# Prioritize the previously interrupted order flow
python -m evals.run --case full-order

# Run small groups as quota allows
python -m evals.run --category reservation
python -m evals.run --quick

# Full suite when sufficient quota is available
python -m evals.run
```

One conversation can make several model requests because tool rounds call the model again. Empty-response retries and SDK retries can add requests. Avoid repeated full-suite runs while quota is limited.

Reports in `eval_results/` include transcripts, token usage, latency, and errors. On a daily `per-day` rate-limit error, the runner stops after the affected turn and saves partial results and remaining runs. Resume manually using `--case` or `--category`; automatic report resumption is not implemented.

API problems are excluded from graded pass rates. Code crashes count as failures, including when the same case also has an API error. Report skipped cases alongside pass counts.

## Validation status

- Saved live quick run: **7 passed, 1 error out of 8 cases** (`eval_results/eval-20261101-154630.json`). The older harness labeled every captured exception as infrastructure, so the skipped TypeError is not a confirmed provider fault.
- The subsequent full run was interrupted by errors and the daily request limit. All 36 cases have not been validated.
- Step 5b: **7 offline regression tests passed**. These verify error handling, not conversational quality.

## Next steps

1. Validate live order flow, then remaining categories in small batches after quota resets; investigate real failures.
2. Exercise the connected Live UI when model quota permits; Mock mode and connection/history/order checks remain available without model requests.
3. Complete live integration checks and record a short demo with documented evaluation coverage.

Paid API access is optional for continued development. Backend checks, UI development, and documentation can proceed without model calls. Real requests are still needed to validate model behavior and demonstrate the live assistant.

See [UPDATES.md](UPDATES.md) for the brief implementation handoff log.
