from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class GraphTests(unittest.TestCase):
    def _benchmark(self):
        from m8_proof_agent.models import Benchmark

        return Benchmark(
            id="smoke_true",
            title="True introduction",
            suite="smoke",
            difficulty="easy",
            imports="",
            statement="theorem smoke_true : True := by",
            source="unit-test",
            expected_tactics=["trivial"],
        )

    def test_graph_returns_success_trace_after_verified_candidate(self) -> None:
        from m8_proof_agent.graph import ProofCandidate, run_proof_graph
        from m8_proof_agent.models import LeanResult

        class Provider:
            name = "fake"
            model = "unit"

            def generate_candidates(self, context):
                return [ProofCandidate(proof="trivial", rationale="True is trivial.")]

        def verify(imports: str, statement: str, proof: str) -> LeanResult:
            return LeanResult(success=True, status="success", output="ok")

        trace = run_proof_graph(self._benchmark(), Provider(), verify_fn=verify)

        self.assertEqual(trace.status, "success")
        self.assertEqual(trace.final_proof, "trivial")
        self.assertEqual(trace.attempts[0].agent.value, "tactic_agent")
        self.assertTrue(any(event.kind == "final_verified" for event in trace.events))

    def test_graph_repairs_after_lean_failure(self) -> None:
        from m8_proof_agent.graph import ProofCandidate, run_proof_graph
        from m8_proof_agent.models import LeanResult

        class Provider:
            name = "fake"
            model = "unit"

            def __init__(self) -> None:
                self.calls = 0

            def generate_candidates(self, context):
                self.calls += 1
                if self.calls == 1:
                    return [ProofCandidate(proof="exact bad", rationale="Initial guess.")]
                return [ProofCandidate(proof="trivial", rationale="Repair from Lean error.")]

        results: List[LeanResult] = [
            LeanResult(success=False, status="failed", errors="unknown identifier 'bad'"),
            LeanResult(success=True, status="success", output="ok"),
        ]

        def verify(imports: str, statement: str, proof: str) -> LeanResult:
            return results.pop(0)

        provider = Provider()
        trace = run_proof_graph(self._benchmark(), provider, verify_fn=verify, max_attempts=2)

        self.assertEqual(trace.status, "success")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(len(trace.attempts), 2)
        self.assertTrue(any(event.agent.value == "repair_agent" for event in trace.events))

    def test_graph_passes_goal_probe_to_provider_context(self) -> None:
        from m8_proof_agent.graph import ProofCandidate, run_proof_graph
        from m8_proof_agent.models import LeanResult

        seen = {}

        class Provider:
            name = "fake"
            model = "unit"

            def generate_candidates(self, context):
                seen["goal_state"] = context["goal_state"]
                return [ProofCandidate(proof="trivial", rationale="Use probed goal.")]

        def verify(imports: str, statement: str, proof: str) -> LeanResult:
            return LeanResult(success=True, status="success", output="ok")

        def probe(imports: str, statement: str) -> LeanResult:
            return LeanResult(success=False, status="failed", errors="unsolved goals\n⊢ True")

        trace = run_proof_graph(self._benchmark(), Provider(), verify_fn=verify, goal_probe_fn=probe)

        self.assertEqual(trace.status, "success")
        self.assertEqual(seen["goal_state"], "unsolved goals\n⊢ True")
        self.assertTrue(any(event.kind == "goal_probe_finished" for event in trace.events))

    def test_graph_uses_beam_width_to_verify_multiple_candidates(self) -> None:
        from m8_proof_agent.graph import ProofCandidate, run_proof_graph
        from m8_proof_agent.models import LeanResult

        seen = {}

        class Provider:
            name = "fake"
            model = "unit"

            def generate_candidates(self, context):
                seen["candidate_count"] = context["candidate_count"]
                return [
                    ProofCandidate(proof="exact bad", rationale="First beam branch."),
                    ProofCandidate(proof="trivial", rationale="Second beam branch."),
                    ProofCandidate(proof="exact never", rationale="Unused branch."),
                ]

        def verify(imports: str, statement: str, proof: str) -> LeanResult:
            if proof == "trivial":
                return LeanResult(success=True, status="success", output="ok")
            return LeanResult(success=False, status="failed", errors="unknown identifier")

        trace = run_proof_graph(self._benchmark(), Provider(), verify_fn=verify, beam_width=3)

        self.assertEqual(trace.status, "success")
        self.assertEqual(trace.final_proof, "trivial")
        self.assertEqual(seen["candidate_count"], 3)
        self.assertEqual([attempt.proof for attempt in trace.attempts], ["exact bad", "trivial"])
        self.assertTrue(any(event.kind == "beam_started" and event.payload["beam_width"] == 3 for event in trace.events))

    def test_graph_stops_when_lean_setup_is_missing(self) -> None:
        from m8_proof_agent.graph import ProofCandidate, run_proof_graph
        from m8_proof_agent.models import LeanResult

        class Provider:
            name = "fake"
            model = "unit"

            def generate_candidates(self, context):
                return [ProofCandidate(proof="trivial", rationale="True is trivial.")]

        def verify(imports: str, statement: str, proof: str) -> LeanResult:
            return LeanResult(success=False, status="setup_needed", errors="lean not found")

        trace = run_proof_graph(self._benchmark(), Provider(), verify_fn=verify)

        self.assertEqual(trace.status, "setup_needed")
        self.assertEqual(trace.error, "lean not found")
        self.assertTrue(any(event.kind == "setup_needed" for event in trace.events))

    def test_graph_passes_benchmark_lean_project_dir_to_verifier(self) -> None:
        from m8_proof_agent.graph import ProofCandidate, run_proof_graph
        from m8_proof_agent.models import Benchmark, LeanResult

        theorem = Benchmark(
            id="mathlib_demo",
            title="Mathlib demo",
            suite="minif2f_subset",
            difficulty="starter",
            imports="import Mathlib",
            statement="theorem mathlib_demo : True := by",
            source="unit-test",
            expected_tactics=["trivial"],
            lean_project_dir="/tmp/mathlib-project",
        )

        class Provider:
            name = "fake"
            model = "unit"

            def generate_candidates(self, context):
                return [ProofCandidate(proof="trivial", rationale="True is trivial.")]

        seen = {}

        def verify(imports: str, statement: str, proof: str, lean_project_dir=None) -> LeanResult:
            seen["lean_project_dir"] = lean_project_dir
            return LeanResult(success=True, status="success", output="ok")

        trace = run_proof_graph(theorem, Provider(), verify_fn=verify)

        self.assertEqual(trace.status, "success")
        self.assertEqual(seen["lean_project_dir"], "/tmp/mathlib-project")

    def test_graph_streams_events_with_elapsed_time(self) -> None:
        from m8_proof_agent.graph import ProofCandidate, run_proof_graph
        from m8_proof_agent.models import LeanResult

        class Provider:
            name = "fake"
            model = "unit"

            def generate_candidates(self, context):
                return [ProofCandidate(proof="trivial", rationale="True is trivial.")]

        streamed = []

        def verify(imports: str, statement: str, proof: str) -> LeanResult:
            return LeanResult(success=True, status="success", output="ok")

        trace = run_proof_graph(self._benchmark(), Provider(), verify_fn=verify, event_sink=streamed.append)

        self.assertEqual(trace.status, "success")
        self.assertGreaterEqual(len(streamed), 5)
        self.assertEqual(streamed[0].kind, "run_started")
        self.assertIn("elapsed_ms", streamed[0].payload)
        self.assertTrue(any(event.kind == "verification_finished" for event in streamed))
        verification_event = next(event for event in streamed if event.kind == "verification_finished")
        self.assertEqual(verification_event.payload["output"], "ok")


if __name__ == "__main__":
    unittest.main()
