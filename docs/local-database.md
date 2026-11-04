# Local FastAPI and PostgreSQL with Docker

Docker Desktop must be running. From the repository root:

```powershell
docker compose up -d --build --wait
```

Compose starts PostgreSQL and waits for it to become healthy. The API container
applies Alembic migrations, starts FastAPI, and checks `/health/db`. It connects
to `db:5432` on the Compose network. Open http://127.0.0.1:8000/docs or
http://127.0.0.1:8000/health/db. Stop any host FastAPI process using port 8000
before starting the API container.

On a fresh local volume, load the Demo Store once:

```powershell
docker compose exec api python -m app.demo.seed
```

Skip seeding if the store already exists. Rerunning it resets Demo Store chats
and orders. Compose reuses the existing database volume.

The frontend connects to `http://127.0.0.1:8000` using `DEMO_API_KEY` from your
local `.env` or shell environment. Compose passes selected settings at runtime.
Both database URLs always point at the Compose database. Live chat starts off.
When ready to use model quota, configure `OPENROUTER_API_KEY` and set
`COMPOSE_LIVE_CHAT_ENABLED=true` in `.env`, then rerun the Compose startup command.

## Run FastAPI from host Python instead

```powershell
docker compose stop api
docker compose up -d --wait db
.\scripts\local-db.ps1 -m alembic upgrade head
# First setup only; repeating seed resets local Demo Store chats/orders.
.\scripts\local-db.ps1 -m app.demo.seed
.\scripts\local-db.ps1 -m uvicorn app.main:app --reload
```

Create `.venv` and install `requirements-dev.txt` first on a new machine.

`local-db.ps1` temporarily overrides BOTH database URLs for its child Python process,
forces live chat off, and replaces the provider key with a dummy value. It restores
the previous environment afterward. Your existing `.env`/Neon credentials remain
unchanged. HTTP demo access still uses the separate `DEMO_API_KEY` from `.env`.
Do not run the raw seed/migration commands expecting them to use Docker: without
the wrapper they use your normal configuration, which may point to Neon.

PostgreSQL listens only on this machine at `127.0.0.1:5433`; inside the container
it listens on port 5432. The public `local-dev-only` password is for this local
development service only, never an internet deployment.

The named volume `yefhamak_postgres_data` stores data independently of the container.
On the current machine Docker's disk is at `E:\DockerData\DockerDesktopWSL`.
Cloning this repository elsewhere creates a separate empty database; Neon does
not synchronize with it. Migrations create tables; seed inserts demo products.

## Stop or inspect the stack

```powershell
docker compose ps
docker compose logs api
docker compose stop        # Stop services, retain data
docker compose down        # Remove containers/network, retain named volume
```

`docker compose down -v` deletes the database volume and its data. Avoid it unless
you deliberately want to erase the local database. Seeding is also a reset of
Demo Store data, so it is not an everyday startup command.

This is the development database. The destructive integration tests require a
separate explicitly named test database; see [database-tests.md](database-tests.md).
No model requests are needed for migration, seeding, health, or reading orders.
