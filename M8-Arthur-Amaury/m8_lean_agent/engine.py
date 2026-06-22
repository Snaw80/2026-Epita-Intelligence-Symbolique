"""Hybrid LLM -> Lean -> repair loop."""

from __future__ import annotations

import inspect
from time import time
from typing import Callable, Dict, List, Sequence, Union

from .benchmarks import find_benchmark, load_benchmarks
from .models import Benchmark, BenchmarkSuiteResult, ProofAttempt, ProofSessionResult, VerificationResult
from .providers import BaseProvider, ProviderError, get_provider
from .verifier import verify_lean


VerifyFn = Callable[[str, str, str], VerificationResult]


def _as_benchmark(theorem: Union[Benchmark, Dict[str, object], str]) -> Benchmark:
    if isinstance(theorem, Benchmark):
        return theorem
    if isinstance(theorem, str):
        return find_benchmark(theorem, load_benchmarks())
    return Benchmark(
        id=str(theorem.get("id", "custom")),
        title=str(theorem.get("title", "Custom theorem")),
        difficulty=str(theorem.get("difficulty", "custom")),
        imports=str(theorem.get("imports", "")),
        statement=str(theorem.get("statement", "")),
        description=str(theorem.get("description", "")),
        expected_tactics=[str(item) for item in theorem.get("expected_tactics", [])],
        source=str(theorem.get("source", "")),
        lean_project_dir=str(theorem.get("lean_project_dir", "")),
    )


def _as_provider(provider: Union[str, BaseProvider], model: str = "") -> BaseProvider:
    if isinstance(provider, BaseProvider):
        return provider
    return get_provider(provider, model or None)


def _verify_candidate(
    verify_fn: VerifyFn,
    benchmark: Benchmark,
    proof: str,
) -> VerificationResult:
    parameters = inspect.signature(verify_fn).parameters
    supports_project_dir = "lean_project_dir" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    if supports_project_dir:
        return verify_fn(
            benchmark.imports,
            benchmark.statement,
            proof,
            lean_project_dir=benchmark.lean_project_dir or None,
        )
    return verify_fn(benchmark.imports, benchmark.statement, proof)


def run_proof_session(
    theorem: Union[Benchmark, Dict[str, object], str],
    provider: Union[str, BaseProvider] = "mistral",
    max_iterations: int = 3,
    verify_fn: VerifyFn = verify_lean,
    model: str = "",
) -> ProofSessionResult:
    benchmark = _as_benchmark(theorem)
    started = time()
    attempts: List[ProofAttempt] = []
    token_usage: Dict[str, int] = {}

    try:
        proof_provider = _as_provider(provider, model)
    except ProviderError as exc:
        finished = time()
        return ProofSessionResult(
            theorem_id=benchmark.id,
            theorem_title=benchmark.title,
            provider=str(provider),
            model=model,
            status="provider_error",
            attempts=[],
            final_proof=None,
            error=str(exc),
            token_usage={},
            started_at=started,
            finished_at=finished,
        )

    error_history: List[str] = []
    status = "failed"
    final_proof = None
    provider_error = ""

    for iteration in range(1, max_iterations + 1):
        context = {
            "theorem_id": benchmark.id,
            "theorem": benchmark.statement,
            "imports": benchmark.imports,
            "iteration": iteration,
            "errors": error_history[-4:],
        }
        try:
            candidates = proof_provider.generate_candidates(context)
        except ProviderError as exc:
            status = "provider_error"
            provider_error = str(exc)
            error_history.append(provider_error)
            break

        for index, candidate in enumerate(candidates, start=1):
            verification = _verify_candidate(verify_fn, benchmark, candidate.proof)
            attempts.append(
                ProofAttempt(
                    iteration=iteration,
                    candidate_index=index,
                    proof=candidate.proof,
                    rationale=candidate.rationale,
                    verification=verification,
                )
            )
            if verification.success:
                status = "success"
                final_proof = candidate.proof
                break
            if verification.status == "setup_needed":
                status = "setup_needed"
                break
            error_history.append(verification.errors)
        for key, value in getattr(proof_provider, "last_token_usage", {}).items():
            token_usage[key] = token_usage.get(key, 0) + value
        if status in {"success", "setup_needed"}:
            break

    finished = time()
    return ProofSessionResult(
        theorem_id=benchmark.id,
        theorem_title=benchmark.title,
        provider=proof_provider.name,
        model=proof_provider.model,
        status=status,
        attempts=attempts,
        final_proof=final_proof,
        error=provider_error if status == "provider_error" else "",
        token_usage=token_usage,
        started_at=started,
        finished_at=finished,
    )


def run_benchmark_suite(
    suite_name: str,
    benchmarks: Sequence[Benchmark],
    provider: Union[str, BaseProvider] = "mistral",
    max_iterations: int = 3,
    limit: int = 0,
    verify_fn: VerifyFn = verify_lean,
    model: str = "",
) -> BenchmarkSuiteResult:
    started = time()
    selected = list(benchmarks[:limit] if limit and limit > 0 else benchmarks)
    try:
        proof_provider = _as_provider(provider, model)
    except ProviderError as exc:
        finished = time()
        return BenchmarkSuiteResult(
            suite=suite_name,
            provider=str(provider),
            model=model,
            status="provider_error",
            sessions=[],
            started_at=started,
            finished_at=finished,
            error=str(exc),
        )

    sessions = [
        run_proof_session(
            theorem=benchmark,
            provider=proof_provider,
            max_iterations=max_iterations,
            verify_fn=verify_fn,
            model=model,
        )
        for benchmark in selected
    ]
    finished = time()
    status = "success" if sessions and all(session.status == "success" for session in sessions) else "completed"
    return BenchmarkSuiteResult(
        suite=suite_name,
        provider=proof_provider.name,
        model=proof_provider.model,
        status=status,
        sessions=sessions,
        started_at=started,
        finished_at=finished,
    )
