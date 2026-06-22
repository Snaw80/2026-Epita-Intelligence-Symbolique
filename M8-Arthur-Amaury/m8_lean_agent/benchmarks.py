"""Benchmark loading for the Lean proof-agent demo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Union

from .models import Benchmark


DEFAULT_BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "benchmarks.json"


def _require_text(item: dict, key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"benchmark entry missing non-empty string field {key!r}")
    return value


def load_benchmarks(path: Union[str, Path] = DEFAULT_BENCHMARK_PATH) -> List[Benchmark]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("benchmark file must contain a JSON list")

    benchmarks = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("benchmark entries must be JSON objects")
        tactics = item.get("expected_tactics", [])
        if not isinstance(tactics, list):
            raise ValueError("expected_tactics must be a list")
        benchmarks.append(
            Benchmark(
                id=_require_text(item, "id"),
                title=_require_text(item, "title"),
                difficulty=_require_text(item, "difficulty"),
                imports=item.get("imports", ""),
                statement=_require_text(item, "statement"),
                description=item.get("description", ""),
                expected_tactics=[str(tactic) for tactic in tactics],
                source=str(item.get("source", "")),
                lean_project_dir=str(item.get("lean_project_dir", "")),
            )
        )
    return benchmarks


def find_benchmark(benchmark_id: str, benchmarks: Iterable[Benchmark]) -> Benchmark:
    for benchmark in benchmarks:
        if benchmark.id == benchmark_id:
            return benchmark
    raise KeyError(f"unknown benchmark id: {benchmark_id}")
