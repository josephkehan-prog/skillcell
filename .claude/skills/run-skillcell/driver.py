"""Agent driver for skillcell: smoke the CLI, drive the TUI, capture screenshots.

Run from the repo root with uv (dev group has textual + pytest deps):

    uv run python .claude/skills/run-skillcell/driver.py smoke
    uv run python .claude/skills/run-skillcell/driver.py tui-screenshot [out.svg]

`smoke` exercises every CLI surface (doctor, validate on all examples, an
offline run) and exits non-zero on the first mismatch. `tui-screenshot`
drives the Textual app headless through its pilot harness — selects
cell.yaml, runs the offline loop with the `r` key — and writes an SVG
screenshot of the resulting screen.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples"


def _run(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=REPO, check=False)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        sys.exit(1)


def smoke() -> None:
    code, out = _run(["uv", "run", "skillcell", "doctor"])
    _check("doctor exits 0", code == 0, out)
    _check("doctor reports ready", "STATUS=ready" in out, out)

    for manifest in sorted(EXAMPLES.glob("*.yaml")):
        code, out = _run(["uv", "run", "skillcell", "validate", str(manifest)])
        _check(f"validate {manifest.name}", code == 0 and "VALID" in out, out)

    code, out = _run(
        [
            "uv",
            "run",
            "skillcell",
            "run",
            str(EXAMPLES / "cell.yaml"),
            "--goal",
            "triage firmware image",
            "--json",
        ]
    )
    _check("offline run exits 0", code == 0, out)
    payload = json.loads(out)
    _check("route is firmware-pentest", payload["route"] == "firmware-pentest", out)
    _check("act stage skipped offline", not payload["executed"], out)
    stages = [s["name"] for s in payload["stages"]]
    _check("all seven stages present", stages == [
        "align", "review", "select", "gate", "act", "record", "stop"
    ], str(stages))

    code, out = _run(["uv", "run", "skillcell", "validate", "/nonexistent.yaml"])
    _check("missing manifest exits 2", code == 2, out)
    print("smoke: all checks passed")


async def _tui_screenshot(out_path: Path) -> None:
    sys.path.insert(0, str(REPO / "src"))
    from textual.widgets import ListView

    from skillcell.tui import SkillcellApp

    app = SkillcellApp(manifest_dir=EXAMPLES)
    async with app.run_test(size=(100, 32)) as pilot:
        listing = pilot.app.query_one("#manifest-list", ListView)
        listing.index = [item.name for item in listing.children].index("cell.yaml")
        await pilot.press("enter")
        await pilot.press("r")
        await pilot.pause()
        pilot.app.save_screenshot(str(out_path))
    print(f"screenshot written: {out_path}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke()
    elif mode == "tui-screenshot":
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "tui-screenshot.svg"
        asyncio.run(_tui_screenshot(out))
    else:
        print(f"unknown mode '{mode}'; use: smoke | tui-screenshot [out.svg]", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
