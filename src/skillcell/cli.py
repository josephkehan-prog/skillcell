"""skillcell CLI: doctor + run (offline-first local cell runner)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .container import ContainerError, run_command, run_in_container
from .loop import Attempt, run_loop
from .manifest import Cell, ManifestError, load_cell, load_manifest
from .model import BackendError, resolve_backend
from .router import default_router
from .trace import EXPORT_MODES, RunIdentity, TraceWriter, export_sft, read_traces


def _fail(exc: Exception) -> int:
    print(f"error: {exc}", file=sys.stderr)
    return 2


def _cmd_doctor(_: argparse.Namespace) -> int:
    print("STATUS=ready")
    print("RUNTIME=local")
    print("PLANES=local,offline,frontier,byok")
    print("OFFLINE_LOOP=ready")
    return 0


def _cmd_validate(ns: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(ns.manifest)
    except (ManifestError, FileNotFoundError, OSError) as exc:
        return _fail(exc)
    kind = "Cell" if isinstance(manifest, Cell) else "Chain"
    print(f"VALID kind={kind} name={manifest.name}")
    return 0


def _cmd_tui(ns: argparse.Namespace) -> int:  # pragma: no cover - interactive
    try:
        from .tui import run_tui
    except ModuleNotFoundError:
        print(
            "error: the TUI requires the 'tui' extra — install with: pip install skillcell[tui]",
            file=sys.stderr,
        )
        return 2
    run_tui(ns.dir)
    return 0


def _run_container(cell: Cell, ns: argparse.Namespace) -> int:
    cell_dir = Path(ns.manifest).resolve().parent

    # Same authorization gate as the local loop's act stage: running the
    # container IS the act. Without --act this is a dry run; with --act but
    # no --authorized it is blocked. Docker is never touched on either path.
    if not (ns.act and ns.authorized):
        status = "blocked" if ns.act else "skipped"
        try:
            planned = run_command(cell, cell_dir=cell_dir, goal=ns.goal)
        except ContainerError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        if ns.json:
            print(
                json.dumps(
                    {"cell": cell.name, "runtime": "container", "act": status, "planned": planned}
                )
            )
            return 0
        print(f"cell={cell.name} runtime=container act={status}")
        print(f"planned: {' '.join(planned)}")
        if status == "blocked":
            print("authorization required: pass --act --authorized to execute")
        return 0

    try:
        code, output = run_in_container(cell, cell_dir=cell_dir, goal=ns.goal)
    except ContainerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if ns.json:
        print(
            json.dumps(
                {"cell": cell.name, "runtime": "container", "exit_code": code, "output": output}
            )
        )
    else:
        print(f"cell={cell.name} runtime=container exit_code={code}")
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
    return 0 if code == 0 else 1


def _identity(cell: Cell) -> RunIdentity:
    model = cell.model
    return RunIdentity(
        cell=cell.name,
        plane=model.plane if model else "offline",
        base=model.base if model else "",
        adapter=model.adapter if model else None,
        temperature=model.decode.temperature if model else 0.0,
        seed=model.decode.seed if model else 0,
    )


def _cmd_run(ns: argparse.Namespace) -> int:
    try:
        cell = load_cell(ns.manifest)
    except (ManifestError, FileNotFoundError, OSError) as exc:
        return _fail(exc)

    if cell.runtime == "container":
        return _run_container(cell, ns)

    source = ""
    if ns.source:
        try:
            source = Path(ns.source).read_text(encoding="utf-8")
        except OSError as exc:
            return _fail(exc)

    try:
        backend = resolve_backend(cell.model, env=os.environ)
    except BackendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    callable_backend = (lambda prompt: backend.complete(prompt)) if backend else None

    # Traces are written lazily: an offline run makes no attempts, so it leaves
    # no file behind.
    on_attempt: Callable[[Attempt], None] | None = None
    if ns.traces:
        writer = TraceWriter(
            path=ns.traces, identity=_identity(cell), goal=ns.goal, source=source
        )
        on_attempt = writer.record

    result = run_loop(
        goal=ns.goal,
        router=default_router,
        backend=callable_backend,
        act_mode=ns.act,
        authorized=ns.authorized,
        source=source,
        checks=cell.eval.checks,
        max_attempts=ns.attempts or cell.loop.max_attempts,
        cwd=str(Path(ns.manifest).resolve().parent),
        on_attempt=on_attempt,
    )

    if ns.json:
        print(
            json.dumps(
                {
                    "cell": cell.name,
                    "goal": result.goal,
                    "route": result.route,
                    "executed": result.executed,
                    "output": result.output,
                    "status": result.status,
                    "verified": result.verified,
                    "attempts": len(result.attempts),
                    "stages": [
                        {"name": s.name, "status": s.status, "detail": s.detail}
                        for s in result.stages
                    ],
                    "stopped_at": result.stopped_at,
                }
            )
        )
    else:
        print(
            f"cell={cell.name} route={result.route} "
            f"status={result.status} attempts={len(result.attempts)}"
        )
        for s in result.stages:
            print(f"  {s.name:8} {s.status:8} {s.detail}")

    # Non-zero when the cell ran but never satisfied its contract, so a failing
    # gate is visible to CI. Offline (skipped) stays 0 — nothing was claimed.
    return 1 if result.status == "blocked" and result.executed else 0


def _cmd_traces(ns: argparse.Namespace) -> int:
    records = read_traces(ns.log)

    if ns.export:
        pairs = export_sft(records, mode=ns.mode)
        out = Path(ns.export)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "".join(json.dumps(p, sort_keys=True) + "\n" for p in pairs), encoding="utf-8"
        )
        print(f"EXPORTED={len(pairs)} MODE={ns.mode} PATH={out}")
        return 0

    runs: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        runs.setdefault(str(record.get("run", "")), []).append(record)

    passed = sum(1 for attempts in runs.values() if any(a.get("passed") for a in attempts))
    first_try = sum(
        1
        for attempts in runs.values()
        if any(a.get("passed") and int(a.get("attempt", 0) or 0) == 1 for a in attempts)
    )
    total = len(runs)
    summary: dict[str, Any] = {
        "runs": total,
        "attempts": len(records),
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        # The number that says whether the adapter is earning its keep: a cell
        # that only passes after retries has not learned the skill yet.
        "first_attempt_pass_rate": round(first_try / total, 4) if total else 0.0,
    }

    if ns.json:
        print(json.dumps(summary))
    else:
        for key, value in summary.items():
            print(f"{key.upper()}={value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skillcell", description="Send agents to the work.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check runtime readiness")
    d.set_defaults(func=_cmd_doctor)

    r = sub.add_parser("run", help="run a cell's loop locally")
    r.add_argument("manifest", help="path to a Cell manifest")
    r.add_argument("--goal", required=True, help="the task goal")
    r.add_argument("--source", help="file the cell transforms; checked by the gate")
    r.add_argument("--attempts", type=int, help="override the manifest's loop.maxAttempts")
    r.add_argument("--traces", help="append per-attempt trace records to this JSONL log")
    r.add_argument("--act", action="store_true", help="request act mode (needs authorization)")
    r.add_argument("--authorized", action="store_true", help="authorization gate satisfied")
    r.add_argument("--json", action="store_true", help="machine-readable output")
    r.set_defaults(func=_cmd_run)

    tr = sub.add_parser("traces", help="summarize a trace log or export it as training data")
    tr.add_argument("log", help="path to a JSONL trace log")
    tr.add_argument("--export", help="write gate-passing runs as SFT pairs to this path")
    tr.add_argument(
        "--mode",
        choices=EXPORT_MODES,
        default="star",
        help="star: clean prompt -> passing output (default); repair: teach self-correction",
    )
    tr.add_argument("--json", action="store_true", help="machine-readable output")
    tr.set_defaults(func=_cmd_traces)

    v = sub.add_parser("validate", help="validate a manifest (Cell or Chain)")
    v.add_argument("manifest", help="path to a manifest")
    v.set_defaults(func=_cmd_validate)

    t = sub.add_parser("tui", help="browse and run manifests in a terminal UI")
    t.add_argument("dir", nargs="?", default=".", help="manifest directory (default: cwd)")
    t.set_defaults(func=_cmd_tui)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
