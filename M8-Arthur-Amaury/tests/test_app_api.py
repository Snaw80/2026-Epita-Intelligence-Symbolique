import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app
from app import api_response


class AppApiTests(unittest.TestCase):
    def test_get_benchmarks_api_returns_items(self):
        status, payload = api_response("GET", "/api/benchmarks", b"")

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["benchmarks"]), 8)
        self.assertIn("id", payload["benchmarks"][0])

    def test_get_health_api_reports_tooling_and_providers(self):
        status, payload = api_response("GET", "/api/health", b"")

        self.assertEqual(status, 200)
        self.assertIn("python", payload)
        self.assertIn("lean", payload)
        self.assertNotIn("lake", payload)
        self.assertNotIn("lean_project_dir", payload)
        self.assertIn("providers", payload)
        self.assertNotIn("mock", payload["providers"])
        self.assertIn("mistral", payload["providers"])
        self.assertIn("openai_compatible", payload["providers"])

    def test_health_api_uses_elan_fallback_when_path_misses_lean(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lean = Path(tmpdir) / ".elan" / "bin" / "lean"
            lean.parent.mkdir(parents=True)
            lean.write_text("#!/bin/sh\n", encoding="utf-8")
            lean.chmod(0o755)
            old_home = app.LEAN_HOME_OVERRIDE
            old_lookup = app.LEAN_COMMAND_LOOKUP
            try:
                app.LEAN_HOME_OVERRIDE = Path(tmpdir)
                app.LEAN_COMMAND_LOOKUP = lambda _name: None
                status, payload = api_response("GET", "/api/health", b"")
            finally:
                app.LEAN_HOME_OVERRIDE = old_home
                app.LEAN_COMMAND_LOOKUP = old_lookup

        self.assertEqual(status, 200)
        self.assertEqual(payload["lean"], str(lean))

    def test_health_api_reads_provider_keys_from_dotenv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("MISTRAL_API_KEY=from-dotenv\n", encoding="utf-8")
            old_env_path = getattr(app, "ENV_PATH_OVERRIDE", None)
            old_mistral = os.environ.pop("MISTRAL_API_KEY", None)
            old_openai = os.environ.pop("OPENAI_API_KEY", None)
            try:
                app.ENV_PATH_OVERRIDE = env_path
                status, payload = api_response("GET", "/api/health", b"")
            finally:
                app.ENV_PATH_OVERRIDE = old_env_path
                if old_mistral is not None:
                    os.environ["MISTRAL_API_KEY"] = old_mistral
                else:
                    os.environ.pop("MISTRAL_API_KEY", None)
                if old_openai is not None:
                    os.environ["OPENAI_API_KEY"] = old_openai
                else:
                    os.environ.pop("OPENAI_API_KEY", None)

        self.assertEqual(status, 200)
        self.assertTrue(payload["providers"]["mistral"])

    def test_post_run_api_rejects_removed_mock_provider(self):
        body = json.dumps(
            {
                "theorem_id": "logic_true",
                "provider": "mock",
                "max_iterations": 1,
            }
        ).encode("utf-8")

        status, payload = api_response("POST", "/api/run", body)

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "provider_error")
        self.assertIsNone(payload["final_proof"])
        self.assertEqual(payload["provider"], "mock")

    def test_post_run_benchmark_api_returns_suite_trace_shape(self):
        body = json.dumps(
            {
                "suite": "smoke",
                "provider": "mock",
                "max_iterations": 1,
                "limit": 2,
            }
        ).encode("utf-8")

        status, payload = api_response("POST", "/api/run-benchmark", body)

        self.assertEqual(status, 200)
        self.assertEqual(payload["suite"], "smoke")
        self.assertEqual(payload["status"], "provider_error")
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["sessions"], [])

    def test_research_benchmark_api_explains_missing_import_file(self):
        body = json.dumps({"suite": "research", "provider": "mistral"}).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            old_env_path = getattr(app, "ENV_PATH_OVERRIDE", None)
            old_suite_path = app.BENCHMARK_SUITES["research"]
            old_research_path = os.environ.pop("RESEARCH_BENCHMARK_PATH", None)
            try:
                app.ENV_PATH_OVERRIDE = Path(tmpdir) / ".env"
                app.BENCHMARK_SUITES["research"] = Path(tmpdir) / "missing_research.json"
                status, payload = api_response("POST", "/api/run-benchmark", body)
            finally:
                app.ENV_PATH_OVERRIDE = old_env_path
                app.BENCHMARK_SUITES["research"] = old_suite_path
                if old_research_path is not None:
                    os.environ["RESEARCH_BENCHMARK_PATH"] = old_research_path

        self.assertEqual(status, 400)
        self.assertIn("import_putnam.py", payload["error"])


if __name__ == "__main__":
    unittest.main()
