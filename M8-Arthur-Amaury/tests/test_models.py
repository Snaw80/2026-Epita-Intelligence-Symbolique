from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ModelTests(unittest.TestCase):
    def test_trace_round_trip_preserves_events_and_final_status(self) -> None:
        from m8_proof_agent.models import (
            AgentRole,
            Benchmark,
            LeanResult,
            ProofAttempt,
            ProofTrace,
            TraceEvent,
            model_to_dict,
            model_to_json,
        )

        theorem = Benchmark(
            id="smoke_and_swap",
            title="And swap",
            suite="smoke",
            difficulty="easy",
            imports="",
            statement="theorem smoke_and_swap (p q : Prop) : p ∧ q → q ∧ p := by",
            source="local",
            expected_tactics=["constructor"],
        )
        trace = ProofTrace(
            run_id="run-test",
            theorem=theorem,
            mode="real",
            provider="openai",
            model="gpt-test",
            status="success",
            events=[
                TraceEvent(
                    index=1,
                    kind="agent_started",
                    agent=AgentRole.ORCHESTRATOR,
                    message="Planning proof",
                )
            ],
            attempts=[
                ProofAttempt(
                    iteration=1,
                    agent=AgentRole.TACTIC,
                    proof="constructor\nexact h.right\nexact h.left",
                    rationale="Use conjunction elimination.",
                    verification=LeanResult(success=True, status="success", output="ok"),
                )
            ],
            final_proof="constructor\nexact h.right\nexact h.left",
        )

        payload = json.loads(model_to_json(trace))
        loaded = ProofTrace(**payload)

        self.assertEqual(loaded.status, "success")
        self.assertEqual(loaded.theorem.id, "smoke_and_swap")
        self.assertEqual(loaded.events[0].agent, AgentRole.ORCHESTRATOR)
        self.assertTrue(loaded.attempts[0].verification.success)
        self.assertEqual(model_to_dict(loaded)["final_proof"], trace.final_proof)

    def test_run_request_clamps_attempt_budget(self) -> None:
        from m8_proof_agent.models import RunRequest

        too_low = RunRequest(theorem_id="x", max_attempts=0)
        too_high = RunRequest(theorem_id="x", max_attempts=99)

        self.assertEqual(too_low.max_attempts, 1)
        self.assertEqual(too_high.max_attempts, 8)

    def test_run_request_leaves_model_empty_so_provider_can_use_env(self) -> None:
        from m8_proof_agent.models import RunRequest

        request = RunRequest(theorem_id="x", provider="openai")

        self.assertEqual(request.model, "")


if __name__ == "__main__":
    unittest.main()
