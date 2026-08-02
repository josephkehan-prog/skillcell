"""skillcell CLI: doctor + run (offline-first local cell runner)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from .loop import run_loop
from .manifest import ManifestError, load_cell
from .model import BackendError, resolve_backend
from .router import default_router


def _cmd_doctor(_: argparse.Namespace) -> int:
    print("STATUS=ready")
    print("RUNTIME=local")
    print("PLANES=offline,frontier,system,byok")
    print("OFFLINE_LOOP=ready")
    return 0


def _cmd_run(ns: argparse.Namespace) -> int:
    try:
        cell = load_cell(ns.manifest)
    except (ManifestError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

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
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
