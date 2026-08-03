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
uv run skillcell validate examples/wordsmith.yaml   # validate a Cell or Chain manifest
uv run skillcell run examples/wordsmith.yaml --goal "tighten this" \
  --source NOTES.md --traces .skillcell/traces.jsonl   # exits 1 if the gate never passes
uv run skillcell traces .skillcell/traces.jsonl --json          # pass-rate summary
uv run skillcell traces .skillcell/traces.jsonl --export sft.jsonl   # rejection-sampled SFT data
uv run skillcell tui examples             # terminal UI (needs the 'tui' extra; dev group has it)
```

`skillcell run` flags: `--goal` (required), `--source` (file the gate checks), `--attempts` (override `loop.maxAttempts`), `--traces` (JSONL log path), `--act` (request act mode), `--authorized` (satisfies the authorization gate), `--json`.

## What this is

An "agent-into-cell" system: instead of loading skills into one agent session, each skill becomes a **cell** — a mono-scoped workspace with its own contract, tool allowlist, agent loop, and (later) a pinned LoRA-adapted model.

The thesis, as one causal chain: **bit-reproducibility is only available on single-tenant local decode → that means small models → small models need an adapter to be useful → and a hard gate to be correct.** The adapter makes small-model determinism *affordable*; the gate makes it *right*.

`docs/ARCHITECTURE.md` is the plan of record. Phases 0–1 (local runner; gate, retry, traces, container argv builders) exist in code. **Phase 2 — the adapter experiment — is the falsifiable core and has not been run.** Do not assume adapter training, the adapter registry, the orchestrator, or kube mode are implemented, and do not write copy that implies the adapter bet is proven.

## Architecture (src/skillcell/, ~500 lines total)

Data flows: CLI → manifest → loop, with router and model as pluggable callables the loop receives.

- `manifest.py` — parses/validates CRD-shaped YAML (`apiVersion: skillcell.dev/v1alpha1`). `load_cell` (`kind: Cell`) parses `metadata.name`, `spec.scope`, `spec.runtime`, `spec.contract.inputs`/`outputs`, `spec.contract.eval` (→ `EvalSpec`: `checks`, `coverageFloor`; the legacy single-script `eval.gate` becomes a `command` check), `spec.loop` (→ `LoopSpec`: `maxAttempts`, `stopOn`), `spec.model` (plane, base, decode, endpoint, provider, base_url, adapter), `spec.tools`, and `spec.network`. Checks are validated at parse time — a bad regex or unknown preserve class fails `skillcell validate`, not the run that depends on it. `load_chain` (`kind: Chain`, first YAML document) parses `spec.nodes` (cell, `as` alias, inputs) and `spec.edges` (from/to), validating `${alias.outputs.x}` refs and edge endpoints against declared aliases. `spec.container.devcontainer` is parsed into `ContainerCfg`. The `lsp` block shown in `examples/cell.yaml` is still design-spec only — not parsed or enforced.
- `verify.py` — the composable gate, and **the most important module in the repo**. Check kinds: `command` (exit code), `require`/`forbid` (regex), `preserves` (numbers, urls, emails, acronyms, negations), `max_edit_ratio`. Every check is offline, model-free, and a pure function of `(source, output)` or a subprocess exit code. The gate does three jobs with one artifact: runtime guarantee, training-data filter, reward signal. Keep checks pure and deterministic — `run_checks` must return the same `Verdict` for the same inputs, and `SequenceMatcher` runs with `autojunk=False` for exactly that reason.
- `loop.py` — the eight-stage in-cell loop: `align, review, select, gate, act, verify, record, stop`. **Offline-first is the core invariant**: with no backend the loop still aligns, routes, gates, records, and stops with `act` and `verify` marked `skipped`. `act`/`verify` repeat until the gate passes or `max_attempts` is spent; status is `done` only on a passing gate, else `blocked`. **Retry determinism**: each retry carries the prior failure reason into the next prompt (`build_prompt`), so attempt *N* is a pure function of goal, source, and prior verdicts — retrying an unchanged prompt at temperature 0 would loop on the same failure forever. Takes `Router` and `Backend` as plain callables (`Callable[[str], str]`) and streams attempts to an injectable `on_attempt` hook — keep both seams; don't couple the loop to concrete backends or to where traces are written.
- `trace.py` — per-attempt JSONL capture plus `export_sft`. Records carry **no wall-clock time** so identical runs write byte-identical logs (reproducibility is checkable with `diff`) — don't add timestamps. `export_sft` mode `star` pairs the clean first prompt with the passing output (rejection sampling — the adapter should learn to succeed first time); `repair` pairs the retry prompt with the passing output.
- `router.py` — deterministic keyword routing (order-stable tuple of rules → specialist name, `generalist` fallback). Determinism here is a contract, not an implementation detail: same goal must always select the same route.
- `model.py` — the model plane behind one `complete(prompt, *, temperature=None)` interface. `local` is canonical (`LocalBackend`: no key, no egress, optional `adapter`; `system` is a deprecated alias for it); `offline` (echo transport), `frontier` (Anthropic), and `byok` are the others. **API keys come from the environment by convention, never from the manifest**: `ANTHROPIC_API_KEY`, `SKILLCELL_BYOK_KEY`. Local endpoint resolves manifest → `SKILLCELL_LOCAL_ENDPOINT` → `SKILLCELL_SYSTEM_ENDPOINT` → `DEFAULT_LOCAL_ENDPOINT`. The local plane must never read a key on any path. The `temperature` override exists because **temperature 0 is a serving invariant, not a training one** — rejection sampling needs to sample hot.
- `evalgate.py` — the `command` primitive (`run_gate`) that `verify.py` composes; runs a cell-declared script with a fixed argv and no shell.
- `container.py` — phase-1 container runtime: pure `docker build`/`docker run` argv builders + injectable `Runner` (tests never need a daemon; subprocess attaches at the CLI edge only). Hermetic mapping is conservative: `network: deny` AND `allowlist` → `--network=none`, only explicit `open` gets the bridge. Cell dir mounts at `/cell`. Keep argv construction pure and deterministic. `skillcell run` dispatches container-runtime cells here behind the same authorization gate as the local act stage: no `--act --authorized` → dry run printing the planned argv, docker untouched; authorized → execute (exit 3 docker missing, exit 1 container non-zero).
- `cli.py` — `doctor`, `run`, `validate`, `traces`, and `tui` subcommands. Exit 2 on manifest errors, 3 on backend/docker errors, **1 when a cell ran but never satisfied its gate** (so CI sees a failing contract); offline runs exit 0 because nothing was claimed. `run` takes `--source` (the file the gate checks), `--attempts` (overrides `loop.maxAttempts`), and `--traces`. `traces` summarizes a log or exports it with `--export`/`--mode`; `FIRST_ATTEMPT_PASS_RATE` is the metric that says whether an adapter is earning its keep.
- `tui.py` — Textual app (optional `tui` extra): manifest list + detail pane, validates on select, `r` runs a Cell's offline loop. Takes `manifest_dir` in the constructor so tests drive it headless via `app.run_test()`; keep it constructor-injected, no cwd reads.

## Constraints

- **Determinism is the product — but it is not correctness.** Decode params pin temperature 0 / fixed seed; routing is order-stable; checks and exports are order-stable; runs must be reproducible. Any change that introduces nondeterminism into the loop, router, verifier, or manifest handling breaks the core promise. Two things must stay separate in code and in docs: **determinism comes from single-tenant local serving**, and **the adapter supplies capability, not consistency**. Same input → same output includes the same *wrong* output — correctness comes from the gate. Keep new claims as qualified as the ones in the README.
- **The gate is the crown jewel.** It is the runtime guarantee, the training-data filter, and the reward signal. A cell must never report `done` on a failing gate. New checks must be offline, model-free, and deterministic.
- **Offline-first.** The default path must work with zero network and zero keys. New features need an offline behavior (done/skipped/blocked), not a hard dependency on a backend. No frontier model belongs in the default path — including in the training-data path.
- **Security posture is deliberate**: cells are hermetic (tool allowlist, `network: deny` default), act mode is gated behind explicit authorization (`--act --authorized`). The example cell is a firmware-triage security workflow — the authorization gate exists because of it. Don't weaken these gates for convenience.
- **Licensing boundary**: everything outside `ee/` is Apache-2.0. `ee/` is reserved for the commercial edition (currently just a license file). Anything required to run one machine's cells stays in the Apache tree — never move core functionality under `ee/`.
- Built with TDD; `mypy` runs strict. Keep new code typed and tested to the existing standard.
