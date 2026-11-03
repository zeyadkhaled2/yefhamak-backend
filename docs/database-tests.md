# PostgreSQL integration tests

Run command: `python -m tests.integration`. Assertions live in `tests/integration/test_postgres.py`; the runner and safety checks are in `tests/integration/__main__.py` and `database.py`. The older `check_*.py` scripts remain manual utilities and do not decide CI pass/fail.

## How CI runs them

After offline tests pass, the `PostgreSQL integration tests` job starts its own PostgreSQL 16 service with an empty `yefhamak_test` database and disposable credentials. No Neon connection, model key, or GitHub secret is used.

The runner selects the explicit test URL before importing application settings, applies real Alembic migrations, and runs the tests. Each test truncates only that disposable database's application tables and reuses `app/demo/seed.py` for predictable products/stock. Alembic's version table is retained. All sessions and concurrent workers use the guarded test engine. The database disappears with the job.

Coverage:

- Arabic/Franco search and ambiguity.
- Two connections competing for the last item, repeated three times.
- Concurrent/idempotent release; expiry without releasing active or confirmed holds.
- Invalid quantities and seller isolation for reservations, catalog, conversations, and orders.
- Multi-item preview/confirmation, totals, duplicate-order prevention, and item details.
- Atomic rollback when a reservation expires before order creation.
- Durable request replay across sessions and competing request claims.

Model access is blocked by a test stub. These checks establish PostgreSQL behavior for the tested cases, not model quality or every possible timing/interleaving.

## Optional local execution

You do not need a local PostgreSQL/Docker installation to use GitHub's checks. Later, create a dedicated disposable database and run:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@127.0.0.1:5432/yefhamak_test'
python -m tests.integration
```

**Application data in that test database is reset before each test.** The runner does not create/drop databases. It refuses missing URLs, remote hosts, non-PostgreSQL drivers, ordinary database names, and connection-override query parameters. Only explicit loopback hosts and database names `yefhamak_test` or `yefhamak_test_*` are accepted. It never falls back to `DATABASE_URL`, `DIRECT_URL`, or `.env`. Unit tests verify those refusal rules without connecting.

Ordinary discovery skips PostgreSQL tests unless opted in through the dedicated runner. Do not manually set its internal flag; the runner sets environment values before database imports.

## Evidence

Open **Actions → Backend CI → PostgreSQL integration tests**. The `postgres-test-results` artifact retains output for 14 days, including failures. Dated records under `docs/testing/` preserve verified runs for later demo/portfolio use.
