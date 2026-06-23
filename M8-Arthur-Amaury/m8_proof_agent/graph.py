from __future__ import annotations

import inspect
from time import perf_counter
from typing import Callable, List
from uuid import uuid4

from .models import AgentRole, Benchmark, LeanResult, ProofAttempt, ProofCandidate, ProofTrace, TraceEvent
from .providers import CandidateProvider, ProviderError
from .verifier import verify_lean


VerifyFn = Callable[..., LeanResult]


def langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except Exception:
        return False
    return True


class EventBuilder:
    def __init__(self) -> None:
        self.events: List[TraceEvent] = []

    def add(self, kind: str, agent: AgentRole, message: str, **payload: object) -> None:
        self.events.append(
            TraceEvent(index=len(self.events) + 1, kind=kind, agent=agent, message=message, payload=dict(payload))
        )


def _verify_candidate(verify_fn: VerifyFn, theorem: Benchmark, proof: str) -> LeanResult:
    signature = inspect.signature(verify_fn)
    supports_project_dir = "lean_project_dir" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    if supports_project_dir:
        return verify_fn(theorem.imports, theorem.statement, proof, lean_project_dir=theorem.lean_project_dir)
    return verify_fn(theorem.imports, theorem.statement, proof)


def run_proof_graph(
    theorem: Benchmark,
    provider: CandidateProvider,
    verify_fn: VerifyFn = verify_lean,
    max_attempts: int = 3,
) -> ProofTrace:
    started = perf_counter()
    events = EventBuilder()
    attempts: List[ProofAttempt] = []
    errors: List[str] = []
    final_proof = None
    status = "failed"
    error = ""

    events.add("run_started", AgentRole.ORCHESTRATOR, f"Starting proof search for {theorem.id}")
    events.add("plan_created", AgentRole.DECOMPOSER, "Created tactic-oriented proof plan", expected_tactics=theorem.expected_tactics)

    for iteration in range(1, max(1, min(max_attempts, 8)) + 1):
        agent = AgentRole.TACTIC if iteration == 1 else AgentRole.REPAIR
        events.add("agent_started", agent, f"Generating candidate proof for iteration {iteration}")
        context = {
            "theorem_id": theorem.id,
            "imports": theorem.imports,
            "statement": theorem.statement,
            "expected_tactics": theorem.expected_tactics,
            "errors": errors[-3:],
            "iteration": iteration,
        }
        try:
            candidates = provider.generate_candidates(context)
        except ProviderError as exc:
            status = "provider_error"
            error = str(exc)
            events.add("provider_error", agent, error)
            break

        for candidate in candidates:
            events.add("candidate_created", agent, candidate.rationale, proof=candidate.proof)
            verification = _verify_candidate(verify_fn, theorem, candidate.proof)
            attempts.append(
                ProofAttempt(
                    iteration=iteration,
                    agent=agent,
                    proof=candidate.proof,
                    rationale=candidate.rationale,
                    verification=verification,
                )
            )
            events.add(
                "verification_finished",
                AgentRole.VERIFIER,
                "Lean accepted the candidate" if verification.success else "Lean rejected the candidate",
                status=verification.status,
                errors=verification.errors,
            )
            if verification.success:
                final_proof = candidate.proof
                status = "success"
                events.add("final_verified", AgentRole.ASSEMBLER, "Final proof accepted by Lean", proof=final_proof)
                break
            if verification.status == "setup_needed":
                status = "setup_needed"
                error = verification.errors or "Lean setup is missing"
                events.add("setup_needed", AgentRole.VERIFIER, error)
                break
            errors.append(verification.errors or verification.output or "Lean rejected the proof")
        if status in {"success", "setup_needed"}:
            break
        if errors:
            events.add("repair_requested", AgentRole.REPAIR, "Sending Lean errors to repair agent", errors=errors[-3:])

    if status == "failed" and not error:
        error = "proof budget exhausted"
        events.add("budget_exhausted", AgentRole.ORCHESTRATOR, error)

    elapsed = int((perf_counter() - started) * 1000)
    events.add("trace_recorded", AgentRole.TRACE_RECORDER, "Trace ready for replay", elapsed_ms=elapsed)
    return ProofTrace(
        run_id=f"run-{uuid4().hex[:10]}",
        theorem=theorem,
        mode="real",
        provider=provider.name,
        model=provider.model,
        status=status,  # type: ignore[arg-type]
        events=events.events,
        attempts=attempts,
        final_proof=final_proof,
        error=error,
        elapsed_ms=elapsed,
    )


__all__ = ["ProofCandidate", "run_proof_graph", "langgraph_available"]
