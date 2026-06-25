from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
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

    def test_traces_and_replay_return_latest_trace(self) -> None:
        import app

        with tempfile.TemporaryDirectory() as tmp:
            original_trace_dir = app.TRACE_DIR
            app.TRACE_DIR = Path(tmp)
            (app.TRACE_DIR / "old.json").write_text(json.dumps(trace_payload("run-old", "old_theorem")), encoding="utf-8")
            (app.TRACE_DIR / "new.json").write_text(json.dumps(trace_payload("run-new", "new_theorem")), encoding="utf-8")
            os.utime(app.TRACE_DIR / "old.json", (100, 100))
            os.utime(app.TRACE_DIR / "new.json", (200, 200))
            try:
                traces_status, traces_payload = app.api_response("GET", "/api/traces", b"")
                replay_status, replay_payload = app.api_response(
                    "POST",
                    "/api/replay",
                    json.dumps({"trace": "old.json"}).encode("utf-8"),
                )
            finally:
                app.TRACE_DIR = original_trace_dir

        self.assertEqual(traces_status, 200)
        self.assertEqual(replay_status, 200)
        self.assertTrue(any(item["file"] == "new.json" for item in traces_payload["traces"]))
        self.assertEqual(replay_payload["trace"]["status"], "success")
        self.assertEqual(replay_payload["trace"]["run_id"], "run-new")

    def test_replay_can_return_latest_trace_for_specific_theorem(self) -> None:
        import app

        with tempfile.TemporaryDirectory() as tmp:
            original_trace_dir = app.TRACE_DIR
            app.TRACE_DIR = Path(tmp)
            (app.TRACE_DIR / "target-old.json").write_text(
                json.dumps(trace_payload("run-target-old", "target_theorem")),
                encoding="utf-8",
            )
            (app.TRACE_DIR / "other-new.json").write_text(
                json.dumps(trace_payload("run-other-new", "other_theorem")),
                encoding="utf-8",
            )
            (app.TRACE_DIR / "target-new.json").write_text(
                json.dumps(trace_payload("run-target-new", "target_theorem")),
                encoding="utf-8",
            )
            os.utime(app.TRACE_DIR / "target-old.json", (100, 100))
            os.utime(app.TRACE_DIR / "other-new.json", (300, 300))
            os.utime(app.TRACE_DIR / "target-new.json", (200, 200))
            try:
                status, payload = app.api_response(
                    "POST",
                    "/api/replay",
                    json.dumps({"theorem_id": "target_theorem"}).encode("utf-8"),
                )
            finally:
                app.TRACE_DIR = original_trace_dir

        self.assertEqual(status, 200)
        self.assertEqual(payload["trace"]["run_id"], "run-target-new")

    def test_run_persists_new_trace_for_future_replay(self) -> None:
        import app
        from m8_proof_agent.models import LeanResult

        original_verify = app.VERIFY_FN
        original_get_provider = app.get_provider
        original_trace_dir = app.TRACE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            app.TRACE_DIR = Path(tmp)
            app.VERIFY_FN = lambda imports, statement, proof: LeanResult(success=True, status="success", output="ok")
            app.get_provider = lambda name, model="": FakeProvider()
            try:
                status, payload = app.api_response(
                    "POST",
                    "/api/run",
                    json.dumps({"theorem_id": "smoke_true", "suite": "smoke", "provider": "openai"}).encode("utf-8"),
                )
                replay_status, replay_payload = app.api_response("POST", "/api/replay", b"{}")
            finally:
                app.VERIFY_FN = original_verify
                app.get_provider = original_get_provider
                app.TRACE_DIR = original_trace_dir

        self.assertEqual(status, 200)
        self.assertEqual(replay_status, 200)
        self.assertEqual(payload["trace"]["status"], "success")
        self.assertEqual(payload["trace"]["final_proof"], "trivial")
        self.assertEqual(replay_payload["trace"]["run_id"], payload["trace"]["run_id"])

    def test_run_passes_search_strategy_to_graph(self) -> None:
        import app
        from m8_proof_agent.models import ProofTrace

        original_get_provider = app.get_provider
        original_trace_dir = app.TRACE_DIR
        original_run_proof_graph = app.run_proof_graph
        seen = {}
        with tempfile.TemporaryDirectory() as tmp:
            app.TRACE_DIR = Path(tmp)
            app.get_provider = lambda name, model="": FakeProvider()

            def fake_run_proof_graph(theorem, provider, **kwargs):
                seen.update(kwargs)
                return ProofTrace(
                    run_id="run-search-strategy",
                    theorem=theorem,
                    mode="real",
                    provider=provider.name,
                    model=provider.model,
                    status="success",
                    final_proof="trivial",
                )

            app.run_proof_graph = fake_run_proof_graph
            try:
                status, _payload = app.api_response(
                    "POST",
                    "/api/run",
                    json.dumps(
                        {
                            "theorem_id": "smoke_true",
                            "suite": "smoke",
                            "provider": "openai",
                            "search_strategy": "mcts",
                            "mcts_iterations": 7,
                        }
                    ).encode("utf-8"),
                )
            finally:
                app.get_provider = original_get_provider
                app.run_proof_graph = original_run_proof_graph
                app.TRACE_DIR = original_trace_dir

        self.assertEqual(status, 200)
        self.assertEqual(seen["search_strategy"], "mcts")
        self.assertEqual(seen["mcts_iterations"], 7)

    def test_stream_run_lines_yields_events_then_final_trace(self) -> None:
        import app
        from m8_proof_agent.models import LeanResult

        original_verify = app.VERIFY_FN
        original_get_provider = app.get_provider
        original_trace_dir = app.TRACE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            app.TRACE_DIR = Path(tmp)
            app.VERIFY_FN = lambda imports, statement, proof: LeanResult(success=True, status="success", output="ok")
            app.get_provider = lambda name, model="": FakeProvider()
            try:
                lines = list(
                    app.stream_run_lines(
                        json.dumps({"theorem_id": "smoke_true", "suite": "smoke", "provider": "openai"}).encode("utf-8")
                    )
                )
            finally:
                app.VERIFY_FN = original_verify
                app.get_provider = original_get_provider
                app.TRACE_DIR = original_trace_dir

        payloads = [json.loads(line.decode("utf-8")) for line in lines]
        self.assertEqual(payloads[0]["type"], "event")
        self.assertTrue(any(item["type"] == "event" and item["event"]["kind"] == "verification_finished" for item in payloads))
        self.assertEqual(payloads[-1]["type"], "trace")
        self.assertEqual(payloads[-1]["trace"]["status"], "success")

    def test_run_suite_scores_all_requested_benchmarks_and_saves_traces(self) -> None:
        import app
        from m8_proof_agent.models import Benchmark, LeanResult

        benchmarks = [
            Benchmark(
                id="suite_success",
                title="Suite success",
                suite="minif2f_v2s",
                difficulty="valid",
                imports="",
                statement="theorem suite_success : True := by",
                source="unit-test",
            ),
            Benchmark(
                id="suite_failed",
                title="Suite failed",
                suite="minif2f_v2s",
                difficulty="valid",
                imports="",
                statement="theorem suite_failed : True := by",
                source="unit-test",
            ),
        ]

        original_verify = app.VERIFY_FN
        original_get_provider = app.get_provider
        original_trace_dir = app.TRACE_DIR
        original_load_benchmarks = app.load_benchmarks
        with tempfile.TemporaryDirectory() as tmp:
            app.TRACE_DIR = Path(tmp)
            app.get_provider = lambda name, model="": FakeProvider()
            app.load_benchmarks = lambda suite="smoke": benchmarks

            def verify(imports, statement, proof):
                success = "suite_success" in statement
                return LeanResult(success=success, status="success" if success else "failed", output="ok")

            app.VERIFY_FN = verify
            try:
                with redirect_stdout(StringIO()):
                    status, payload = app.api_response(
                        "POST",
                        "/api/run-suite",
                        json.dumps({"suite": "minif2f_v2s", "provider": "openai"}).encode("utf-8"),
                    )
                replay_status, replay_payload = app.api_response(
                    "POST",
                    "/api/replay",
                    json.dumps({"theorem_id": "suite_success"}).encode("utf-8"),
                )
            finally:
                app.VERIFY_FN = original_verify
                app.get_provider = original_get_provider
                app.TRACE_DIR = original_trace_dir
                app.load_benchmarks = original_load_benchmarks

        self.assertEqual(status, 200)
        self.assertEqual(payload["score"]["solved"], 1)
        self.assertEqual(payload["score"]["attempted"], 2)
        self.assertEqual(payload["score"]["accuracy"], 0.5)
        self.assertEqual([item["theorem_id"] for item in payload["results"]], ["suite_success", "suite_failed"])
        self.assertEqual(replay_status, 200)
        self.assertEqual(replay_payload["trace"]["theorem"]["id"], "suite_success")

    def test_run_suite_logs_each_completed_call_to_stdout(self) -> None:
        import app
        from m8_proof_agent.models import Benchmark, LeanResult

        benchmarks = [
            Benchmark(
                id="logged_one",
                title="Logged one",
                suite="minif2f_v2s",
                difficulty="valid",
                imports="",
                statement="theorem logged_one : True := by",
                source="unit-test",
            ),
            Benchmark(
                id="logged_two",
                title="Logged two",
                suite="minif2f_v2s",
                difficulty="valid",
                imports="",
                statement="theorem logged_two : True := by",
                source="unit-test",
            ),
        ]

        original_verify = app.VERIFY_FN
        original_get_provider = app.get_provider
        original_trace_dir = app.TRACE_DIR
        original_load_benchmarks = app.load_benchmarks
        stdout = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            app.TRACE_DIR = Path(tmp)
            app.get_provider = lambda name, model="": FakeProvider()
            app.load_benchmarks = lambda suite="smoke": benchmarks
            app.VERIFY_FN = lambda imports, statement, proof: LeanResult(success=True, status="success", output="ok")
            try:
                with redirect_stdout(stdout):
                    status, _payload = app.api_response(
                        "POST",
                        "/api/run-suite",
                        json.dumps({"suite": "minif2f_v2s", "provider": "openai"}).encode("utf-8"),
                    )
            finally:
                app.VERIFY_FN = original_verify
                app.get_provider = original_get_provider
                app.TRACE_DIR = original_trace_dir
                app.load_benchmarks = original_load_benchmarks

        self.assertEqual(status, 200)
        self.assertIn("[m8] suite minif2f_v2s 1/2 logged_one -> success", stdout.getvalue())
        self.assertIn("[m8] suite minif2f_v2s 2/2 logged_two -> success", stdout.getvalue())

    def test_stream_suite_lines_yields_each_result_then_score(self) -> None:
        import app
        from m8_proof_agent.models import Benchmark, LeanResult

        benchmarks = [
            Benchmark(
                id="stream_one",
                title="Stream one",
                suite="minif2f_v2s",
                difficulty="valid",
                imports="",
                statement="theorem stream_one : True := by",
                source="unit-test",
            ),
            Benchmark(
                id="stream_two",
                title="Stream two",
                suite="minif2f_v2s",
                difficulty="valid",
                imports="",
                statement="theorem stream_two : True := by",
                source="unit-test",
            ),
        ]

        original_verify = app.VERIFY_FN
        original_get_provider = app.get_provider
        original_trace_dir = app.TRACE_DIR
        original_load_benchmarks = app.load_benchmarks
        with tempfile.TemporaryDirectory() as tmp:
            app.TRACE_DIR = Path(tmp)
            app.get_provider = lambda name, model="": FakeProvider()
            app.load_benchmarks = lambda suite="smoke": benchmarks
            app.VERIFY_FN = lambda imports, statement, proof: LeanResult(success=True, status="success", output="ok")
            try:
                with redirect_stdout(StringIO()):
                    lines = list(
                        app.stream_suite_lines(
                            json.dumps({"suite": "minif2f_v2s", "provider": "openai"}).encode("utf-8")
                        )
                    )
            finally:
                app.VERIFY_FN = original_verify
                app.get_provider = original_get_provider
                app.TRACE_DIR = original_trace_dir
                app.load_benchmarks = original_load_benchmarks

        payloads = [json.loads(line.decode("utf-8")) for line in lines]
        self.assertEqual([item["type"] for item in payloads], ["result", "result", "score"])
        self.assertEqual(payloads[0]["result"]["theorem_id"], "stream_one")
        self.assertEqual(payloads[1]["result"]["theorem_id"], "stream_two")
        self.assertEqual(payloads[2]["score"]["solved"], 2)
        self.assertEqual(payloads[2]["score"]["attempted"], 2)


class FakeProvider:
    name = "openai"
    model = "gpt-test"

    def generate_candidates(self, context):
        from m8_proof_agent.models import ProofCandidate

        return [ProofCandidate(proof="trivial", rationale="unit test")]


def trace_payload(run_id: str, theorem_id: str):
    return {
        "run_id": run_id,
        "theorem": {
            "id": theorem_id,
            "title": theorem_id,
            "suite": "smoke",
            "difficulty": "easy",
            "imports": "",
            "statement": f"theorem {theorem_id} : True := by",
            "source": "unit-test",
            "expected_tactics": ["trivial"],
        },
        "mode": "real",
        "provider": "openai",
        "model": "gpt-test",
        "status": "success",
        "events": [],
        "attempts": [],
        "final_proof": "trivial",
        "error": "",
        "elapsed_ms": 10,
        "token_usage": {},
    }


if __name__ == "__main__":
    unittest.main()
