# M8 - Lean Proof Agent Demo

Functional demo for the EPITA SCIA subject **M8 - Demonstration automatique
neuro-symbolique : agent LLM pour Lean 4**.

The app demonstrates a hybrid loop:

1. An LLM proposes Lean tactic proofs.
2. A deterministic verifier runs Lean.
3. Lean errors are fed back to the LLM for repair.
4. The session stops on a verified proof, setup issue, provider issue, or budget exhaustion.

Lean is always the correctness judge. LLM providers only propose candidate
proofs; they never validate them.

## Quick Start

```bash
python3 M8-Arthur-Amaury/app.py
```

Open <http://127.0.0.1:8787>. Configure one provider key before running a live
proof search. The app itself has no Python package dependencies.

Run tests:

```bash
python3 -m unittest discover -s M8-Arthur-Amaury/tests
```

## Providers

### Mistral

```bash
export MISTRAL_API_KEY="..."
export MISTRAL_MODEL="mistral-small-latest"
python3 M8-Arthur-Amaury/app.py
```

The endpoint defaults to `https://api.mistral.ai/v1/chat/completions`.

### OpenAI-compatible

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"
# Optional for OpenRouter or local OpenAI-compatible servers:
export OPENAI_BASE_URL="https://api.openai.com/v1"
python3 M8-Arthur-Amaury/app.py
```

## Lean Setup

For real verification, install Lean 4 through `elan` so `lean` is available on
the PATH.

```bash
bash M8-Arthur-Amaury/setup_lean.sh
python3 M8-Arthur-Amaury/check_lean.py
```

The verifier deliberately uses plain `lean` only. Lake is not required for this
demo because the bundled benchmarks are small stdlib snippets. If `lean` is not
found, the app returns `setup_needed` instead of crashing.

## API

- `GET /api/benchmarks`: returns the 8 bundled Lean theorem tasks.
- `GET /api/health`: reports Python, Lean availability, and provider keys.
- `POST /api/run`: runs a proof session.
- `POST /api/run-benchmark`: runs a full benchmark suite sequentially.

Example payload:

```json
{
  "theorem_id": "nat_zero_add",
  "provider": "mistral",
  "max_iterations": 3
}
```

The response is a trace JSON with provider, model, theorem id, attempts, Lean
errors, final status, timing, and token usage when the provider reports it.

Batch benchmark payload:

```json
{
  "suite": "smoke",
  "provider": "mistral",
  "max_iterations": 3,
  "limit": 0
}
```

Use `limit` to run a small prefix before spending a full API budget.

## Research Benchmark Mode

The normal `smoke` suite uses plain `lean`. Research suites can opt into a Lean
project, which makes the verifier run:

```bash
lake env lean /tmp/generated-proof-file.lean
```

from the configured project directory. This is useful for datasets that depend
on Mathlib or project-local definitions, such as PutnamBench.

Example `.env`:

```bash
MISTRAL_API_KEY="..."
RESEARCH_BENCHMARK_PATH="/absolute/path/to/M8-Arthur-Amaury/research_benchmarks.json"
RESEARCH_LEAN_PROJECT_DIR="/absolute/path/to/PutnamBench/lean4"
```

Each research JSON entry can also set its own `lean_project_dir`; that per-task
value wins over the shared `RESEARCH_LEAN_PROJECT_DIR`.

Generate a PutnamBench research suite from a local clone:

```bash
git clone https://github.com/trishullab/PutnamBench /absolute/path/to/PutnamBench
cd /absolute/path/to/PutnamBench/lean4
lake exe cache get
lake build
cd /absolute/path/to/2026-Epita-Intelligence-Symbolique
python3 M8-Arthur-Amaury/import_putnam.py /absolute/path/to/PutnamBench/lean4 --limit 50
```

Then select `research` in the UI and run the full benchmark. Start with
`--limit 10` or a UI limit before spending a larger API budget.

```json
[
  {
    "id": "putnam_1962_a1",
    "title": "PutnamBench 1962 A1",
    "difficulty": "research",
    "imports": "import Mathlib",
    "statement": "theorem putnam_1962_a1 : True",
    "source": "PutnamBench",
    "lean_project_dir": "/absolute/path/to/PutnamBench/lean4"
  }
]
```

PutnamBench is a good first target: its README reports 672 Lean 4
formalizations, sourced from the William Lowell Putnam Mathematical Competition.
The Lean 4 folder is a Lake project and imports Mathlib, so it fits this
optional research mode.

The importer skips statements mentioning `*_solution` placeholders by default,
because those factored-answer tasks need extra generated context. Use
`--include-solution-placeholders` only after preparing that context.

## Presentation Story

Recommended 10-minute demo arc:

1. Show a small theorem such as `logic_true` to explain the loop.
2. Show a repair example such as `nat_zero_add`: first candidate fails, second succeeds.
3. Compare Mistral with an OpenAI-compatible provider if both API keys are configured.
4. Explain why Lean, not the LLM, is trusted.
5. Discuss failure modes: syntax hallucination, wrong tactic, missing lemma, timeout, missing mathematical infrastructure.

## References

- M8 subject README: <https://github.com/jsboigeEpita/2026-Epita-Intelligence-Symbolique>
- Mistral Chat Completion API: <https://docs.mistral.ai/api/>
- LeanDojo: <https://arxiv.org/abs/2306.15626>
- LeanCopilot: <https://arxiv.org/abs/2404.12534>
- AlphaProof: <https://deepmind.google/discover/blog/ai-solves-imo-problems-at-silver-medal-level/>
- APOLLO: <https://arxiv.org/abs/2505.05758>
