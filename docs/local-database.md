# Local PostgreSQL with Docker

Docker Desktop must be running. From the repository root:

```powershell
docker compose up -d --wait db
.\scripts\local-db.ps1 -m alembic upgrade head
# First setup only; repeating seed resets local Demo Store chats/orders.
.\scripts\local-db.ps1 -m app.demo.seed
.\scripts\local-db.ps1 -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/health/db or http://127.0.0.1:8000/docs.
The API runs in the host Python virtual environment; only PostgreSQL is containerized.
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

```powershell
docker compose ps
docker compose stop db      # Stop database, retain data
docker compose up -d --wait db  # Start again
docker compose down        # Remove container/network, retain named volume
```

`docker compose down -v` deletes the database volume and its data. Avoid it unless
you deliberately want to erase the local database. Seeding is also a reset of
Demo Store data, so it is not an everyday startup command.

This is the development database. The destructive integration tests require a
separate explicitly named test database; see [database-tests.md](database-tests.md).
No model requests are needed for migration, seeding, health, or reading orders.
