---
name: run-skillcell
description: Run, smoke-test, screenshot, or drive skillcell — the CLI (doctor/run/validate) and the Textual TUI. Use when asked to run skillcell, launch the TUI, take a screenshot, or verify the app works end to end.
---

# Run skillcell

Phase-0/1 local cell runner: a Python CLI (`skillcell doctor|run|validate|tui`)
plus a Textual TUI. Everything is driven through
`.claude/skills/run-skillcell/driver.py` — no daemon, no display needed.
All paths below are relative to the repo root and were verified on macOS.

## Prerequisites

Python 3.11+ and `uv`. Nothing else — deps (incl. textual for the TUI) come in:

```bash
uv sync
```

## Run (agent path) — the driver

Smoke every CLI surface (doctor, validate on all three examples, offline
run with route/stage assertions, error exit codes). Exits non-zero on the
first failure:

```bash
uv run python .claude/skills/run-skillcell/driver.py smoke
```

Drive the TUI headless and capture a real screenshot (selects `cell.yaml`,
presses `r` to run the offline loop, saves what's on screen):

```bash
uv run python .claude/skills/run-skillcell/driver.py tui-screenshot /tmp/skillcell-tui.svg
```

Output is **SVG** (Textual's native screenshot format). Verify it captured
the interaction, not a blank screen:

```bash
grep -c "firmware-pentest" /tmp/skillcell-tui.svg   # ≥1 means the loop ran
```

## Live TUI under tmux (interactive poking)

```bash
tmux new-session -d -s skillcell-tui -x 100 -y 32 'uv run skillcell tui examples'
sleep 4                                   # uv + app startup; keys sent earlier are lost
tmux send-keys -t skillcell-tui Enter     # validate selected manifest
tmux send-keys -t skillcell-tui r         # run offline loop on the selected Cell
tmux capture-pane -t skillcell-tui -p     # read the screen
tmux kill-session -t skillcell-tui
```

Keys: arrows move the list, `Enter` validates, `r` runs (Cells only), `q` quits.

## Run (human path)

```bash
uv run skillcell tui examples             # opens the TUI in your terminal
uv run skillcell run examples/cell.yaml --goal "triage firmware image" --json
```

Offline by default — no keys, no network. `--json` gives the machine-readable
loop result (`route`, `executed`, seven `stages`).

## Direct invocation (most PRs need only this)

The loop, router, and manifest layer are plain functions:

```bash
uv run python -c "
from skillcell.manifest import load_manifest
from skillcell.loop import run_loop
from skillcell.router import default_router
cell = load_manifest('examples/cell.yaml')
r = run_loop(goal=cell.scope, router=default_router, backend=None, act_mode=False, authorized=False)
print(r.route, [s.status for s in r.stages])
"
```

## Test

```bash
uv run pytest --cov     # 67 tests, 80% coverage floor enforced
```

## Gotchas

- **Textual 8.x renamed `Static.renderable` → `Static.content`.** Any code
  reading the detail pane must use `.content`; `.renderable` raises
  AttributeError.
- **tmux: wait ~4s after `new-session` before `send-keys`.** `uv run` +
  Textual startup swallows earlier keys silently.
- **Screenshots are SVG, not PNG.** `save_screenshot` / the driver emit SVG;
  grep them for expected strings instead of image-diffing.
- **`r` on a Chain shows "only Cell manifests are runnable"** — by design,
  not a bug.
- **Exit codes:** `validate` and manifest errors → 2, backend/model errors
  in `run` → 3, success → 0. The driver asserts these.
- **`runtime: container` cells dispatch to docker, behind the act gate.**
  Without `--act --authorized`, `skillcell run` is a dry run: it prints the
  planned `docker run` argv and executes nothing (exit 0; `--act` alone
  shows act=blocked). With both flags it builds (if needed) and runs the
  image: exit 3 when docker is missing, exit 1 when the container exits
  non-zero (its code is shown). Local cells are untouched by this path.

## Troubleshooting

- `ModuleNotFoundError: textual` → you installed without dev deps; run
  `uv sync` (dev group carries textual + pytest-asyncio).
- TUI subcommand prints `requires the 'tui' extra` → same fix for
  non-dev installs: `pip install 'skillcell[tui]'`.
- Driver `FAIL validate ...` with exit 2 → the example manifest is broken;
  run `uv run skillcell validate <file>` directly to see the real error.
