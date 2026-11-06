# Yefhamak | يفهمك — Backend

[![Backend CI](https://github.com/zeyadkhaled2/yefhamak-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/zeyadkhaled2/yefhamak-backend/actions/workflows/ci.yml)

An Egyptian Arabic shopping-assistant MVP that turns customer conversations into stock reservations and reviewable orders. The model interprets requests; Python services and PostgreSQL enforce inventory and order rules.

**[Watch the full live-chat demo](https://www.youtube.com/watch?v=gR0TXw6iMhM)** · **[Try the public mock demo](https://yefhamak.vercel.app/demo)** · **[Frontend repository](https://github.com/zeyadkhaled2/yefhamak)**

[![Watch the Yefhamak demo on YouTube](https://img.youtube.com/vi/gR0TXw6iMhM/hqdefault.jpg)](https://www.youtube.com/watch?v=gR0TXw6iMhM)

The recording demonstrates the live chat experience. Store-document RAG was added afterward; its separate live checks and traces are linked below. The public frontend offers a scripted mock experience. Live mode connects the frontend to your locally running backend and configured model.

## What it does

- **Tool-based shopping conversations:** Arabic, English and Franco-Arabic catalog normalization, product clarification, and model-driven tool calls.
- **Inventory correctness:** short-lived reservations, availability checks, expiry/release support, and concurrent reservation protection.
- **Order lifecycle:** customer details, delivery fees, preview before creation, duplicate-request protection, and seller confirmation/cancellation with transactional stock changes.
- **Store-document RAG:** seller-scoped lexical retrieval over imported Markdown/text documents, Arabic/English normalization and synonyms, and source references appended to replies.
- **Fallbacks:** saved questions for missing store information, human-handoff state, input filtering and unsupported-number checks.
- **Repeatable development:** Docker Compose, Alembic migrations, offline tests, and isolated PostgreSQL tests in GitHub Actions.

## Architecture

```text
Next.js frontend (local Live mode)
             |
     FastAPI /api/demo — DEMO_API_KEY
             |
         Agent loop <----> OpenRouter model
             |
      Validated tool calls
             |
 Catalog / reservations / orders / knowledge
             |
     PostgreSQL (local Docker)
```

Application services enforce stock and order actions. Knowledge retrieval selects up to three passages of at most 1,000 characters each, then passes their text to the model. Each reply includes references to the documents consulted. See [RAG implementation and import guide](docs/rag.md).

**Stack:** Python, FastAPI, SQLAlchemy, PostgreSQL, Alembic, Pydantic, OpenRouter, Docker Compose, GitHub Actions. PostgreSQL can also be configured on Neon; Compose creates an independent local development database.

## Run locally

Prerequisites: Git and Docker Desktop with the Linux engine running. Run these commands in a fresh backend checkout:

```powershell
git clone https://github.com/zeyadkhaled2/yefhamak-backend.git
cd yefhamak-backend
```

Create a local `.env` file in the repository root. Set `DEMO_API_KEY` to your own random access key and `COMPOSE_LIVE_CHAT_ENABLED=false` for initial setup. Compose configures the local database connection automatically. Configuration stays local and is excluded from Git.

```powershell
docker compose up -d --build --wait
# First setup only: creates demo products and stock.
docker compose exec api python -m app.demo.seed
```

**Run seed only on first setup: repeating it resets the demo store, including chats and orders.** The named Docker volume preserves data across restarts.

- API docs: http://127.0.0.1:8000/docs
- Database health: http://127.0.0.1:8000/health/db
- PostgreSQL from host tools: `127.0.0.1:5433`; API-to-database inside Compose: `db:5432`.

To send real chat messages, set `OPENROUTER_API_KEY` and `COMPOSE_LIVE_CHAT_ENABLED=true` in `.env`, then rerun the Compose startup command. `LLM_MODEL` selects the OpenRouter model; the default is a free Nemotron model whose availability/quota depends on the provider. Keep the OpenRouter key in the backend configuration; the frontend uses the separate demo access key.

Start the [frontend locally](https://github.com/zeyadkhaled2/yefhamak#run-locally), open `/demo`, select **Live**, and connect using `http://127.0.0.1:8000` plus `DEMO_API_KEY`. Model quota is used when sending chat messages; connection, history and order browsing are quota-free.

For host-Python development, service lifecycle and database details, see [local setup](docs/local-database.md). To add the bundled demo care guide without reseeding, follow [document import](docs/rag.md#import-locally-with-docker).

## Tests and evidence

The last saved backend run on **2026-11-06** passed **45 unit tests and 29 PostgreSQL integration tests**. The linked outputs document the exact regression cases and live scenarios verified.

- [Unit test output](docs/testing/2026-11-06-rag-unit.txt)
- [PostgreSQL test output](docs/testing/2026-11-06-rag-postgres.txt): concurrent reservations, expiry, idempotency, order transitions, seller isolation, and knowledge retrieval.
- [Live order verification](docs/testing/2026-11-04-live-order.md): one checkout scenario through seller confirmation.
- [RAG verification](docs/testing/2026-11-06-rag.md): two real-model questions, with [saved tool traces](docs/testing/2026-11-06-rag-live.jsonl).

To run tests on the host, install Python 3.12 and create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
# Host Python connects through the published local PostgreSQL port.
$env:DATABASE_URL = 'postgresql+psycopg://yefhamak:local-dev-only@127.0.0.1:5433/yefhamak'
python -m unittest discover -s tests/unit -v

# Create the disposable database once; skip if it already exists.
docker compose exec -T db createdb -U yefhamak yefhamak_test
$env:TEST_DATABASE_URL = 'postgresql+psycopg://yefhamak:local-dev-only@127.0.0.1:5433/yefhamak_test'
python -m tests.integration
```

Integration tests reset only the explicitly selected disposable test database and forbid model calls. GitHub Actions runs both suites on pushes and pull requests using its own PostgreSQL service. See [CI](docs/ci.md) and [database-test safeguards](docs/database-tests.md).

The live evaluation harness contains 36 conversation scenarios. Live scenarios are evaluated in small batches as model quota allows. `python -m evals.run --case full-order` runs one live scenario, **resets Demo Store data**, and consumes model quota. Tool rounds/retries can use multiple requests per message; daily-limit failures save partial results and stop the run.

## Repository guide

- `app/api/` — protected demo chat, history, status and seller-order endpoints.
- `app/agent/` — prompt, tool registry, model loop and guards.
- `app/services/` — catalog, inventory, orders, request deduplication and retrieval.
- `app/models.py`, `app/db/`, `alembic/` — database models, sessions and migrations.
- `app/knowledge.py` — trusted-operator document import CLI.
- `app/demo/` — synthetic store fixtures and sample knowledge.
- `tests/unit/`, `tests/integration/` — offline and isolated PostgreSQL tests.
- `evals/`, `scripts/` — model evaluations and developer utilities.
- `docs/`, [UPDATES.md](UPDATES.md) — setup, contracts, evidence and brief handoff history.

## Project scope

Yefhamak focuses on the complete browser shopping workflow: customer questions, grounded product answers, stock reservations, order creation and seller review. The demo runs locally with a shared access key and synthetic store data. Human-handoff state and saved questions support seller follow-up.

Detailed behavior, evaluation coverage and operational considerations are documented in the [API guide](docs/api.md), [RAG guide](docs/rag.md) and linked test records.
