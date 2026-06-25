from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class VerifierTests(unittest.TestCase):
    def test_build_lean_file_strips_extra_by_from_provider_body(self) -> None:
        from m8_proof_agent.verifier import build_lean_file

        source = build_lean_file(
            "",
            "theorem t (a b : Nat) : a + b = b + a := by",
            "by\n  exact Nat.add_comm a b",
        )

        self.assertIn("theorem t (a b : Nat) : a + b = b + a := by\n  exact Nat.add_comm a b", source)
        self.assertNotIn("by\n  by", source)

    def test_verify_lean_copies_stdout_diagnostics_to_errors_on_failure(self) -> None:
        from m8_proof_agent import verifier

        original_find_lean = verifier.find_lean
        verifier.find_lean = lambda: "/usr/bin/lean"

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="unknown module prefix 'Mathlib'", stderr="")

        try:
            result = verifier.verify_lean("", "theorem t : True := by", "exact False.elim", runner=runner)
        finally:
            verifier.find_lean = original_find_lean

        self.assertFalse(result.success)
        self.assertEqual(result.errors, "unknown module prefix 'Mathlib'")

    def test_probe_lean_goal_uses_skip_to_capture_unsolved_goals(self) -> None:
        from m8_proof_agent import verifier

        original_find_lean = verifier.find_lean
        verifier.find_lean = lambda: "/usr/bin/lean"
        seen = {}

        def runner(*args, **kwargs):
            source = Path(args[0][-1]).read_text(encoding="utf-8")
            seen["source"] = source
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="unsolved goals\n⊢ True")

        try:
            result = verifier.probe_lean_goal("", "theorem t : True := by", runner=runner)
        finally:
            verifier.find_lean = original_find_lean

        self.assertIn("skip", seen["source"])
        self.assertFalse(result.success)
        self.assertEqual(result.errors, "unsolved goals\n⊢ True")

    def test_mathlib_import_without_project_returns_setup_needed(self) -> None:
        from m8_proof_agent import verifier

        original_find_lean = verifier.find_lean
        verifier.find_lean = lambda: "/usr/bin/lean"
        try:
            result = verifier.verify_lean("import Mathlib", "theorem t : True := by", "trivial")
        finally:
            verifier.find_lean = original_find_lean

        self.assertEqual(result.status, "setup_needed")
        self.assertIn("Lake project", result.errors)

    def test_missing_mathlib_olean_returns_setup_needed(self) -> None:
        from m8_proof_agent import verifier

        original_find_lean = verifier.find_lean
        verifier.find_lean = lambda: "/usr/bin/lean"

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args[0],
                1,
                stdout="error: object file '/project/.lake/packages/mathlib/.lake/build/lib/lean/Mathlib.olean' of module Mathlib does not exist",
                stderr="",
            )

        try:
            result = verifier.verify_lean(
                "import Mathlib",
                "theorem t : True := by",
                "trivial",
                lean_project_dir="/project",
                runner=runner,
            )
        finally:
            verifier.find_lean = original_find_lean

        self.assertEqual(result.status, "setup_needed")
        self.assertIn("lake exe cache get", result.errors)


if __name__ == "__main__":
    unittest.main()
