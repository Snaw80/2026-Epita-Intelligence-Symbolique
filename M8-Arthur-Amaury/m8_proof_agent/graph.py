from __future__ import annotations

import inspect
from time import perf_counter
from typing import Callable, List, Optional
from uuid import uuid4

from .models import AgentRole, Benchmark, LeanResult, ProofAttempt, ProofCandidate, ProofTrace, TraceEvent
from .providers import CandidateProvider, ProviderError
from .verifier import verify_lean


VerifyFn = Callable[..., LeanResult]
GoalProbeFn = Callable[..., LeanResult]
EventSink = Callable[[TraceEvent], None]


def langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except Exception:
        return False
    return True


class EventBuilder:
    def __init__(self, started_at: float, sink: Optional[EventSink] = None) -> None:
        self.events: List[TraceEvent] = []
        self.started_at = started_at
        self.sink = sink

    def add(self, kind: str, agent: AgentRole, message: str, **payload: object) -> None:
        event_payload = dict(payload)
        event_payload.setdefault("elapsed_ms", int((perf_counter() - self.started_at) * 1000))
        event = TraceEvent(
            index=len(self.events) + 1,
            kind=kind,
            agent=agent,
            message=message,
            payload=event_payload,
        )
        self.events.append(event)
        if self.sink:
            self.sink(event)


def _verify_candidate(verify_fn: VerifyFn, theorem: Benchmark, proof: str) -> LeanResult:
    signature = inspect.signature(verify_fn)
    supports_project_dir = "lean_project_dir" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    if supports_project_dir:
        return verify_fn(theorem.imports, theorem.statement, proof, lean_project_dir=theorem.lean_project_dir)
    return verify_fn(theorem.imports, theorem.statement, proof)


def _probe_goal(goal_probe_fn: GoalProbeFn, theorem: Benchmark) -> LeanResult:
    signature = inspect.signature(goal_probe_fn)
    supports_project_dir = "lean_project_dir" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    if supports_project_dir:
        return goal_probe_fn(theorem.imports, theorem.statement, lean_project_dir=theorem.lean_project_dir)
    return goal_probe_fn(theorem.imports, theorem.statement)


def run_proof_graph(
    theorem: Benchmark,
    provider: CandidateProvider,
    verify_fn: VerifyFn = verify_lean,
    max_attempts: int = 3,
    beam_width: int = 1,
    goal_probe_fn: Optional[GoalProbeFn] = None,
    event_sink: Optional[EventSink] = None,
) -> ProofTrace:
    started = perf_counter()
    events = EventBuilder(started_at=started, sink=event_sink)
    attempts: List[ProofAttempt] = []
    errors: List[str] = []
    final_proof = None
    status = "failed"
    error = ""
    goal_state = ""
    effective_beam_width = max(1, min(beam_width, 5))

    events.add("run_started", AgentRole.ORCHESTRATOR, f"Starting proof search for {theorem.id}")
    events.add("plan_created", AgentRole.DECOMPOSER, "Created tactic-oriented proof plan", expected_tactics=theorem.expected_tactics)
    if goal_probe_fn:
        events.add("goal_probe_started", AgentRole.VERIFIER, "Asking Lean for the initial proof goal")
        goal_probe = _probe_goal(goal_probe_fn, theorem)
        goal_state = goal_probe.errors or goal_probe.output
        events.add(
            "goal_probe_finished" if goal_state else "goal_probe_skipped",
            AgentRole.VERIFIER,
            "Lean returned an initial goal state" if goal_state else "Lean goal probe produced no goal text",
            status=goal_probe.status,
            goal_state=goal_state,
            command=goal_probe.command,
            probe_elapsed_ms=goal_probe.elapsed_ms,
        )

    for iteration in range(1, max(1, min(max_attempts, 8)) + 1):
        agent = AgentRole.TACTIC if iteration == 1 else AgentRole.REPAIR
        events.add("agent_started", agent, f"Generating candidate proof for iteration {iteration}")
        events.add(
            "beam_started",
            agent,
            f"Requesting up to {effective_beam_width} proof candidate branch(es)",
            iteration=iteration,
            beam_width=effective_beam_width,
        )
        context = {
            "theorem_id": theorem.id,
            "imports": theorem.imports,
            "statement": theorem.statement,
            "expected_tactics": theorem.expected_tactics,
            "errors": errors[-3:],
            "goal_state": goal_state,
            "candidate_count": effective_beam_width,
            "beam_width": effective_beam_width,
            "iteration": iteration,
        }
        try:
            candidates = provider.generate_candidates(context)[:effective_beam_width]
        except ProviderError as exc:
            status = "provider_error"
            error = str(exc)
            events.add("provider_error", agent, error)
            break
        if not candidates:
            errors.append("Provider returned no proof candidates")
            events.add("beam_empty", agent, errors[-1], iteration=iteration, beam_width=effective_beam_width)
            continue

        for branch_index, candidate in enumerate(candidates, start=1):
            events.add(
                "candidate_created",
                agent,
                candidate.rationale,
                proof=candidate.proof,
                branch_index=branch_index,
                beam_width=effective_beam_width,
            )
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
                output=verification.output,
                command=verification.command,
                branch_index=branch_index,
                beam_width=effective_beam_width,
                verification_elapsed_ms=verification.elapsed_ms,
            )
            if verification.success:
                final_proof = candidate.proof
                status = "success"
                events.add(
                    "final_verified",
                    AgentRole.ASSEMBLER,
                    "Final proof accepted by Lean",
                    proof=final_proof,
                    branch_index=branch_index,
                    beam_width=effective_beam_width,
                )
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
