"""Trace capture — the bridge from runtime to adapter training.

Every act/verify attempt is appended to a JSONL log with its gate verdict and
the full identity of the run that produced it (cell, plane, base, adapter,
decode params). Two things fall out of that:

- **Reproducibility is checkable.** Records carry no wall-clock time, so two
  identical runs write byte-identical trace files and `diff` is the proof.
- **The adapter plane bootstraps with no frontier teacher.** Gate-passing
  attempts are exactly a rejection-sampled dataset: sample the local model,
  keep only what passes the contract, train on that (STaR). The gate that
  guards the runtime is the same gate that filters the training set.

Export modes:

``star``
    Pair the *clean* first prompt with the output that eventually passed. This
    is what you want by default — the adapter should learn to succeed on the
    first attempt, not to depend on gate feedback that won't be there.
``repair``
    Pair the retry prompt (which carries the failure reason) with the passing
    output. Teaches self-correction; useful as a second adapter or a mix-in.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .loop import Attempt

SCHEMA = 1
EXPORT_MODES = ("star", "repair")


@dataclass(frozen=True)
class RunIdentity:
    """Everything that must be equal for two runs to be expected to match."""

    cell: str
    plane: str
    base: str
    adapter: str | None
    temperature: float
    seed: int


def run_hash(identity: RunIdentity, *, goal: str, source: str) -> str:
    """Stable 16-hex digest over the run's identity and its inputs.

    Same digest means: same cell, same weights, same decode, same task. Any
    difference in output between two runs sharing a digest is a reproducibility
    bug, and this is the handle you'd file it under.
    """
    payload = json.dumps(
        {"identity": asdict(identity), "goal": goal, "source": source},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class TraceWriter:
    """Appends one JSONL record per attempt. Wire it in as ``on_attempt``."""

    def __init__(
        self,
        *,
        path: str | Path,
        identity: RunIdentity,
        goal: str,
        source: str = "",
    ) -> None:
        self._path = Path(path)
        self._identity = identity
        self._goal = goal
        self._source = source
        self._run = run_hash(identity, goal=goal, source=source)

    @property
    def run(self) -> str:
        return self._run

    def record(self, attempt: Attempt) -> None:
        entry: dict[str, Any] = {
            "schema": SCHEMA,
            "run": self._run,
            "goal": self._goal,
            "source": self._source,
            "attempt": attempt.index,
            "prompt": attempt.prompt,
            "output": attempt.output,
            "passed": attempt.verdict.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in attempt.verdict.checks
            ],
            **asdict(self._identity),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


def read_traces(path: str | Path) -> list[dict[str, Any]]:
    """Read a trace log. A missing log is an empty one, not an error."""
    file = Path(path)
    if not file.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _by_run(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group attempts by run, preserving first-seen run order and attempt order."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record.get("run", "")), []).append(record)
    for attempts in grouped.values():
        attempts.sort(key=lambda r: int(r.get("attempt", 0)))
    return grouped


def _pair(prompt: str, output: str) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": output},
        ]
    }


def export_sft(records: list[dict[str, Any]], *, mode: str = "star") -> list[dict[str, Any]]:
    """Turn gate-passing attempts into chat-format SFT pairs.

    Order-stable and deterministic: the same trace log always exports the same
    dataset, in the same order.
    """
    if mode not in EXPORT_MODES:
        raise ValueError(f"unknown export mode {mode!r}; expected one of {EXPORT_MODES}")

    pairs: list[dict[str, Any]] = []
    for attempts in _by_run(records).values():
        winner = next((a for a in attempts if a.get("passed")), None)
        if winner is None:
            continue  # the run never satisfied its contract — not training data
        if mode == "star":
            pairs.append(_pair(str(attempts[0]["prompt"]), str(winner["output"])))
        elif int(winner.get("attempt", 1)) > 1:
            # Only runs that actually needed a repair teach repair.
            pairs.append(_pair(str(winner["prompt"]), str(winner["output"])))
    return pairs
