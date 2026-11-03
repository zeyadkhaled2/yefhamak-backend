"""Opt-in configuration for destructive checks on a disposable PostgreSQL DB."""
import os

from sqlalchemy.engine import make_url


def test_database_url(value: str | None) -> str:
    if not value:
        raise ValueError("Set TEST_DATABASE_URL explicitly; DATABASE_URL/.env are never used as a fallback.")
    try:
        url = make_url(value)
    except Exception:
        raise ValueError("TEST_DATABASE_URL must be a valid PostgreSQL URL.") from None
    if url.drivername not in ("postgresql", "postgresql+psycopg"):
        raise ValueError("Integration tests require PostgreSQL with psycopg.")
    if url.host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Integration tests only accept an explicit loopback host, never a remote database.")
    if not url.database or not (url.database == "yefhamak_test" or url.database.startswith("yefhamak_test_")):
        raise ValueError("The disposable database name must be yefhamak_test or start with yefhamak_test_.")
    if set(url.query) - {"connect_timeout"}:
        raise ValueError("Only connect_timeout is allowed in the test URL query; connection overrides are refused.")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def configure_test_environment() -> str:
    url = test_database_url(os.environ.get("TEST_DATABASE_URL"))
    os.environ.update(DATABASE_URL=url, DIRECT_URL=url, OPENROUTER_API_KEY="",
                      DEMO_API_KEY="database-tests-only", LIVE_CHAT_ENABLED="false",
                      YEFHAMAK_RUN_DB_TESTS="1")
    return url
