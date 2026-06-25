from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class MiniF2FV2Tests(unittest.TestCase):
    def test_parse_minif2f_v2_jsonl_rows_as_benchmarks(self) -> None:
        from m8_proof_agent.minif2f_v2 import parse_jsonl_rows

        rows = [
            json.dumps(
                {
                    "name": "mathd_numbertheory_237",
                    "split": "valid",
                    "informal_statement": "Show that the remainder is 4.",
                    "formal_statement": "theorem mathd_numbertheory_237 :\n  (1 + 2) % 6 = 3 := by",
                    "header": "import Mathlib\nimport Aesop\n\nopen BigOperators\n",
                    "formal_proof": "norm_num",
                }
            )
        ]

        benchmarks = parse_jsonl_rows(rows, suite="minif2f_v2s")

        self.assertEqual(len(benchmarks), 1)
        self.assertEqual(benchmarks[0].id, "mathd_numbertheory_237")
        self.assertEqual(benchmarks[0].suite, "minif2f_v2s")
        self.assertEqual(benchmarks[0].difficulty, "valid")
        self.assertIn("import Mathlib", benchmarks[0].imports)
        self.assertIn("theorem mathd_numbertheory_237", benchmarks[0].statement)
        self.assertEqual(benchmarks[0].expected_tactics, ["norm_num"])
        self.assertIn("Show that", benchmarks[0].description)

    def test_write_benchmark_json_from_jsonl(self) -> None:
        from m8_proof_agent.benchmarks import load_benchmarks
        from m8_proof_agent.minif2f_v2 import write_benchmark_json

        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path = Path(tmp) / "mini.jsonl"
            output_path = Path(tmp) / "mini.json"
            jsonl_path.write_text(
                json.dumps(
                    {
                        "name": "sample_problem",
                        "split": "test",
                        "informal_statement": "A sample problem.",
                        "formal_statement": "theorem sample_problem : True := by",
                        "header": "import Mathlib\n",
                        "formal_proof": "trivial",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            written = write_benchmark_json(jsonl_path, output_path, suite="minif2f_v2s")

            loaded = load_benchmarks(written)
            self.assertEqual(loaded[0].id, "sample_problem")
            self.assertEqual(loaded[0].expected_tactics, ["trivial"])


if __name__ == "__main__":
    unittest.main()
