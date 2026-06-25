# M8 Multi-Agent Lean Proof Agent

Fresh demo app for **M8 - Demonstration automatique neuro-symbolique : agent LLM pour Lean 4**.

The demo uses a multi-agent proof loop:

1. The orchestrator loads a theorem from the smoke suite or the miniF2F starter subset.
2. Proof agents propose Lean tactic bodies.
3. Lean verifies each candidate through `lean` or `lake env lean`.
4. Failed Lean output is fed to the repair loop.
5. Successful runs are represented as JSON traces and can be replayed during the presentation.

Lean is the trust boundary: agents propose, Lean verifies.

## Run

```bash
M8-Arthur-Amaury/.venv/bin/python M8-Arthur-Amaury/app.py
```

Open <http://127.0.0.1:8787>.

## Install

```bash
python3 -m venv M8-Arthur-Amaury/.venv
M8-Arthur-Amaury/.venv/bin/python -m pip install -r M8-Arthur-Amaury/requirements.txt
```

## Test

```bash
M8-Arthur-Amaury/.venv/bin/python -m unittest discover -s M8-Arthur-Amaury/tests -v
```

## Modes

- `replay`: loads the newest saved trace from `M8-Arthur-Amaury/traces/`.
- `real run`: calls a provider and verifies the candidate proof locally.
- `Run suite`: runs every theorem in the selected suite, saves one trace per theorem, and reports solved/attempted accuracy. Click `Open` in the score table to inspect one theorem's latest saved trace.

Configure `OPENAI_API_KEY`, `OPENAI_MODEL`, and optionally `OPENAI_BASE_URL` to use OpenAI. Configure `MISTRAL_API_KEY`, `MISTRAL_MODEL`, and optionally `MISTRAL_BASE_URL` to add Mistral to the provider list.

The app loads `M8-Arthur-Amaury/.env` automatically and does not overwrite variables already set in the shell.

## miniF2F-v2

The `minif2f_v2s` suite is generated from the simplified miniF2F-v2 dataset and contains 488 Lean 4 / Mathlib-style theorem statements. Refresh it with:

```bash
M8-Arthur-Amaury/.venv/bin/python M8-Arthur-Amaury/scripts/import_minif2f_v2.py --suite minif2f_v2s
```

The importer reads the dataset JSONL fields `name`, `split`, `header`, `formal_statement`, and informal statement text, then writes `M8-Arthur-Amaury/benchmarks/minif2f_v2s.json`.

## Mathlib / miniF2F

Benchmarks that import Mathlib must be verified from a Lake project that has Mathlib available. Set:

```bash
M8_LEAN_PROJECT_DIR="/absolute/path/to/lean/project/with/mathlib"
```

When this variable is present, Mathlib benchmarks run with:

```bash
lake env lean /tmp/generated-candidate.lean
```

If a theorem imports Mathlib and no project is configured, the app returns `setup_needed` immediately instead of wasting LLM repair attempts on an environment problem.

## Stack

- Python 3.9+
- Pydantic data contracts
- Optional LangGraph dependency for the intended orchestration runtime
- Direct Lean subprocess verifier
- Vanilla browser UI

LeanDojo is intentionally not a v1 dependency. It remains research context for proof-state interaction and benchmark infrastructure.
