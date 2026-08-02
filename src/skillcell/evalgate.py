"""Cell eval gate: a cell reports done only if its gate script exits 0."""

from __future__ import annotations

import subprocess  # nosec B404 - the eval gate exists to run a cell-declared script
from dataclasses import dataclass


@dataclass
class EvalResult:
    passed: bool
    exit_code: int
    output: str


def run_gate(script: str, *, cwd: str, timeout: int = 600) -> EvalResult:
    try:
        # Fixed argv, shell=False: the script path is the cell's own declared
        # gate, run inside the cell scope. No shell interpolation of any input.
        proc = subprocess.run(  # noqa: S603  # nosec B603
            [script],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return EvalResult(passed=False, exit_code=127, output=str(exc))
    except subprocess.TimeoutExpired as exc:
        return EvalResult(passed=False, exit_code=124, output=f"timeout: {exc}")

    output = (proc.stdout or "") + (proc.stderr or "")
    return EvalResult(passed=proc.returncode == 0, exit_code=proc.returncode, output=output)
