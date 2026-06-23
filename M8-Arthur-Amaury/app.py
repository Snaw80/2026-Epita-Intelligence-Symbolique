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

from m8_proof_agent.benchmarks import find_benchmark, load_all_benchmarks, load_benchmarks
from m8_proof_agent.graph import langgraph_available, run_proof_graph
from m8_proof_agent.models import Benchmark, RunRequest, model_to_dict
from m8_proof_agent.providers import ProviderError, get_provider
from m8_proof_agent.replay import list_traces, load_trace, resolve_trace
from m8_proof_agent.verifier import find_lean, verify_lean


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
VERIFY_FN = verify_lean


def load_dotenv(path: Path | str = ROOT / ".env", environ: Dict[str, str] = os.environ) -> None:
    env_path = Path(path)
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


def _json_body(body: bytes) -> Dict[str, Any]:
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def apply_environment_to_benchmark(benchmark: Benchmark, environ: Dict[str, str] = os.environ) -> Benchmark:
    if benchmark.lean_project_dir:
        return benchmark
    project_dir = environ.get("M8_LEAN_PROJECT_DIR") or environ.get("RESEARCH_LEAN_PROJECT_DIR")
    if project_dir and "import Mathlib" in benchmark.imports:
        data = model_to_dict(benchmark)
        data["lean_project_dir"] = project_dir
        return Benchmark(**data)
    return benchmark


def api_response(method: str, path: str, body: bytes) -> Tuple[int, Dict[str, Any]]:
    load_dotenv()
    route = urlparse(path).path
    if method == "GET" and route == "/api/health":
        return 200, {
            "python": platform.python_version(),
            "lean": find_lean(),
            "lake": shutil.which("lake"),
            "langgraph_available": langgraph_available(),
            "providers": {
                "demo": True,
                "openai_compatible": bool(os.getenv("OPENAI_API_KEY")),
            },
        }

    if method == "GET" and route == "/api/benchmarks":
        return 200, {"benchmarks": [model_to_dict(apply_environment_to_benchmark(item)) for item in load_all_benchmarks()]}

    if method == "GET" and route == "/api/traces":
        return 200, {"traces": list_traces()}

    if method == "POST" and route == "/api/replay":
        try:
            payload = _json_body(body)
            trace = load_trace(resolve_trace(str(payload.get("trace") or "")))
        except (ValueError, FileNotFoundError) as exc:
            return 400, {"error": str(exc)}
        return 200, {"trace": model_to_dict(trace)}

    if method == "POST" and route == "/api/run":
        try:
            payload = _json_body(body)
            request = RunRequest(**payload)
            theorem = apply_environment_to_benchmark(find_benchmark(request.theorem_id, load_benchmarks(suite=request.suite)))
            provider = get_provider(request.provider, request.model)
            trace = run_proof_graph(theorem, provider, verify_fn=VERIFY_FN, max_attempts=request.max_attempts)
        except (ValueError, KeyError, ProviderError) as exc:
            return 400, {"error": str(exc)}
        return 200, {"trace": model_to_dict(trace)}

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
        status, payload = api_response("POST", self.path, self.rfile.read(length))
        self._send_json(status, payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[m8] {self.address_string()} - {fmt % args}")


def run_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"M8 Lean Proof Agent running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server(port=int(os.getenv("PORT", "8787")))
