from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class AppApiTests(unittest.TestCase):
    def test_load_dotenv_reads_values_without_overwriting_environment(self) -> None:
        import app

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                'OPENAI_API_KEY="from-file"\nOPENAI_MODEL=gpt-test\nEXISTING=from-file\n',
                encoding="utf-8",
            )
            original_key = os.environ.pop("OPENAI_API_KEY", None)
            original_model = os.environ.pop("OPENAI_MODEL", None)
            original_existing = os.environ.get("EXISTING")
            os.environ["EXISTING"] = "from-env"
            try:
                app.load_dotenv(env_path)

                self.assertEqual(os.environ["OPENAI_API_KEY"], "from-file")
                self.assertEqual(os.environ["OPENAI_MODEL"], "gpt-test")
                self.assertEqual(os.environ["EXISTING"], "from-env")
            finally:
                for key, value in {
                    "OPENAI_API_KEY": original_key,
                    "OPENAI_MODEL": original_model,
                    "EXISTING": original_existing,
                }.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_health_reports_runtime_and_optional_langgraph(self) -> None:
        import app

        status, payload = app.api_response("GET", "/api/health", b"")

        self.assertEqual(status, 200)
        self.assertIn("python", payload)
        self.assertIn("langgraph_available", payload)

    def test_apply_environment_sets_lean_project_dir_for_mathlib_benchmark(self) -> None:
        import app
        from m8_proof_agent.models import Benchmark

        benchmark = Benchmark(
            id="mathlib_demo",
            title="Mathlib demo",
            suite="minif2f_subset",
            difficulty="starter",
            imports="import Mathlib",
            statement="theorem mathlib_demo : True := by",
            source="unit-test",
            expected_tactics=["trivial"],
        )

        configured = app.apply_environment_to_benchmark(benchmark, {"M8_LEAN_PROJECT_DIR": "/tmp/mathlib-project"})

        self.assertEqual(configured.lean_project_dir, "/tmp/mathlib-project")

    def test_benchmarks_lists_smoke_and_minif2f_subset(self) -> None:
        import app

        status, payload = app.api_response("GET", "/api/benchmarks", b"")

        self.assertEqual(status, 200)
        suites = {item["suite"] for item in payload["benchmarks"]}
        self.assertIn("smoke", suites)
        self.assertIn("minif2f_subset", suites)

    def test_traces_and_replay_return_sample_trace(self) -> None:
        import app

        traces_status, traces_payload = app.api_response("GET", "/api/traces", b"")
        replay_status, replay_payload = app.api_response(
            "POST",
            "/api/replay",
            json.dumps({"trace": "sample_success.json"}).encode("utf-8"),
        )

        self.assertEqual(traces_status, 200)
        self.assertEqual(replay_status, 200)
        self.assertTrue(any(item["file"] == "sample_success.json" for item in traces_payload["traces"]))
        self.assertEqual(replay_payload["trace"]["status"], "success")

    def test_run_uses_demo_provider_and_injected_verifier(self) -> None:
        import app
        from m8_proof_agent.models import LeanResult

        original = app.VERIFY_FN
        app.VERIFY_FN = lambda imports, statement, proof: LeanResult(success=True, status="success", output="ok")
        try:
            status, payload = app.api_response(
                "POST",
                "/api/run",
                json.dumps({"theorem_id": "smoke_true", "suite": "smoke", "provider": "demo"}).encode("utf-8"),
            )
        finally:
            app.VERIFY_FN = original

        self.assertEqual(status, 200)
        self.assertEqual(payload["trace"]["status"], "success")
        self.assertEqual(payload["trace"]["final_proof"], "trivial")

    def test_stream_run_lines_yields_events_then_final_trace(self) -> None:
        import app
        from m8_proof_agent.models import LeanResult

        original = app.VERIFY_FN
        app.VERIFY_FN = lambda imports, statement, proof: LeanResult(success=True, status="success", output="ok")
        try:
            lines = list(
                app.stream_run_lines(
                    json.dumps({"theorem_id": "smoke_true", "suite": "smoke", "provider": "demo"}).encode("utf-8")
                )
            )
        finally:
            app.VERIFY_FN = original

        payloads = [json.loads(line.decode("utf-8")) for line in lines]
        self.assertEqual(payloads[0]["type"], "event")
        self.assertTrue(any(item["type"] == "event" and item["event"]["kind"] == "verification_finished" for item in payloads))
        self.assertEqual(payloads[-1]["type"], "trace")
        self.assertEqual(payloads[-1]["trace"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
