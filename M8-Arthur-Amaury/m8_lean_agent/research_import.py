"""Import helpers for external Lean research benchmarks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Sequence


THEOREM_RE = re.compile(
    r"(?:/--.*?-/\s*)?^\s*theorem\s+([A-Za-z_][A-Za-z0-9_'.]*)\b(.*?)(?=:=)",
    flags=re.M | re.S,
)
IMPORT_RE = re.compile(r"^\s*import\s+.+$", flags=re.M)


def _title_from_id(theorem_id: str) -> str:
    return theorem_id.replace("_", " ").replace("-", " ").strip().title()


def _extract_imports(text: str) -> str:
    imports = [match.group(0).strip() for match in IMPORT_RE.finditer(text)]
    return "\n".join(imports) if imports else "import Mathlib"


def _lean_files(project_dir: Path) -> Sequence[Path]:
    source_dir = project_dir / "src"
    root = source_dir if source_dir.exists() else project_dir
    return sorted(root.rglob("*.lean"))


def extract_putnam_benchmarks(
    lean_project_dir: Path,
    *,
    limit: int = 0,
    include_solution_placeholders: bool = False,
) -> List[Dict[str, object]]:
    project_dir = Path(lean_project_dir).expanduser().resolve()
    if not project_dir.exists():
        raise FileNotFoundError(f"Lean project directory does not exist: {project_dir}")

    benchmarks: List[Dict[str, object]] = []
    for path in _lean_files(project_dir):
        text = path.read_text(encoding="utf-8")
        imports = _extract_imports(text)
        relative = path.relative_to(project_dir)
        for match in THEOREM_RE.finditer(text):
            theorem_id = match.group(1)
            statement = f"theorem {theorem_id}{match.group(2)}"
            statement = re.sub(r"\s+", " ", statement).strip()
            if not include_solution_placeholders and "_solution" in statement:
                continue
            benchmarks.append(
                {
                    "id": theorem_id,
                    "title": _title_from_id(theorem_id),
                    "difficulty": "research",
                    "imports": imports,
                    "statement": statement,
                    "description": f"Imported from PutnamBench Lean file {relative}.",
                    "expected_tactics": [],
                    "source": "PutnamBench",
                    "lean_project_dir": str(project_dir),
                }
            )
            if limit and len(benchmarks) >= limit:
                return benchmarks
    return benchmarks


def write_putnam_benchmarks(
    lean_project_dir: Path,
    output_path: Path,
    *,
    limit: int = 0,
    include_solution_placeholders: bool = False,
) -> int:
    benchmarks = extract_putnam_benchmarks(
        lean_project_dir,
        limit=limit,
        include_solution_placeholders=include_solution_placeholders,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(benchmarks, indent=2) + "\n", encoding="utf-8")
    return len(benchmarks)
