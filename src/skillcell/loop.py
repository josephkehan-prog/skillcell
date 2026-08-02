"""The in-cell agent loop.

Seven stages, deterministic routing, offline-first. With no backend the loop
still aligns, routes, gates, records, and stops — the ``act`` stage is marked
``skipped``. A backend enables the specialist turn without changing the
contract. Act mode additionally requires an authorization gate to pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

STAGES = ["align", "review", "select", "gate", "act", "record", "stop"]

Router = Callable[[str], str]
Backend = Callable[[str], str]


@dataclass
class Stage:
    name: str
    status: str  # done | skipped | blocked
    detail: str = ""


@dataclass
class LoopResult:
    goal: str
    route: str
    executed: bool
    output: str | None
    stages: list[Stage] = field(default_factory=list)
    stopped_at: str = "decisionBoundary"


def run_loop(
    *,
    goal: str,
    router: Router,
    backend: Backend | None,
    act_mode: bool = False,
    authorized: bool = False,
) -> LoopResult:
    stages: list[Stage] = []

    stages.append(Stage("align", "done", goal))
    stages.append(Stage("review", "done", "retained context reviewed"))

    route = router(goal)
    stages.append(Stage("select", "done", route))

    # Authorization gate: only blocks when act mode is requested.
    if act_mode and not authorized:
        stages.append(Stage("gate", "blocked", "authorization required for act mode"))
        gate_ok = False
    else:
        stages.append(Stage("gate", "done", "scope satisfied"))
        gate_ok = True

    executed = False
    output: str | None = None
    if backend is None:
        stages.append(Stage("act", "skipped", "no model configured (offline)"))
    elif not gate_ok:
        stages.append(Stage("act", "blocked", "authorization gate not satisfied"))
    else:
        prompt = f"[route:{route}] goal: {goal}"
        output = backend(prompt)
        executed = True
        stages.append(Stage("act", "done"))

    stages.append(Stage("record", "done", "route and result recorded"))
    stages.append(Stage("stop", "done", "decisionBoundary"))

    return LoopResult(
        goal=goal,
        route=route,
        executed=executed,
        output=output,
        stages=stages,
        stopped_at="decisionBoundary",
    )
