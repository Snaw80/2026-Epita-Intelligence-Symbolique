"""Typed data structures for the Lean proof-agent demo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import time
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class Benchmark:
    id: str
    title: str
    difficulty: str
    imports: str
    statement: str
    description: str = ""
    expected_tactics: List[str] = field(default_factory=list)
    source: str = ""
    lean_project_dir: str = ""


@dataclass
class ProofCandidate:
    proof: str
    rationale: str = ""
    source: str = "llm"
    confidence: Optional[float] = None


@dataclass
class VerificationResult:
    success: bool
    status: str
    errors: str
    raw_output: str = ""
    command: List[str] = field(default_factory=list)
    elapsed_ms: int = 0


@dataclass
class ProofAttempt:
    iteration: int
    candidate_index: int
    proof: str
    rationale: str
    verification: VerificationResult

    def to_trace_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["success"] = self.verification.success
        data["status"] = self.verification.status
        data["errors"] = self.verification.errors
        return data


@dataclass
class ProofSessionResult:
    theorem_id: str
    theorem_title: str
    provider: str
    model: str
    status: str
    attempts: List[ProofAttempt]
    final_proof: Optional[str] = None
    error: str = ""
    token_usage: Dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time)
    finished_at: float = field(default_factory=time)
    session_id: str = field(default_factory=lambda: str(uuid4())[:8])

    @property
    def elapsed_ms(self) -> int:
        return int((self.finished_at - self.started_at) * 1000)

    def to_trace_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "theorem_id": self.theorem_id,
            "theorem_title": self.theorem_title,
            "status": self.status,
            "attempts": [attempt.to_trace_dict() for attempt in self.attempts],
            "final_proof": self.final_proof,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "token_usage": dict(self.token_usage),
        }


@dataclass
class BenchmarkSuiteResult:
    suite: str
    provider: str
    model: str
    status: str
    sessions: List[ProofSessionResult]
    started_at: float = field(default_factory=time)
    finished_at: float = field(default_factory=time)
    error: str = ""
    suite_id: str = field(default_factory=lambda: str(uuid4())[:8])

    @property
    def elapsed_ms(self) -> int:
        return int((self.finished_at - self.started_at) * 1000)

    @property
    def total(self) -> int:
        return len(self.sessions)

    @property
    def success(self) -> int:
        return sum(1 for session in self.sessions if session.status == "success")

    @property
    def failed(self) -> int:
        return self.total - self.success

    @property
    def first_try_success(self) -> int:
        return sum(
            1
            for session in self.sessions
            if session.status == "success"
            and session.attempts
            and session.attempts[0].verification.success
        )

    @property
    def average_attempts(self) -> float:
        if not self.sessions:
            return 0.0
        return round(sum(len(session.attempts) for session in self.sessions) / len(self.sessions), 2)

    def to_trace_dict(self) -> Dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "suite": self.suite,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "first_try_success": self.first_try_success,
            "average_attempts": self.average_attempts,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "sessions": [session.to_trace_dict() for session in self.sessions],
        }
