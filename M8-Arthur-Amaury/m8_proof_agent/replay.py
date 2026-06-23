from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .models import ProofTrace


ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = ROOT / "traces"


def load_trace(path: Path | str) -> ProofTrace:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    return ProofTrace(**data)


def list_traces(directory: Path | str = TRACE_DIR) -> List[Dict[str, str]]:
    root = Path(directory)
    if not root.exists():
        return []
    traces: List[Dict[str, str]] = []
    for path in sorted(root.glob("*.json")):
        trace = load_trace(path)
        traces.append(
            {
                "file": path.name,
                "run_id": trace.run_id,
                "theorem_id": trace.theorem.id,
                "status": trace.status,
            }
        )
    return traces


def resolve_trace(filename: str) -> Path:
    path = (TRACE_DIR / filename).resolve()
    if not str(path).startswith(str(TRACE_DIR.resolve())):
        raise ValueError("Trace path escapes trace directory")
    return path

