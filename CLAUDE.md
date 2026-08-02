# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Everything runs through `uv` (Python >= 3.11):

```bash
uv sync                                  # install deps (dev group included)
uv run pytest                            # full test suite (tests/, -q by default)
uv run pytest tests/test_loop.py         # one test file
uv run pytest tests/test_loop.py::test_name -v   # one test
uv run pytest --cov                      # coverage (branch, source=skillcell; 80% floor per contract)
uv run ruff check src tests             # lint (E,F,I,UP,B,SIM; line-length 100)
uv run mypy                              # strict typing, src/ only
uv run bandit -c pyproject.toml -r src   # security scan
uv run skillcell doctor                  # runtime readiness check
uv run skillcell validate examples/chain.yaml   # validate a Cell or Chain manifest
uv run skillcell run examples/cell.yaml --goal "triage firmware image" --json
```

`skillcell run` flags: `--goal` (required), `--act` (request act mode), `--authorized` (satisfies the authorization gate), `--json`.

## What this is

Phase 0 of an "agent-into-cell" system: instead of loading skills into one agent session, each skill becomes a **cell** — a mono-scoped workspace with its own contract, tool allowlist, LSP servers, agent loop, and (later) a pinned LoRA-adapted model. `docs/ARCHITECTURE.md` is the plan of record (phases 0–4: local runner → containers → adapter plane → Go orchestrator → k8s CRDs). Only the phase-0 local runner exists in code today; do not assume the orchestrator, container runtime, or adapter registry are implemented.

## Architecture (src/skillcell/, ~500 lines total)

Data flows: CLI → manifest → loop, with router and model as pluggable callables the loop receives.

- `manifest.py` — parses/validates CRD-shaped YAML (`apiVersion: skillcell.dev/v1alpha1`). `load_cell` (`kind: Cell`) parses `metadata.name`, `spec.scope`, `spec.runtime`, `spec.contract.inputs`/`outputs`, `spec.model` (plane, base, decode, endpoint, provider, base_url, adapter), `spec.tools`, and `spec.network`. `load_chain` (`kind: Chain`, first YAML document) parses `spec.nodes` (cell, `as` alias, inputs) and `spec.edges` (from/to), validating `${alias.outputs.x}` refs and edge endpoints against declared aliases. The `contract.eval`, `loop`, `lsp`, and `container` blocks shown in `examples/cell.yaml` are design-spec only — phase 0 does not parse or enforce them, so do not rely on them being enforced. See `examples/cell.yaml` and `examples/chain.yaml` for the full shapes.
- `loop.py` — the seven-stage in-cell loop: `align, review, select, gate, act, record, stop`. **Offline-first is the core invariant**: with no backend the loop still aligns, routes, gates, records, and stops with `act` marked `skipped`. Act mode additionally requires the authorization gate. Takes `Router` and `Backend` as plain callables (`Callable[[str], str]`) — keep that seam; don't couple the loop to concrete backends.
- `router.py` — deterministic keyword routing (order-stable tuple of rules → specialist name, `generalist` fallback). Determinism here is a contract, not an implementation detail: same goal must always select the same route.
- `model.py` — the model plane: four backends behind one `complete(prompt)` interface — `offline` (echo transport, exercises the plane with no network), `frontier` (Anthropic), `system` (local endpoint), `byok`. **API keys come from the environment by convention, never from the manifest**: `ANTHROPIC_API_KEY`, `SKILLCELL_SYSTEM_ENDPOINT`, `SKILLCELL_BYOK_KEY`.
- `evalgate.py` — the eval gate a cell must pass before reporting done.
- `cli.py` — `doctor`, `run`, and `validate` subcommands; exit 2 on manifest errors.

## Constraints

- **Determinism is the product.** Decode params pin temperature 0 / fixed seed; routing is order-stable; runs must be reproducible. Any change that introduces nondeterminism into the loop, router, or manifest handling breaks the core promise. (Claim is qualified: bit-reproducible on single-tenant local decode; see README core idea 3 — keep new claims equally qualified.)
- **Offline-first.** The default path must work with zero network and zero keys. New features need an offline behavior (done/skipped/blocked), not a hard dependency on a backend.
- **Security posture is deliberate**: cells are hermetic (tool allowlist, `network: deny` default), act mode is gated behind explicit authorization (`--act --authorized`). The example cell is a firmware-triage security workflow — the authorization gate exists because of it. Don't weaken these gates for convenience.
- **Licensing boundary**: everything outside `ee/` is Apache-2.0. `ee/` is reserved for the commercial edition (currently just a license file). Anything required to run one machine's cells stays in the Apache tree — never move core functionality under `ee/`.
- Built with TDD; `mypy` runs strict. Keep new code typed and tested to the existing standard.
