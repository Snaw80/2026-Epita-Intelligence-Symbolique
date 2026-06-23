from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ReplayTests(unittest.TestCase):
    def test_load_trace_reads_proof_trace(self) -> None:
        from m8_proof_agent.replay import load_trace

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text(json.dumps(self._trace_payload()), encoding="utf-8")

            trace = load_trace(path)

        self.assertEqual(trace.run_id, "run-demo")
        self.assertEqual(trace.status, "success")
        self.assertEqual(trace.events[0].kind, "run_started")

    def test_list_traces_returns_metadata_without_full_attempts(self) -> None:
        from m8_proof_agent.replay import list_traces

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "trace.json").write_text(json.dumps(self._trace_payload()), encoding="utf-8")

            traces = list_traces(directory)

        self.assertEqual(traces, [{"file": "trace.json", "run_id": "run-demo", "theorem_id": "smoke_true", "status": "success"}])

    def _trace_payload(self):
        return {
            "run_id": "run-demo",
            "theorem": {
                "id": "smoke_true",
                "title": "True introduction",
                "suite": "smoke",
                "difficulty": "easy",
                "imports": "",
                "statement": "theorem smoke_true : True := by",
                "source": "unit-test",
                "expected_tactics": ["trivial"],
            },
            "mode": "replay",
            "provider": "demo",
            "model": "deterministic",
            "status": "success",
            "events": [
                {"index": 1, "kind": "run_started", "agent": "orchestrator", "message": "start", "payload": {}}
            ],
            "attempts": [],
            "final_proof": "trivial",
            "error": "",
            "elapsed_ms": 10,
            "token_usage": {},
        }


if __name__ == "__main__":
    unittest.main()
