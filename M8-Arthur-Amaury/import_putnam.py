"""Generate research_benchmarks.json from a local PutnamBench Lean 4 project."""

from __future__ import annotations

import argparse
from pathlib import Path

from m8_lean_agent.research_import import write_putnam_benchmarks


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lean_project_dir", help="Path to PutnamBench/lean4")
    parser.add_argument(
        "--output",
        default=str(ROOT / "research_benchmarks.json"),
        help="Output JSON path. Defaults to M8-Arthur-Amaury/research_benchmarks.json.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of theorems to export. 0 means all.")
    parser.add_argument(
        "--include-solution-placeholders",
        action="store_true",
        help="Include statements that mention *_solution placeholders.",
    )
    args = parser.parse_args()

    count = write_putnam_benchmarks(
        Path(args.lean_project_dir),
        Path(args.output),
        limit=max(0, args.limit),
        include_solution_placeholders=args.include_solution_placeholders,
    )
    print(f"Wrote {count} PutnamBench tasks to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
