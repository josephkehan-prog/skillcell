<p align="center">
  <img src="assets/logo.svg" width="88" height="88" alt="Skill Cell logo">
</p>

<h1 align="center">Skill Cell</h1>

<p align="center"><strong>The cell is the skill</strong> - weight-pinned, reusable, agents dispatched into it.</p>

<p align="center">
  <code>pip install skillcell</code> &nbsp;·&nbsp; <a href="https://josephkehan-prog.github.io/skillcell/">Landing page</a> &nbsp;·&nbsp; Apache-2.0 open core
</p>

<p align="center"><img src="https://github.com/josephkehan-prog/skillcell/actions/workflows/ci.yml/badge.svg" alt="ci"></p>

---

**The bet, as one causal chain:**

> Bit-reproducibility is only available on **single-tenant local decode**
> (batch size 1, pinned seed). Local decode means **small models**. Small
> models are too weak to do real work — *unless* they are shaped for one
> narrow task. So a **LoRA adapter is what makes small-model determinism
> affordable**, and a **hard eval gate is what makes it correct**.

Two claims live in there, and they are independent — conflating them is the
most common way to misread this project:

- **Determinism is a property of how you serve**, not of the adapter. You get
  bit-reproducible runs from a stock 7B at temperature 0, batch size 1, with no
  adapter at all.
- **The adapter is a source of capability**, not of consistency. It is what
  lifts a small model to useful on one narrow skill, which is what makes the
  reproducible serving path worth standing on in the first place.

And determinism alone buys nothing a user wants. *Same input → same output*
includes **the same wrong output, every time**. Correctness comes from the
gate: the cell retries against its own contract and reports `blocked` rather
than `done` if it never passes. That is how a 7B reaches the guarantee a much
larger model would — more attempts, not more parameters.

## Core ideas

1. **Cell** — a mono-scoped repo/workspace where one skill can be completed end
   to end. A cell declares its contract (inputs, outputs, eval gate), its
   toolset, its agent loop, and its model. Nothing outside the cell's scope is
   reachable from inside it.
2. **The gate is the crown jewel.** One artifact does three jobs: it is the
   *runtime guarantee* (retry until it passes), the *training filter* (only
   gate-passing attempts become adapter data), and the *reward signal* an RL
   pass would optimize. Checks are offline and model-free — command exit codes,
   preserved figures/URLs/acronyms, negation-count equality, bounded rewrite
   ratio.
3. **Local plane first.** No key, no egress, single-tenant. The frontier and
   BYOK planes exist as fallbacks for cells with no promoted adapter yet — the
   default path never needs them, including for training data.
4. **Adapter plane** — a cell may pin a base model plus a **LoRA adapter**
   trained on its own gate-passing traces. Temperature 0 and a fixed seed pin
   sampling, not the reduction kernel: single-tenant local decode is the
   bit-reproducible path today, while shared batched inference additionally
   needs batch-invariant kernels. One adapter per cell, swapped rather than
   stacked, sidesteps multi-adapter interference.
5. **Local or containerized** — a cell runs as a local worktree or an OCI
   container built from a devcontainer-compatible spec. Same manifest, two
   runtimes.

### Temperature 0 is a serving invariant, not a training one

Rejection sampling needs *diverse* attempts to have anything to filter. The
data-generation path samples hot on purpose (`complete(prompt, temperature=…)`);
only the served path is pinned. Both are declared in the same manifest.

## The inversion, in one table

| Today (skills-into-agent)          | skillcell (agent-into-cell)                  |
| ---------------------------------- | -------------------------------------------- |
| Skill loads into a shared session  | Skill *is* a workspace; agent travels to it  |
| One context holds everything       | Each cell holds only its own scope           |
| Prompt-level behavior, drifts      | Pinned single-tenant decode, bit-reproducible |
| Small models too weak to use       | Adapter shapes one narrow skill per cell     |
| "Looks done" is the finish line    | Gate passes, or the cell reports `blocked`   |
| Personality/style clash across skills | One adapter per cell, no cross-talk       |
| Runs are unlogged                  | Every attempt traced; passes become training data |

## Repository layout

```
skillcell/
├── README.md            you are here
├── LICENSE              Apache-2.0 — everything outside ee/
├── docs/
│   └── ARCHITECTURE.md  full design: cells, adapter plane, orchestrator, roadmap
├── examples/
│   ├── wordsmith.yaml              the reference cell — trainable, gated
│   ├── cell.yaml                   firmware triage — aspirational, not a starting point
│   ├── chain.yaml                  a DAG of cells run by the orchestrator
│   └── refactor-audit-chain.yaml   implement-then-audit two-cell chain
├── .github/
│   └── workflows/ci.yml   lint, type-check, tests, security scan on every push
├── src/skillcell/       phase-0 runner: manifest, model plane, loop, router, eval gate, CLI
├── docs/index.html      landing page
└── ee/                  commercial edition — separate closed license (see ee/LICENSE.md)
```

## Quickstart

```bash
uv sync
uv run skillcell doctor
uv run skillcell validate examples/wordsmith.yaml

# run the reference cell against a draft — gate and retries included
uv run skillcell run examples/wordsmith.yaml \
  --goal "tighten this" --source NOTES.md --traces .skillcell/traces.jsonl
```

Exit code is `1` when the cell ran but never satisfied its contract, so a
failing gate is visible to CI. Offline runs exit `0` — nothing was claimed.

### The loop, and where reliability comes from

Eight stages: `align, review, select, gate, act, verify, record, stop`. The
`act`/`verify` pair repeats until the gate passes or `loop.maxAttempts` is
spent. Each retry carries the previous failure reason into the next prompt —
which is also *why retrying stays deterministic*: the prompt changes, so the
output changes, and attempt *N* remains a pure function of the goal, the
source, and every prior verdict. Retrying an unchanged prompt at temperature 0
would just reproduce the same failure forever.

Offline-first is unchanged: with no `model` in the manifest the loop aligns,
routes, gates, records, and stops, with `act` and `verify` marked `skipped`.

### The gate

Declared in the manifest, enforced at runtime, model-free and offline:

```yaml
contract:
  eval:
    checks:
      - command: ./eval/lint.sh     # any script; exit 0 to pass
      - forbid: '\bTODO\b'
      - require: '^## Summary'
      - preserves: numbers          # every figure survives the rewrite
      - preserves: negations        # a flipped negation inverts the meaning
      - maxEditRatio: 0.55          # reject a from-scratch rewrite
loop:
  maxAttempts: 4
```

A linter tells you the output *conforms*. It cannot tell you the output still
*means* what the input meant — so the preservation checks and the bounded
rewrite ratio exist to catch the drift a green gate would otherwise wave
through, reproducibly, forever.

### Traces → adapter

Every attempt is logged with its verdict and the full run identity (cell,
plane, base, adapter, decode params). Records carry **no wall-clock time**, so
two identical runs write byte-identical logs and `diff` is the reproducibility
proof.

```bash
uv run skillcell traces .skillcell/traces.jsonl            # summary
uv run skillcell traces .skillcell/traces.jsonl --export sft.jsonl
```

`FIRST_ATTEMPT_PASS_RATE` is the number that says whether an adapter is
earning its keep: a cell that only passes after retries has not learned the
skill yet.

The export is rejection sampling. `--mode star` (default) pairs the *clean*
first prompt with the output that eventually passed — the adapter should learn
to succeed first time, not to depend on gate feedback that won't be there.
`--mode repair` pairs the retry prompt with the passing output, teaching
self-correction. No frontier teacher is involved on either path.

### Model planes

Keys come from the environment, never the manifest:

| Plane | `model.plane` | Key (env) | Use |
| --- | --- | --- | --- |
| **Local** | `local` | none | **the default** — MLX-LM / Ollama / llama.cpp on this machine, optional `adapter`. `system` is a deprecated alias. |
| Frontier | `frontier` | `ANTHROPIC_API_KEY` | fallback for cells with no promoted adapter |
| BYOK | `byok` | `SKILLCELL_BYOK_KEY` | any OpenAI-compatible `provider` + `base_url` |

Endpoint resolution for the local plane: manifest `endpoint` →
`SKILLCELL_LOCAL_ENDPOINT` → `http://127.0.0.1:11434/v1`. The local plane never
reads an API key on any path, so a key in the environment cannot change its
behavior.

Act mode (`--act`) additionally requires the authorization gate
(`--authorized`) before the specialist turn runs.

## Which cells are trainable

A cell can only carry an adapter if all three hold. Pick the first cell against
this list, not against how interesting the domain sounds:

1. **Procedural** — shapeable by an adapter. A LoRA makes a small model
   reliably *assume a procedure*; it cannot make it smarter. If the skill needs
   judgment the base model lacks, no adapter rescues it.
2. **Mechanically verifiable** — the gate decides pass/fail with no model and
   no human. Without this, rejection sampling has no filter and the loop never
   ignites.
3. **Non-zero base pass rate** — the stock model succeeds *sometimes* under
   sampling. If pass@1 is 0%, pass@50 is usually 0% too, and there is nothing
   to train on.

`examples/wordsmith.yaml` satisfies all three. `examples/cell.yaml` (firmware
triage) satisfies none — it is kept as an aspiration and clearly marked.

## Status

Working today: the local cell runner — manifest (including a parsed, enforced
`contract.eval`), local/frontier/BYOK model planes, the eight-stage loop with
gate-driven retry, the composable verifier, trace capture, the SFT export, the
container argv builders, and the CLI. TDD'd, `mypy --strict`, security-scanned.

Not built yet, and not to be assumed: adapter *training* and the adapter
registry, the Go orchestrator, and kube mode. See `docs/ARCHITECTURE.md` for
the roadmap — that document is the source of truth for the design.

The load-bearing claim — *an adapted 7B beats the prompted base on this cell's
own gate, while staying bit-reproducible* — is *untested*. Everything above is
the harness built to test it. Treat it as a hypothesis with a measurement rig
around it, not a proven result.

## Licensing

skillcell is **open core**:

- Everything outside `ee/` is licensed under **Apache-2.0** (see `LICENSE`).
- Everything under `ee/` is source-available under a **commercial license**
  (see `ee/LICENSE.md`) and is not open source. Planned `ee/` scope: fleet
  orchestration at scale, adapter registry hosting, and policy/audit packs.

Contributions to the open core are welcome under Apache-2.0.
