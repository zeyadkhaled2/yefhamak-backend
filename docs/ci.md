# Continuous integration

[Backend CI runs](https://github.com/zeyadkhaled2/yefhamak-backend/actions/workflows/ci.yml)

GitHub Actions checks every push and pull request. You can also select **Actions → Backend CI → Run workflow**. The workflow is `.github/workflows/ci.yml`.

On a standard Ubuntu runner with Python 3.12 it:

1. Installs `requirements-dev.txt` (application dependencies plus explicit HTTP test support).
2. Compiles Python modules to catch syntax errors.
3. Runs `python -m unittest discover -s tests/unit -v`.
4. Saves test output as the `backend-test-results` artifact for 14 days, including when tests fail.

Shell pipeline failures propagate to the job, so a failing test cannot be hidden by saving its output. Actions are pinned to exact commits, repository access is read-only, old runs on the same branch/PR are cancelled, and the job has a timeout.

## No model quota or real database required

CI supplies a dummy database URL pointing at unused local port 1, an empty OpenRouter key, and `LIVE_CHAT_ENABLED=false`. No repository secrets are needed. There is no `.env` in the checkout and CI never calls seeding, live evaluation, or `scripts.check_api`.

The 37 current unit tests use mocked PostgreSQL/model calls or an isolated in-memory SQLite table. They cover guardrails, HTTP contracts, key checks, request replay, and error handling. They do **not** establish PostgreSQL reservation concurrency or real model quality; temporary PostgreSQL integration tests are the next step.

## Reproduce locally

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests/unit -v
```

Normal local configuration still comes from `.env`; CI overrides it with dummy environment variables. Live model tests and database-backed checks remain explicit, separate commands.

Open a run, then its job, to inspect a failure. Fix the cause and push again; a new run starts automatically. Download the artifact from the run page if you want to keep evidence for a future recording or portfolio.

CI reports failures; it does not stop direct pushes to `main` or automatically block Vercel deployment. Making checks mandatory requires a later branch-rule/deployment-gate decision. This step adds checks only, not Docker or backend deployment.
