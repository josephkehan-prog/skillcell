<p align="center">
  <img src="assets/logo.svg" width="88" height="88" alt="Skill Cell logo">
</p>

<h1 align="center">Skill Cell</h1>

<p align="center"><strong>The cell is the skill</strong> - weight-pinned, reusable, agents dispatched into it.</p>

<p align="center">
  <code>pip install skillcell</code> &nbsp;·&nbsp; <a href="https://josephkehan-prog.github.io/skillcell/">Landing page</a> &nbsp;·&nbsp; Apache-2.0 open core
</p>

---

Every serious agent platform now containerizes the *runtime* (OpenHands, Devin,
Codex Cloud, Claude Code cloud, Copilot all run a sandbox per task). skillcell's
bet is one layer they don't: make the **skill itself** the mono-scoped, reusable
unit — pinned to its own LoRA adapter for deterministic behavior — that agents
travel into. Sandboxing per task is settled; per-skill weight specialization
was just proven in research (Skill-to-LoRA, LatentSkill — June 2026), but
nobody ships it as a product unit. The papers proved the adapter; skillcell
ships the cell around it: contract, tools, LSP, eval gate, orchestration.

It inverts the current agent-skill workflow. Today, a user opens one
generalist LLM session and loads skills *into* it: context bloats, model
"personalities" clash, results drift run to run. skillcell turns each skill,
plugin, or repo into a **cell** — a self-contained, mono-scoped workspace with
its own code, tools, language servers, agent loop, and (optionally) its own
LoRA-adapted model. Agents are dispatched *into* cells to do the work, and an
orchestrator chains cells together Kubernetes-style for larger tasks.

## Core ideas

1. **Cell** — a mono-scoped repo/workspace where one skill or plugin can be
   completed end to end. A cell declares its contract (inputs, outputs,
   eval gate), its toolset, its LSP servers, and its agent loop. Nothing
   outside the cell's scope is reachable from inside it.
2. **Local or containerized** — a cell runs either as a local git worktree
   with provisioned tooling, or as an OCI container built from a
   devcontainer-compatible spec. Same manifest, two runtimes.
3. **Adapter plane** — instead of prompting a shared generalist model, a
   cell may pin a base model plus a **LoRA adapter** trained on that cell's
   skill traces. Decoding is pinned — temperature 0, fixed seed, pinned
   weight and adapter hashes — which gives bit-reproducible runs on
   single-tenant local serving (MLX-LM, batch size 1); on shared batched
   inference, reproducibility additionally requires batch-invariant kernels,
   which the manifest can declare.
4. **Orchestrator** — a Kubernetes-style control plane reconciles declarative
   manifests (`Cell`, `Chain`, `Run`). A `Chain` is a DAG of cells; the
   scheduler dispatches subagents into each cell, where they **adopt** the
   cell's adapter, system prompt, toolset, and loop for the duration of the
   task, then hand typed artifacts to the next cell.

## The inversion, in one table

| Today (skills-into-agent)          | skillcell (agent-into-cell)                  |
| ---------------------------------- | -------------------------------------------- |
| Skill loads into a shared session  | Skill *is* a workspace; agent travels to it  |
| One context holds everything       | Each cell holds only its own scope           |
| Prompt-level behavior, drifts      | Adapter + pinned decode, bit-reproducible locally |
| Personality/style clash across skills | One adapter per cell, no cross-talk       |
| Manual chaining by the user        | Declarative DAG, reconciled by orchestrator  |
| Tools/LSP configured per session   | Tools/LSP provisioned per cell, once         |

## Repository layout

```
skillcell/
├── README.md            you are here
├── LICENSE              Apache-2.0 — everything outside ee/
├── docs/
│   └── ARCHITECTURE.md  full design: cells, adapter plane, orchestrator, roadmap
├── examples/
│   ├── cell.yaml        a single mono-scoped cell manifest
│   └── chain.yaml       a DAG of cells run by the orchestrator
└── ee/                  commercial edition — separate closed license (see ee/LICENSE.md)
```

## Quickstart (phase 0 — local cell runner)

```bash
uv sync
uv run skillcell doctor
uv run skillcell run examples/cell.yaml --goal "triage firmware image" --json
```

Offline by default: with no `model` in the manifest, the loop aligns, routes,
gates, records, and stops — the `act` stage is marked `skipped`. Add a model
plane to enable the specialist turn.

### Model planes

Three backends behind one interface; keys come from the environment, never the
manifest:

| Plane | Manifest `model.plane` | Key (env) | Use |
| --- | --- | --- | --- |
| Frontier | `frontier` | `ANTHROPIC_API_KEY` | hosted frontier model (Claude) |
| System-native | `system` | none | local model on this machine (MLX / Ollama `endpoint`) |
| BYOK | `byok` | `SKILLCELL_BYOK_KEY` | any OpenAI-compatible `provider` + `base_url` |

```yaml
spec:
  model:
    plane: byok
    base: gpt-4o
    provider: openai
    base_url: https://api.openai.com/v1
    decode: { temperature: 0.0, seed: 1 }   # deterministic decode
```

Act mode (`--act`) additionally requires the authorization gate
(`--authorized`) to pass before the specialist turn runs.

## Status

Phase 0 shipped: local cell runner (manifest, model plane, seven-stage loop,
eval gate, CLI) — TDD'd, security-scanned, packaged to a wheel. See the
roadmap in `docs/ARCHITECTURE.md` for phases 1–4 (containers, adapter plane,
orchestrator, kube mode). That document is the source of truth for the design.

## Licensing

skillcell is **open core**:

- Everything outside `ee/` is licensed under **Apache-2.0** (see `LICENSE`).
- Everything under `ee/` is source-available under a **commercial license**
  (see `ee/LICENSE.md`) and is not open source. Planned `ee/` scope: fleet
  orchestration at scale, adapter registry hosting, and policy/audit packs.

Contributions to the open core are welcome under Apache-2.0.
