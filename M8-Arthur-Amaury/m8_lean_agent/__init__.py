"""M8 Lean proof-agent demo package."""

from .benchmarks import load_benchmarks
from .engine import run_proof_session
from .verifier import verify_lean

__all__ = ["load_benchmarks", "run_proof_session", "verify_lean"]
