"""Run only against an explicitly selected disposable database.

    TEST_DATABASE_URL=... python -m tests.integration
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.integration.database import configure_test_environment


def main() -> int:
    try:
        configure_test_environment()
    except ValueError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2

    # Set the target before importing application settings/engine or Alembic env.
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(config, "head")
    suite = unittest.defaultTestLoader.discover(str(root / "tests/integration"), pattern="test_postgres.py")
    # These tests must never invoke a model, even if application code changes.
    with patch("app.agent.loop.get_client", side_effect=AssertionError("Model access forbidden in DB tests")) as model:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if model.called:
            print("FAILED: database tests attempted model access", file=sys.stderr)
            return 1
    return 0 if result.wasSuccessful() and result.testsRun else 1


if __name__ == "__main__":
    raise SystemExit(main())
