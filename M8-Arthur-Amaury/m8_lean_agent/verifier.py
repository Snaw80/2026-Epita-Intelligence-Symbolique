"""Deterministic Lean verification layer."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Callable, List, Optional

from .models import VerificationResult


FORBIDDEN_PROOF_RE = re.compile(r"\b(sorry|admit)\b")


def _format_lean_code(imports: str, theorem: str, proof: str) -> str:
    proof = proof.strip()
    theorem = theorem.strip()
    if proof.startswith("by "):
        body = f"{theorem} := {proof}"
    else:
        body = f"{theorem} := by\n  {proof}"
    return "\n".join(part for part in [imports.strip(), body] if part) + "\n"


def find_lean_binary(
    command_lookup: Callable[[str], Optional[str]],
    home: Optional[Path] = None,
) -> Optional[str]:
    found = command_lookup("lean")
    if found:
        return found

    elan_lean = (home or Path.home()) / ".elan" / "bin" / "lean"
    if elan_lean.exists() and os.access(elan_lean, os.X_OK):
        return str(elan_lean)
    return None


def find_lake_binary(
    command_lookup: Callable[[str], Optional[str]],
    home: Optional[Path] = None,
) -> Optional[str]:
    found = command_lookup("lake")
    if found:
        return found

    elan_lake = (home or Path.home()) / ".elan" / "bin" / "lake"
    if elan_lake.exists() and os.access(elan_lake, os.X_OK):
        return str(elan_lake)
    return None


def command_for_lean(
    command_lookup: Callable[[str], Optional[str]],
    lean_file: str,
    *,
    home: Optional[Path] = None,
    lean_project_dir: Optional[str] = None,
) -> Optional[List[str]]:
    lean = find_lean_binary(command_lookup, home=home)
    if lean and lean_project_dir:
        lake = find_lake_binary(command_lookup, home=home)
        if lake:
            return [lake, "env", lean, lean_file]
        return None
    if lean:
        return [lean, lean_file]
    return None


def verify_lean(
    imports: str,
    theorem: str,
    proof: str,
    *,
    command_lookup: Callable[[str], Optional[str]] = shutil.which,
    lean_project_dir: Optional[str] = None,
    lean_home: Optional[Path] = None,
    timeout_s: int = 30,
) -> VerificationResult:
    """Verify a theorem/proof pair with Lean.

    Lean is the only correctness judge. This function only returns success when
    the Lean process exits cleanly. Missing tooling is reported as setup_needed
    so the web demo can show actionable setup guidance.
    """
    if FORBIDDEN_PROOF_RE.search(proof):
        token = FORBIDDEN_PROOF_RE.search(proof).group(1)
        return VerificationResult(
            success=False,
            status="rejected",
            errors=f"Proof rejected before Lean: forbidden placeholder {token!r}.",
        )
    if lean_project_dir and not Path(lean_project_dir).is_dir():
        return VerificationResult(
            success=False,
            status="setup_needed",
            errors=f"Lean project directory does not exist: {lean_project_dir}",
        )

    code = _format_lean_code(imports, theorem, proof)

    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False, encoding="utf-8") as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    command = command_for_lean(command_lookup, tmp_path, home=lean_home, lean_project_dir=lean_project_dir)
    if command is None:
        Path(tmp_path).unlink(missing_ok=True)
        if lean_project_dir:
            return VerificationResult(
                success=False,
                status="setup_needed",
                errors="Lake is not available. Research benchmark mode needs `lake env lean` inside the Lean project.",
            )
        return VerificationResult(
            success=False,
            status="setup_needed",
            errors="Lean is not available. Install elan/Lean 4 so the plain `lean` command is on PATH.",
        )

    start = perf_counter()
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=lean_project_dir or None,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((perf_counter() - start) * 1000)
        return VerificationResult(
            success=False,
            status="timeout",
            errors=f"Lean verification timed out after {timeout_s}s.",
            command=command,
            elapsed_ms=elapsed,
        )
    except FileNotFoundError as exc:
        return VerificationResult(
            success=False,
            status="setup_needed",
            errors=f"Lean command unavailable: {exc}",
            command=command,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    elapsed = int((perf_counter() - start) * 1000)
    output = (process.stdout or "") + (process.stderr or "")
    return VerificationResult(
        success=process.returncode == 0,
        status="success" if process.returncode == 0 else "failed",
        errors="" if process.returncode == 0 else output.strip(),
        raw_output=output,
        command=command,
        elapsed_ms=elapsed,
    )
