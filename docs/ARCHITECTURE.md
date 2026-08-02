# skillcell architecture

Status: design (v0). This document is the plan of record for reversing the
skills-into-agent workflow into an agent-into-workspace system.

## 1. Problem

The current workflow loads skills into one generalist agent session:

- **Context bloat.** Every skill, rule file, and tool schema competes for the
  same context window.
- **Personality clash.** Skills written for different models/styles produce
  inconsistent behavior when stacked in one session.
- **Nondeterminism.** Prompt-level skill behavior drifts between runs and
  between harness versions.
- **No end-to-end ownership.** A skill invocation is a detour inside a larger
  session, not a bounded unit of work with its own contract and eval gate.

## 2. The inversion

Make the skill the *place*, not the payload. Each skill/plugin becomes a
**cell**: a mono-scoped workspace containing everything needed to complete
that one piece of work end to end. Agents are dispatched into cells; an
orchestrator chains cells for multi-step tasks.

## 3. Cell anatomy

A cell is a repo (or repo subtree) plus a manifest. It declares:

| Component | What it is |
| --- | --- |
| `scope` | The single skill/plugin the cell owns, end to end |
| `contract` | Typed inputs, typed output artifacts, and an eval gate that must pass before the cell reports done |
| `tools` | The exact tool allowlist available inside the cell — nothing else is reachable |
| `lsp` | Language servers provisioned in the cell (e.g. rust-analyzer, pyright); symbol-accurate editing is established *inside* the cell, not bolted onto a session |
| `loop` | The agent loop the cell runs: plan → act → verify → record, with iteration cap and stop conditions |
| `model` | Pinned base model + optional LoRA adapter + decode params (see §5) |
| `runtime` | `local` or `container` (see §4) |

Cells are **hermetic by default**: filesystem scope limited to the cell
worktree, network policy declared in the manifest, credentials injected per
run (never stored in the cell).

## 4. Runtimes: local and containerized

Same manifest, two runtimes:

- **local** — the cell materializes as a git worktree; a provisioner installs
  the declared tools and LSP servers project-locally and starts the loop
  runner in that directory. Cheap, fast, ideal on a workstation.
- **container** — the cell builds to an OCI image from a
  devcontainer-compatible spec (`devcontainer.json` is the provisioning
  standard; we reuse it rather than inventing one). The loop runner is the
  container entrypoint. This is the unit the orchestrator schedules — on the
  local Docker/Apple-container runtime first, on real Kubernetes later.

## 5. Adapter plane (deterministic per-cell models)

Goal: the backend model is *transformed into the skill* rather than prompted
with it, eliminating cross-skill personality clash and run-to-run drift.

- **Per-cell adapter.** Each cell may reference a LoRA adapter trained on
  that cell's skill traces (successful loop transcripts, curated
  demonstrations). Base model stays shared and frozen; adapters are small,
  versioned artifacts in an adapter registry.
- **Adoption.** When a subagent enters a cell, it adopts the cell's identity:
  adapter loaded, cell system prompt applied, toolset swapped. On exit,
  nothing leaks back. Adapters are swapped between cells, never stacked
  within one — sidestepping the multi-adapter interference production
  reports describe, where composed adapters fight over the same weight
  regions until output collapses toward base-model quality.
- **Determinism.** Manifest pins base-model hash, adapter hash, temperature 0
  (or fixed seed where sampling is required), and the prompt template
  version. Same inputs → same route → same artifacts, or the eval gate fails
  the run. Temperature 0 and a fixed seed pin sampling, not the reduction
  kernel: batched serving is batch-size-dependent nondeterministic, so local
  MLX single-tenant decode (batch size 1) is the bit-reproducible path today.
  vLLM multi-LoRA at scale needs batch-invariant kernels (current published
  overhead: ~34%) to match it; until a cell opts into those kernels, the eval
  gate treats its runs as statistically, not bitwise, reproducible.
- **Serving.**
  - Workstation (Apple Silicon): **MLX-LM** — native LoRA training and
    adapter loading, runs locally.
  - Scale-out (GPU): **vLLM multi-LoRA** — one base model in memory, many
    adapters hot-swapped per request; the orchestrator passes the adapter id
    per dispatch.
  - Frontier fallback: cells may declare `model: hosted` (e.g. Claude) when
    no adapter exists yet; the cell still gets determinism from contract +
    eval gate, just not from weights.
- **Training loop.** Cells accumulate traces → periodic distillation job
  fine-tunes/refreshes the adapter → eval gate on the cell's own test suite
  decides promotion. An adapter is promoted like a release, never silently.

## 6. Orchestrator (Kubernetes-style)

Declarative manifests, reconcile loops, level-triggered state — Kubernetes
semantics without requiring Kubernetes on day one.

Resource kinds (CRD-shaped, `skillcell.dev/v1alpha1`):

- **Cell** — the workspace definition (§3).
- **Chain** — a DAG of cells with typed artifact edges; a chain is how
  multiple mono-scoped repos are composed into a larger capability.
- **Run** — one execution of a cell or chain: inputs, dispatch records,
  artifacts, eval results, full iteration transcript.

Control loop:

1. User (or an agent) applies a `Run` referencing a `Chain`.
2. Scheduler topologically orders the DAG, provisions each cell (local
   worktree or container), and dispatches a subagent into it.
3. The subagent adopts the cell (§5), runs the cell's loop, and must pass the
   cell's eval gate to hand its artifacts to the next edge.
4. Failures follow declared policy: retry with backoff, fall back one model
   tier, or park the run for operator decision. Every dispatch, route, and
   artifact hash is recorded — runs are auditable and resumable.
5. In `kube` mode the same manifests become real CRDs and the reconciler runs
   as a controller; cells schedule as pods/jobs. `local` mode and `kube` mode
   share the spec so nothing is rewritten to graduate.

LSP, agent tooling, and the loop runner are **established inside the cell**
by the provisioner in local mode, or baked into the cell image and
orchestrated at the cluster layer in kube mode. Either way the session-level
harness no longer carries them.

## 7. Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Manifests | YAML, CRD-shaped (`apiVersion`/`kind`/`spec`) | Direct path to real k8s CRDs later; toolable now |
| Orchestrator / control plane | **Go** | Reconcile-loop idiom is native (controller-runtime/kubebuilder patterns); single static binary; becomes a real k8s controller in phase 4 without a rewrite |
| Cell provisioner (container) | **devcontainer spec + OCI** (Docker or Apple `container`) | Existing standard for "workspace with tools + LSP declared"; zero invented formats |
| Loop runner (in-cell agent) | **Python + Claude Agent SDK** (headless) | Best current SDK for tool-using loops; cells that need TS can use the TS SDK — the runner is per-cell anyway |
| LSP in cells | Stock language servers (rust-analyzer, pyright, gopls, tsserver) declared in the manifest | Symbol-accurate editing inside the cell |
| Adapter training | **MLX-LM LoRA** (local, Apple Silicon); TRL/PEFT for GPU jobs | Both already evaluated in quarantine on this machine |
| Adapter serving | **MLX-LM** locally; **vLLM multi-LoRA** at scale | One frozen base, hot-swapped adapters per dispatch |
| Artifact/adapter registry | OCI registry (ORAS) | Adapters, cell images, and run artifacts all version through one content-addressed store |
| Durable chain state | SQLite (phase 0–2) → **Temporal** if chains become long-lived/distributed | Don't buy a workflow engine before chains outgrow a reconcile loop |

## 8. Prior art (existing-solutions preflight)

Checked before designing custom pieces; skillcell is a thin control plane
gluing these, not a rebuild of any of them:

- **kagent** (CNCF) — agents as k8s CRDs. Closest prior art for phase 4;
  doesn't cover mono-scoped workspace cells, adapter planes, or local mode.
- **devcontainers** — adopted outright for cell provisioning.
- **vLLM multi-LoRA / S-LoRA** — adopted for adapter serving at scale.
- **MLX-LM** — adopted for local adapter training/serving.
- **LatentSkill** (arXiv 2606.06087) — skill text compiled to LoRA via
  hypernetwork; validates the adapter plane, no workspace/contract/orchestration.
- **Skill-to-LoRA** (arXiv 2606.16769) — SKILL.md distilled into a LoRA,
  document dropped at runtime; same validation, same gap.
- **Parametric Skills** (arXiv 2606.30015) — same skills-as-weights direction.
- **AgentSkillOS** (NPU, 2026) — orchestrates 200K+ skills into workflows;
  skills stay prompt-level, no weight pinning or hermetic cells.
- **Temporal / Dagger** — candidate execution substrates for chains; deferred
  until chains outgrow the built-in reconciler.
- **LangGraph / Claude Agent SDK** — in-cell loop runtime; adopted (SDK)
  rather than rebuilt.
- **reverse-skill langgraph-agent** (local) — its seven-stage loop, scope
  gates, and offline route-record design are the direct ancestor of the cell
  loop contract.

## 9. Roadmap

| Phase | Deliverable | Exit criterion |
| --- | --- | --- |
| 0 | Spec + local runner: `Cell` manifest, worktree provisioner, loop runner, eval gate | One existing skill (from reverse-skill) completes end to end inside a local cell, deterministically routed and recorded |
| 1 | Containerized cells: devcontainer build, OCI image per cell, same manifest | Same cell passes identically in local and container runtimes |
| 2 | Adapter plane: trace capture, MLX-LM LoRA training job, adapter registry, adoption on dispatch | A cell with an adapter beats the prompted baseline on its own eval gate |
| 3 | Orchestrator + chains: reconciler in Go, `Chain`/`Run` kinds, DAG scheduling, retry/fallback policy | A three-cell chain completes with one induced failure recovered by policy |
| 4 | Kube mode: manifests as real CRDs, controller deployment, cells as jobs/pods, vLLM multi-LoRA serving | The phase-3 chain runs unmodified on a k8s cluster |

## 10. Licensing boundary

Open core. Apache-2.0 for the spec, provisioners, loop runner, reconciler,
and local/container runtimes — everything a single operator needs. The `ee/`
tree (commercial license) is reserved for multi-tenant fleet orchestration,
hosted adapter registry, and policy/audit packs. The boundary rule: **anything
required to run one machine's cells stays Apache-2.0.**
