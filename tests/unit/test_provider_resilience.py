"""Offline regression checks: no provider calls or database connections."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agent import loop
from evals import run
from evals.cases import Case


class ProviderTests(unittest.TestCase):
    def test_empty_response_recovers(self):
        answer = SimpleNamespace(choices=[object()])
        client = MagicMock()
        client.chat.completions.create.side_effect = [None, SimpleNamespace(choices=[]), answer]
        with patch.object(loop, "get_client", return_value=client), patch.object(loop.time, "sleep") as sleep:
            self.assertIs(loop._chat([]), answer)
        self.assertEqual(client.chat.completions.create.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_empty_response_exhausts_three_attempts(self):
        client = MagicMock()
        client.chat.completions.create.return_value = None
        with patch.object(loop, "get_client", return_value=client), patch.object(loop.time, "sleep") as sleep:
            with self.assertRaises(loop.EmptyProviderResponse):
                loop._chat([])
        self.assertEqual(client.chat.completions.create.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_crash_location(self):
        try:
            raise ValueError("test")
        except ValueError as error:
            self.assertIn("test_provider_resilience.py:", loop._where(error))
            self.assertIn("test_crash_location", loop._where(error))


class EvaluationTests(unittest.TestCase):
    def test_error_classification(self):
        self.assertTrue(run.is_infra_error("EmptyProviderResponse: no answer"))
        self.assertTrue(run.is_infra_error("RateLimitError: 429"))
        self.assertFalse(run.is_infra_error("TypeError: bad code"))
        self.assertTrue(run.is_daily_limit("RateLimitError: free-models-per-day"))
        self.assertFalse(run.is_daily_limit("RateLimitError: per-minute"))

    def evaluate(self, errors):
        db = MagicMock()
        def handle(*args, trace, **kwargs):
            trace.extend({"type": "error", "error": error} for error in errors)
            return "temporary problem"
        with patch.object(run, "seed"), patch.object(run, "SessionLocal", return_value=db), \
             patch.object(run, "handle_message", side_effect=handle) as handler, \
             patch.object(run, "compute_allowed", return_value=set()), patch.object(run, "GLOBAL_CHECKS", []):
            result = run.run_case(Case("offline", "test", ["first", "second"], []))
        db.close.assert_called_once()
        return result, handler.call_count

    def test_daily_limit_stops_current_conversation(self):
        result, calls = self.evaluate(["RateLimitError: free-models-per-day"])
        self.assertEqual(calls, 1)
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["quota_exhausted"])

    def test_code_crash_is_failure_even_with_provider_error(self):
        result, _ = self.evaluate(["TypeError: broken", "APIConnectionError: disconnected"])
        self.assertEqual(result["status"], "fail")
        self.assertIn("crashed: TypeError: broken", result["failures"])

    def test_daily_limit_saves_and_stops_suite(self):
        import json
        import tempfile
        from pathlib import Path
        cases = [Case("one", "test", [], []), Case("two", "test", [], [])]
        result = dict(id="one", category="test", status="error", failures=[],
                      infra_errors=["RateLimitError: free-models-per-day"], quota_exhausted=True,
                      tokens_in=0, tokens_out=0, latency_ms=[], turns=[])
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run, "CASES", cases), patch.object(run, "run_case", return_value=result) as runner, \
             patch.object(run, "RESULTS_DIR", Path(directory)), \
             patch("sys.argv", ["eval", "--repeat", "2"]), patch("builtins.print"):
            run.main()
            saved = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
        runner.assert_called_once()
        self.assertTrue(saved["stopped_on_daily_limit"])
        self.assertEqual(saved["remaining"], ["one (2 run(s) remaining)", "two (2 run(s) remaining)"])


if __name__ == "__main__":
    unittest.main()
