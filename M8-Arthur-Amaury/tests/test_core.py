import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from m8_lean_agent.benchmarks import load_benchmarks
from m8_lean_agent.engine import run_benchmark_suite, run_proof_session
from m8_lean_agent.models import Benchmark, ProofCandidate, VerificationResult
from m8_lean_agent.providers import BaseProvider, ProviderError, get_provider, parse_candidates
from m8_lean_agent.research_import import extract_putnam_benchmarks, write_putnam_benchmarks
from m8_lean_agent.verifier import command_for_lean, find_lean_binary, verify_lean


class ScriptedProvider(BaseProvider):
    def __init__(self, proofs):
        super().__init__(name="scripted-test", model="test-model", last_token_usage={})
        self.proofs = proofs
        self.calls = 0

    def generate_candidates(self, _context):
        proof = self.proofs[min(self.calls, len(self.proofs) - 1)]
        self.calls += 1
        return [ProofCandidate(proof=proof, rationale="test candidate")]


class BrokenJsonProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="broken-json", model="test-model", last_token_usage={})

    def generate_candidates(self, _context):
        return parse_candidates('{"candidates":[{"proof":"intro h')


class CoreBehaviorTests(unittest.TestCase):
    def test_benchmark_json_loads_required_fields(self):
        benchmarks = load_benchmarks(ROOT / "benchmarks.json")

        self.assertEqual(len(benchmarks), 8)
        for benchmark in benchmarks:
            self.assertTrue(benchmark.id)
            self.assertTrue(benchmark.title)
            self.assertIn("theorem", benchmark.statement)
            self.assertIsInstance(benchmark.expected_tactics, list)

    def test_benchmark_json_loads_optional_research_project_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "research.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "putnam_sample",
                            "title": "PutnamBench sample",
                            "difficulty": "research",
                            "imports": "import Mathlib",
                            "statement": "theorem putnam_sample : True",
                            "lean_project_dir": "/tmp/PutnamBench",
                            "source": "PutnamBench",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            benchmark = load_benchmarks(path)[0]

        self.assertEqual(benchmark.lean_project_dir, "/tmp/PutnamBench")
        self.assertEqual(benchmark.source, "PutnamBench")

    def test_putnam_importer_extracts_theorem_statements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "lean4"
            source_dir = project_dir / "src" / "Putnam"
            source_dir.mkdir(parents=True)
            (source_dir / "Tiny.lean").write_text(
                """import Mathlib

/-- A tiny theorem for importer tests. -/
theorem putnam_tiny (n : Nat) : n = n := by
  sorry

theorem putnam_with_factored_answer : Nat.succ 0 = putnam_with_factored_answer_solution := by
  sorry
""",
                encoding="utf-8",
            )

            benchmarks = extract_putnam_benchmarks(project_dir)

        self.assertEqual(len(benchmarks), 1)
        self.assertEqual(benchmarks[0]["id"], "putnam_tiny")
        self.assertEqual(benchmarks[0]["imports"], "import Mathlib")
        self.assertEqual(benchmarks[0]["statement"], "theorem putnam_tiny (n : Nat) : n = n")
        self.assertEqual(benchmarks[0]["source"], "PutnamBench")
        self.assertEqual(benchmarks[0]["lean_project_dir"], str(project_dir.resolve()))

    def test_putnam_importer_writes_loadable_research_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "lean4"
            source_dir = project_dir / "src"
            source_dir.mkdir(parents=True)
            (source_dir / "Tiny.lean").write_text(
                "import Mathlib\n\ntheorem putnam_tiny : True := by\n  sorry\n",
                encoding="utf-8",
            )
            output_path = Path(tmpdir) / "research_benchmarks.json"

            count = write_putnam_benchmarks(project_dir, output_path)
            loaded = load_benchmarks(output_path)

        self.assertEqual(count, 1)
        self.assertEqual(loaded[0].id, "putnam_tiny")
        self.assertEqual(loaded[0].lean_project_dir, str(project_dir.resolve()))

    def test_removed_mock_provider_is_rejected(self):
        with self.assertRaises(ProviderError):
            get_provider("mock")

    def test_parse_candidates_wraps_malformed_json_as_provider_error(self):
        with self.assertRaises(ProviderError):
            parse_candidates('{"candidates":[{"proof":"intro h')

    def test_parse_candidates_accepts_plain_lean_code_fence(self):
        candidates = parse_candidates("```lean\nby\n  trivial\n```")

        self.assertEqual(candidates[0].proof, "by\n  trivial")
        self.assertEqual(candidates[0].source, "fallback")

    def test_parse_candidates_repairs_raw_newlines_inside_json_proof(self):
        candidates = parse_candidates('{"candidates":[{"proof":"intro h\nexact h","rationale":"direct"}]}')

        self.assertEqual(candidates[0].proof, "intro h\nexact h")

    def test_parse_candidates_accepts_bare_tactic_text(self):
        candidates = parse_candidates("intro h\nexact h")

        self.assertEqual(candidates[0].proof, "intro h\nexact h")
        self.assertEqual(candidates[0].source, "fallback")

    def test_proof_guard_rejects_sorry_and_admit(self):
        theorem = "theorem bad : True"

        sorry_result = verify_lean("", theorem, "sorry")
        admit_result = verify_lean("", theorem, "by admit")

        self.assertFalse(sorry_result.success)
        self.assertEqual(sorry_result.status, "rejected")
        self.assertIn("sorry", sorry_result.errors)
        self.assertFalse(admit_result.success)
        self.assertEqual(admit_result.status, "rejected")
        self.assertIn("admit", admit_result.errors)

    def test_missing_lean_returns_setup_needed(self):
        result = verify_lean(
            "",
            "theorem trivial_true : True",
            "trivial",
            command_lookup=lambda _name: None,
            lean_home=Path(os.devnull),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "setup_needed")
        self.assertIn("Lean", result.errors)

    def test_verifier_uses_plain_lean_without_lake(self):
        command = command_for_lean(lambda name: f"/fake/{name}" if name in {"lean", "lake"} else None, "Tmp.lean")

        self.assertEqual(command, ["/fake/lean", "Tmp.lean"])

    def test_verifier_uses_lake_env_lean_for_project_mode(self):
        command = command_for_lean(
            lambda name: f"/fake/{name}" if name in {"lean", "lake"} else None,
            "Tmp.lean",
            lean_project_dir="/tmp/PutnamBench",
        )

        self.assertEqual(command, ["/fake/lake", "env", "/fake/lean", "Tmp.lean"])

    def test_project_mode_missing_lake_returns_setup_needed(self):
        with tempfile.TemporaryDirectory() as project_dir:
            result = verify_lean(
                "",
                "theorem trivial_true : True",
                "trivial",
                command_lookup=lambda name: "/fake/lean" if name == "lean" else None,
                lean_project_dir=project_dir,
                lean_home=Path(os.devnull),
            )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "setup_needed")
        self.assertIn("Lake", result.errors)

    def test_find_lean_binary_falls_back_to_elan_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lean = Path(tmpdir) / ".elan" / "bin" / "lean"
            lean.parent.mkdir(parents=True)
            lean.write_text("#!/bin/sh\n", encoding="utf-8")
            lean.chmod(0o755)

            resolved = find_lean_binary(command_lookup=lambda _name: None, home=Path(tmpdir))

        self.assertEqual(resolved, str(lean))

    def test_command_for_lean_uses_resolved_elan_binary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lean = Path(tmpdir) / ".elan" / "bin" / "lean"
            lean.parent.mkdir(parents=True)
            lean.write_text("#!/bin/sh\n", encoding="utf-8")
            lean.chmod(0o755)

            command = command_for_lean(lambda _name: None, "Tmp.lean", home=Path(tmpdir))

        self.assertEqual(command, [str(lean), "Tmp.lean"])

    def test_session_loop_succeeds_after_failed_scripted_attempt(self):
        benchmark = next(b for b in load_benchmarks(ROOT / "benchmarks.json") if b.id == "nat_zero_add")

        def fake_verify(_imports, _statement, proof):
            if proof.strip() == "simp":
                return VerificationResult(success=True, status="success", errors="")
            return VerificationResult(success=False, status="failed", errors="tactic failed")

        result = run_proof_session(
            theorem=benchmark,
            provider=ScriptedProvider(["rfl", "simp"]),
            max_iterations=2,
            verify_fn=fake_verify,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.final_proof, "simp")
        self.assertEqual(len(result.attempts), 2)

    def test_session_returns_provider_error_for_malformed_llm_json(self):
        benchmark = next(b for b in load_benchmarks(ROOT / "benchmarks.json") if b.id == "logic_true")

        result = run_proof_session(
            theorem=benchmark,
            provider=BrokenJsonProvider(),
            max_iterations=1,
            verify_fn=lambda _imports, _statement, _proof: VerificationResult(success=True, status="success", errors=""),
        )

        self.assertEqual(result.status, "provider_error")
        self.assertEqual(result.attempts, [])
        self.assertIsNone(result.final_proof)
        self.assertIn("not valid JSON", result.error)

    def test_session_passes_research_project_dir_to_verifier(self):
        benchmark = Benchmark(
            id="research_true",
            title="Research true",
            difficulty="research",
            imports="import Mathlib",
            statement="theorem research_true : True",
            lean_project_dir="/tmp/PutnamBench",
        )
        seen_project_dirs = []

        def fake_verify(_imports, _statement, _proof, *, lean_project_dir=None):
            seen_project_dirs.append(lean_project_dir)
            return VerificationResult(success=True, status="success", errors="")

        result = run_proof_session(
            theorem=benchmark,
            provider=ScriptedProvider(["trivial"]),
            max_iterations=1,
            verify_fn=fake_verify,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(seen_project_dirs, ["/tmp/PutnamBench"])

    def test_benchmark_suite_summarizes_multiple_sessions(self):
        benchmarks = [
            Benchmark(
                id="suite_true",
                title="Suite true",
                difficulty="easy",
                imports="",
                statement="theorem suite_true : True",
            ),
            Benchmark(
                id="suite_false",
                title="Suite false",
                difficulty="hard",
                imports="",
                statement="theorem suite_false : True",
            ),
        ]

        def fake_verify(_imports, _statement, proof, *, lean_project_dir=None):
            return VerificationResult(success=proof == "trivial", status="success" if proof == "trivial" else "failed", errors="")

        result = run_benchmark_suite(
            suite_name="unit",
            benchmarks=benchmarks,
            provider=ScriptedProvider(["trivial", "bad"]),
            max_iterations=1,
            verify_fn=fake_verify,
        )

        trace = result.to_trace_dict()
        self.assertEqual(trace["suite"], "unit")
        self.assertEqual(trace["total"], 2)
        self.assertEqual(trace["success"], 1)
        self.assertEqual(trace["failed"], 1)
        self.assertEqual(trace["first_try_success"], 1)
        self.assertEqual(len(trace["sessions"]), 2)

    def test_benchmark_suite_continues_after_provider_error_session(self):
        benchmarks = [
            Benchmark(id="bad_json", title="Bad JSON", difficulty="easy", imports="", statement="theorem bad_json : True"),
            Benchmark(id="also_bad_json", title="Also bad JSON", difficulty="easy", imports="", statement="theorem also_bad_json : True"),
        ]

        result = run_benchmark_suite(
            suite_name="unit",
            benchmarks=benchmarks,
            provider=BrokenJsonProvider(),
            max_iterations=1,
            verify_fn=lambda _imports, _statement, _proof: VerificationResult(success=True, status="success", errors=""),
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.total, 2)
        self.assertEqual([session.status for session in result.sessions], ["provider_error", "provider_error"])

    def test_trace_export_contains_stable_keys(self):
        benchmark = next(b for b in load_benchmarks(ROOT / "benchmarks.json") if b.id == "logic_true")

        def fake_verify(_imports, _statement, proof):
            return VerificationResult(success=proof.strip() == "trivial", status="success", errors="")

        result = run_proof_session(
            theorem=benchmark,
            provider=ScriptedProvider(["trivial"]),
            max_iterations=1,
            verify_fn=fake_verify,
        )

        trace = result.to_trace_dict()
        for key in [
            "session_id",
            "provider",
            "model",
            "theorem_id",
            "status",
            "attempts",
            "final_proof",
            "error",
            "elapsed_ms",
            "token_usage",
        ]:
            self.assertIn(key, trace)
        json.dumps(trace)


if __name__ == "__main__":
    unittest.main()
