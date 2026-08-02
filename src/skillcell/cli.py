"""skillcell CLI: doctor + run (offline-first local cell runner)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .container import ContainerError, run_command, run_in_container
from .loop import run_loop
from .manifest import Cell, ManifestError, load_cell, load_manifest
from .model import BackendError, resolve_backend
from .router import default_router


def _fail(exc: Exception) -> int:
    print(f"error: {exc}", file=sys.stderr)
    return 2


def _cmd_doctor(_: argparse.Namespace) -> int:
    print("STATUS=ready")
    print("RUNTIME=local")
    print("PLANES=offline,frontier,system,byok")
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


def _cmd_run(ns: argparse.Namespace) -> int:
    try:
        cell = load_cell(ns.manifest)
    except (ManifestError, FileNotFoundError, OSError) as exc:
        return _fail(exc)

    if cell.runtime == "container":
        return _run_container(cell, ns)

    try:
        backend = resolve_backend(cell.model, env=os.environ)
    except BackendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    callable_backend = (lambda prompt: backend.complete(prompt)) if backend else None

    result = run_loop(
        goal=ns.goal,
        router=default_router,
        backend=callable_backend,
        act_mode=ns.act,
        authorized=ns.authorized,
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
                    "stages": [
                        {"name": s.name, "status": s.status, "detail": s.detail}
                        for s in result.stages
                    ],
                    "stopped_at": result.stopped_at,
                }
            )
        )
    else:
        print(f"cell={cell.name} route={result.route} executed={result.executed}")
        for s in result.stages:
            print(f"  {s.name:8} {s.status:8} {s.detail}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skillcell", description="Send agents to the work.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check runtime readiness")
    d.set_defaults(func=_cmd_doctor)

    r = sub.add_parser("run", help="run a cell's loop locally")
    r.add_argument("manifest", help="path to a Cell manifest")
    r.add_argument("--goal", required=True, help="the task goal")
    r.add_argument("--act", action="store_true", help="request act mode (needs authorization)")
    r.add_argument("--authorized", action="store_true", help="authorization gate satisfied")
    r.add_argument("--json", action="store_true", help="machine-readable output")
    r.set_defaults(func=_cmd_run)

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
