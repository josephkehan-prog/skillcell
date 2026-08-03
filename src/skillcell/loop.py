"""The in-cell agent loop.

Eight stages, deterministic routing, offline-first. With no backend the loop
still aligns, routes, gates, records, and stops — ``act`` and ``verify`` are
marked ``skipped``. A backend enables the specialist turn without changing the
contract. Act mode additionally requires an authorization gate to pass.

**Reliability comes from the gate, not the weights.** The loop repeats
act/verify until the cell's gate passes, and reports ``blocked`` if it never
does. That is what lets a small local model reach the same guarantee a large
one would: it gets more attempts, not more parameters.

Retry stays deterministic because each retry *changes the prompt* — the next
attempt is a pure function of the goal, the source, and the previous verdicts.
Retrying an unchanged prompt at temperature 0 would just reproduce the same
failing output forever.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .verify import Check, Verdict, run_checks

STAGES = ["align", "review", "select", "gate", "act", "verify", "record", "stop"]

Router = Callable[[str], str]
Backend = Callable[[str], str]


@dataclass
class Stage:
    name: str
    status: str  # done | skipped | blocked
    detail: str = ""


@dataclass(frozen=True)
class Attempt:
    """One act/verify cycle — the unit of both retry and training data."""

    index: int
    prompt: str
    output: str
    verdict: Verdict


@dataclass
class LoopResult:
    goal: str
    route: str
    executed: bool
    output: str | None
    stages: list[Stage] = field(default_factory=list)
    stopped_at: str = "decisionBoundary"
    attempts: tuple[Attempt, ...] = ()
    verified: bool = False
    status: str = "skipped"  # done | skipped | blocked


def build_prompt(
    *,
    goal: str,
    route: str,
    source: str,
    previous: tuple[Attempt, ...] = (),
) -> str:
    """Build attempt N's prompt from the goal and every prior verdict.

    Pure and order-stable: the same (goal, route, source, previous) always
    yields the same prompt, so a pinned decode yields the same attempt.
    """
    parts = [f"[route:{route}] goal: {goal}"]
    if source:
        parts.append(f"source:\n{source}")
    if previous:
        last = previous[-1]
        parts.append(
            f"attempt {last.index} failed the cell gate: {last.verdict.reason()}\n"
            "Revise the output so every check passes. Change only what the "
            "failures require."
        )
    return "\n\n".join(parts)


def run_loop(
    *,
    goal: str,
    router: Router,
    backend: Backend | None,
    act_mode: bool = False,
    authorized: bool = False,
    source: str = "",
    checks: tuple[Check, ...] = (),
    max_attempts: int = 1,
    cwd: str = ".",
    on_attempt: Callable[[Attempt], None] | None = None,
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

    if backend is None:
        stages.append(Stage("act", "skipped", "no model configured (offline)"))
        stages.append(Stage("verify", "skipped", "nothing to verify"))
        return _finish(goal, route, stages, status="skipped")

    if not gate_ok:
        stages.append(Stage("act", "blocked", "authorization gate not satisfied"))
        stages.append(Stage("verify", "skipped", "act did not run"))
        return _finish(goal, route, stages, status="blocked")

    attempts: list[Attempt] = []
    for index in range(1, max(1, max_attempts) + 1):
        prompt = build_prompt(goal=goal, route=route, source=source, previous=tuple(attempts))
        output = backend(prompt)
        verdict = run_checks(checks, source=source, output=output, cwd=cwd)
        attempt = Attempt(index=index, prompt=prompt, output=output, verdict=verdict)
        attempts.append(attempt)
        if on_attempt is not None:
            on_attempt(attempt)
        if verdict.passed:
            break

    last = attempts[-1]
    verified = last.verdict.passed
    stages.append(Stage("act", "done", f"{len(attempts)} attempt(s)"))
    if verified:
        stages.append(Stage("verify", "done", f"gate passed on attempt {last.index}"))
    else:
        stages.append(Stage("verify", "blocked", last.verdict.reason() or "gate not satisfied"))

    return _finish(
        goal,
        route,
        stages,
        status="done" if verified else "blocked",
        executed=True,
        output=last.output,
        attempts=tuple(attempts),
        verified=verified,
        stopped_at="gatePassed" if verified else "attemptsExhausted",
    )


def _finish(
    goal: str,
    route: str,
    stages: list[Stage],
    *,
    status: str,
    executed: bool = False,
    output: str | None = None,
    attempts: tuple[Attempt, ...] = (),
    verified: bool = False,
    stopped_at: str = "decisionBoundary",
) -> LoopResult:
    stages.append(Stage("record", "done", f"{len(attempts)} attempt(s) recorded"))
    stages.append(Stage("stop", "done", stopped_at))
    return LoopResult(
        goal=goal,
        route=route,
        executed=executed,
        output=output,
        stages=stages,
        stopped_at=stopped_at,
        attempts=attempts,
        verified=verified,
        status=status,
    )
