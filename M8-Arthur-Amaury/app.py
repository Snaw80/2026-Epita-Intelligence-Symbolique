"""Local web app for the M8 Lean proof-agent demo.

Run from the repository root or this directory:

    python3 M8-Arthur-Amaury/app.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from m8_lean_agent.benchmarks import find_benchmark, load_benchmarks
from m8_lean_agent.engine import run_benchmark_suite, run_proof_session
from m8_lean_agent.models import Benchmark
from m8_lean_agent.verifier import find_lean_binary


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
LEAN_HOME_OVERRIDE = None
LEAN_COMMAND_LOOKUP = shutil.which
ENV_PATH_OVERRIDE = None
BENCHMARK_SUITES = {
    "smoke": ROOT / "benchmarks.json",
    "research": ROOT / "research_benchmarks.json",
}


def load_dotenv(path: Path = None, environ: Dict[str, str] = os.environ) -> None:
    env_path = Path(path or ENV_PATH_OVERRIDE or ROOT / ".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        environ[key] = value


def _benchmark_dict(benchmark: Benchmark) -> Dict[str, Any]:
    return {
        "id": benchmark.id,
        "title": benchmark.title,
        "difficulty": benchmark.difficulty,
        "imports": benchmark.imports,
        "statement": benchmark.statement,
        "description": benchmark.description,
        "expected_tactics": benchmark.expected_tactics,
        "source": benchmark.source,
        "lean_project_dir": benchmark.lean_project_dir,
    }


def _load_suite(name: str):
    suite_name = name if name in BENCHMARK_SUITES else "smoke"
    suite_path = Path(os.getenv("RESEARCH_BENCHMARK_PATH", "")) if suite_name == "research" and os.getenv("RESEARCH_BENCHMARK_PATH") else BENCHMARK_SUITES[suite_name]
    if not suite_path.exists():
        if suite_name == "research":
            raise FileNotFoundError(
                f"Benchmark suite 'research' is not configured at {suite_path}. "
                "Generate it with: python3 M8-Arthur-Amaury/import_putnam.py /absolute/path/to/PutnamBench/lean4"
            )
        raise FileNotFoundError(f"Benchmark suite {suite_name!r} is not configured at {suite_path}")
    benchmarks = load_benchmarks(suite_path)
    research_project_dir = os.getenv("RESEARCH_LEAN_PROJECT_DIR", "")
    if suite_name == "research" and research_project_dir:
        for benchmark in benchmarks:
            if not benchmark.lean_project_dir:
                benchmark.lean_project_dir = research_project_dir
    return suite_name, benchmarks


def _theorem_from_payload(payload: Dict[str, Any]) -> Benchmark:
    benchmarks = load_benchmarks(ROOT / "benchmarks.json")
    theorem_id = str(payload.get("theorem_id") or "")
    if theorem_id:
        base = find_benchmark(theorem_id, benchmarks)
    else:
        base = Benchmark(
            id="custom",
            title="Custom theorem",
            difficulty="custom",
            imports="",
            statement="",
            description="",
            expected_tactics=["simp", "trivial", "rfl"],
        )

    statement = str(payload.get("statement") or base.statement).strip()
    imports = str(payload.get("imports") if payload.get("imports") is not None else base.imports)
    title = str(payload.get("title") or base.title)
    return Benchmark(
        id=base.id,
        title=title,
        difficulty=base.difficulty,
        imports=imports,
        statement=statement,
        description=base.description,
        expected_tactics=base.expected_tactics,
    )


def _health_payload() -> Dict[str, Any]:
    load_dotenv()
    return {
        "python": platform.python_version(),
        "lean": find_lean_binary(LEAN_COMMAND_LOOKUP, home=LEAN_HOME_OVERRIDE),
        "providers": {
            "mistral": bool(os.getenv("MISTRAL_API_KEY")),
            "openai_compatible": bool(os.getenv("OPENAI_API_KEY")),
        },
    }


def api_response(method: str, path: str, body: bytes) -> Tuple[int, Dict[str, Any]]:
    route = urlparse(path).path
    if method == "GET" and route == "/api/benchmarks":
        benchmarks = load_benchmarks(ROOT / "benchmarks.json")
        return 200, {"benchmarks": [_benchmark_dict(item) for item in benchmarks]}

    if method == "GET" and route == "/api/health":
        return 200, _health_payload()

    if method == "POST" and route == "/api/run":
        load_dotenv()
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            return 400, {"error": f"Invalid JSON: {exc}"}

        benchmark = _theorem_from_payload(payload)
        provider = str(payload.get("provider") or "mistral")
        max_iterations = int(payload.get("max_iterations") or 3)
        model = str(payload.get("model") or "")

        result = run_proof_session(
            theorem=benchmark,
            provider=provider,
            max_iterations=max(1, min(max_iterations, 8)),
            model=model,
        )
        return 200, result.to_trace_dict()

    if method == "POST" and route == "/api/run-benchmark":
        load_dotenv()
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            return 400, {"error": f"Invalid JSON: {exc}"}

        suite = str(payload.get("suite") or "smoke")
        try:
            suite_name, benchmarks = _load_suite(suite)
        except FileNotFoundError as exc:
            return 400, {"error": str(exc)}

        provider = str(payload.get("provider") or "mistral")
        max_iterations = int(payload.get("max_iterations") or 3)
        limit = int(payload.get("limit") or 0)
        model = str(payload.get("model") or "")
        result = run_benchmark_suite(
            suite_name=suite_name,
            benchmarks=benchmarks,
            provider=provider,
            max_iterations=max(1, min(max_iterations, 8)),
            limit=max(0, limit),
            model=model,
        )
        return 200, result.to_trace_dict()

    return 404, {"error": f"No API route for {method} {route}"}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route.startswith("/api/"):
            status, payload = api_response("GET", self.path, b"")
            self._send_json(status, payload)
            return
        if route == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        static_path = (STATIC_DIR / route.removeprefix("/static/")).resolve()
        if str(static_path).startswith(str(STATIC_DIR.resolve())) and static_path.exists():
            self._send_file(static_path)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        status, payload = api_response("POST", self.path, body)
        self._send_json(status, payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[m8-demo] {self.address_string()} - {fmt % args}")


def run_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"M8 Lean Proof Agent demo running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    run_server(port=int(os.getenv("PORT", "8787")))
