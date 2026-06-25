from __future__ import annotations

import json
import os
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

    def test_latest_trace_path_returns_most_recent_json_trace(self) -> None:
        from m8_proof_agent.replay import latest_trace_path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            old_path = directory / "old.json"
            new_path = directory / "new.json"
            old_path.write_text(json.dumps(self._trace_payload(run_id="run-old")), encoding="utf-8")
            new_path.write_text(json.dumps(self._trace_payload(run_id="run-new")), encoding="utf-8")
            os.utime(old_path, (100, 100))
            os.utime(new_path, (200, 200))

            self.assertEqual(latest_trace_path(directory), new_path)

    def test_save_trace_writes_trace_file_that_becomes_latest(self) -> None:
        from m8_proof_agent.replay import latest_trace_path, load_trace, save_trace

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            trace = load_trace_from_payload(self._trace_payload(run_id="run-fresh"))

            saved_path = save_trace(trace, directory)

            self.assertEqual(saved_path, directory / "run-fresh.json")
            self.assertEqual(latest_trace_path(directory), saved_path)
            self.assertEqual(load_trace(saved_path).run_id, "run-fresh")

    def _trace_payload(self, run_id: str = "run-demo"):
        return {
            "run_id": run_id,
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
            "provider": "openai",
            "model": "gpt-test",
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


def load_trace_from_payload(payload):
    from m8_proof_agent.models import ProofTrace

    return ProofTrace(**payload)


if __name__ == "__main__":
    unittest.main()
