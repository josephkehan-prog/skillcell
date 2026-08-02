# skillcell

**Send agents to the work — don't load the work into agents.**

skillcell inverts the current agent-skill workflow. Today, a user opens one
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
   skill traces. Decoding is deterministic: temperature 0, fixed seed,
   pinned weight and adapter hashes. No personality clash, reproducible runs.
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
| Prompt-level behavior, drifts      | Adapter + pinned decode, deterministic       |
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

## Status

Design phase. `docs/ARCHITECTURE.md` is the source of truth; the roadmap at
the bottom of that document tracks implementation phases.

## Licensing

skillcell is **open core**:

- Everything outside `ee/` is licensed under **Apache-2.0** (see `LICENSE`).
- Everything under `ee/` is source-available under a **commercial license**
  (see `ee/LICENSE.md`) and is not open source. Planned `ee/` scope: fleet
  orchestration at scale, adapter registry hosting, and policy/audit packs.

Contributions to the open core are welcome under Apache-2.0.
