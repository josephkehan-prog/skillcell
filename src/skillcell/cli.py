"""skillcell CLI: doctor + run (offline-first local cell runner)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from .loop import run_loop
from .manifest import ManifestError, load_cell, load_chain
from .model import BackendError, resolve_backend
from .router import default_router


def _cmd_doctor(_: argparse.Namespace) -> int:
    print("STATUS=ready")
    print("RUNTIME=local")
    print("PLANES=offline,frontier,system,byok")
    print("OFFLINE_LOOP=ready")
    return 0


def _cmd_validate(ns: argparse.Namespace) -> int:
    try:
        text = Path(ns.manifest).read_text()
        docs = list(yaml.safe_load_all(text))
        if not docs or not isinstance(docs[0], dict):
            raise ManifestError("manifest must be a mapping")
        kind = docs[0].get("kind")
    except (FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML: {exc}", file=sys.stderr)
        return 2

    try:
        if kind == "Cell":
            cell = load_cell(ns.manifest)
            print(f"VALID kind=Cell name={cell.name}")
            return 0
        elif kind == "Chain":
            chain = load_chain(ns.manifest)
            print(f"VALID kind=Chain name={chain.name}")
            return 0
        else:
            raise ManifestError(f"unexpected kind '{kind}'")
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


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

    v = sub.add_parser("validate", help="validate a manifest (Cell or Chain)")
    v.add_argument("manifest", help="path to a manifest")
    v.set_defaults(func=_cmd_validate)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
