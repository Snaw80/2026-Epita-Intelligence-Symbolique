from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BenchmarkTests(unittest.TestCase):
    def test_load_benchmarks_reads_suite_and_finds_theorem(self) -> None:
        from m8_proof_agent.benchmarks import find_benchmark, load_benchmarks

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "suite.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "demo",
                            "title": "Demo theorem",
                            "suite": "smoke",
                            "difficulty": "easy",
                            "imports": "",
                            "statement": "theorem demo : True := by",
                            "source": "unit-test",
                            "expected_tactics": ["trivial"],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            benchmarks = load_benchmarks(path)
            found = find_benchmark("demo", benchmarks)

        self.assertEqual(len(benchmarks), 1)
        self.assertEqual(found.title, "Demo theorem")
        self.assertEqual(found.expected_tactics, ["trivial"])

    def test_missing_benchmark_raises_clear_key_error(self) -> None:
        from m8_proof_agent.benchmarks import find_benchmark

        with self.assertRaisesRegex(KeyError, "No benchmark"):
            find_benchmark("missing", [])

    def test_minif2f_starter_subset_keeps_mathlib_import(self) -> None:
        from m8_proof_agent.benchmarks import find_benchmark, load_benchmarks

        theorem = find_benchmark("minif2f_mathd_algebra_17", load_benchmarks(suite="minif2f_subset"))

        self.assertEqual(theorem.imports, "import Mathlib")
        self.assertTrue(any("Nat.add_comm" in tactic for tactic in theorem.expected_tactics))


if __name__ == "__main__":
    unittest.main()
