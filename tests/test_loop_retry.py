"""Gate-driven retry: the mechanism behind "completes the task every time".

Reliability is an inference-time property, not a weights property. The cell
retries until its gate passes and reports ``blocked`` if it never does — so a
small local model reaches the same guarantee a large one would, given attempts.
"""

from __future__ import annotations

from skillcell.loop import STAGES, Attempt, run_loop
from skillcell.verify import Check


def _router(goal: str) -> str:
    return "wordsmith"


def _stage(result, name: str):  # type: ignore[no-untyped-def]
    return next(s for s in result.stages if s.name == name)


NUMBERS = (Check("preserves", "numbers"),)


def test_verify_stage_exists_in_the_canonical_stage_list() -> None:
    assert STAGES == ["align", "review", "select", "gate", "act", "verify", "record", "stop"]


def test_offline_run_still_emits_every_stage_with_verify_skipped() -> None:
    result = run_loop(goal="tighten this", router=_router, backend=None, checks=NUMBERS)
    assert [s.name for s in result.stages] == STAGES
    assert _stage(result, "act").status == "skipped"
    assert _stage(result, "verify").status == "skipped"
    assert result.status == "skipped"
    assert result.attempts == ()


def test_passing_gate_on_first_attempt_reports_done() -> None:
    result = run_loop(
        goal="tighten this",
        router=_router,
        backend=lambda p: "kept 3 items",
        source="kept 3 items",
        checks=NUMBERS,
    )
    assert result.verified is True
    assert result.status == "done"
    assert len(result.attempts) == 1
    assert _stage(result, "verify").status == "done"
    assert result.stopped_at == "gatePassed"


def test_loop_retries_until_the_gate_passes() -> None:
    outputs = iter(["dropped the figure", "dropped it again", "kept 3 items"])

    result = run_loop(
        goal="tighten this",
        router=_router,
        backend=lambda p: next(outputs),
        source="kept 3 items",
        checks=NUMBERS,
        max_attempts=5,
    )
    assert result.verified is True
    assert result.status == "done"
    assert len(result.attempts) == 3
    assert result.output == "kept 3 items"


def test_exhausted_attempts_report_blocked_not_done() -> None:
    """A cell that cannot satisfy its contract must never claim success."""
    result = run_loop(
        goal="tighten this",
        router=_router,
        backend=lambda p: "always drops the figure",
        source="kept 3 items",
        checks=NUMBERS,
        max_attempts=3,
    )
    assert result.verified is False
    assert result.status == "blocked"
    assert len(result.attempts) == 3
    assert _stage(result, "verify").status == "blocked"
    assert result.stopped_at == "attemptsExhausted"


def test_retry_prompt_carries_the_gate_failure_reason() -> None:
    """Retry must change the prompt, or a pinned decode repeats itself forever."""
    prompts: list[str] = []

    def backend(prompt: str) -> str:
        prompts.append(prompt)
        return "kept 3 items" if len(prompts) == 2 else "dropped it"

    run_loop(
        goal="tighten this",
        router=_router,
        backend=backend,
        source="kept 3 items",
        checks=NUMBERS,
        max_attempts=4,
    )
    assert len(prompts) == 2
    assert "numbers dropped: 3" in prompts[1]
    assert prompts[0] != prompts[1]


def test_no_checks_means_the_gate_passes_vacuously() -> None:
    result = run_loop(goal="anything", router=_router, backend=lambda p: "out")
    assert result.verified is True
    assert result.status == "done"
    assert len(result.attempts) == 1


def test_authorization_block_skips_act_and_verify() -> None:
    result = run_loop(
        goal="tighten this",
        router=_router,
        backend=lambda p: "out",
        checks=NUMBERS,
        act_mode=True,
        authorized=False,
    )
    assert _stage(result, "act").status == "blocked"
    assert _stage(result, "verify").status == "skipped"
    assert result.status == "blocked"
    assert result.attempts == ()


def test_on_attempt_hook_sees_every_attempt_in_order() -> None:
    """The trace seam: attempts stream out for capture without the loop
    knowing where they are written."""
    seen: list[Attempt] = []
    outputs = iter(["nope", "kept 3 items"])

    run_loop(
        goal="tighten this",
        router=_router,
        backend=lambda p: next(outputs),
        source="kept 3 items",
        checks=NUMBERS,
        max_attempts=3,
        on_attempt=seen.append,
    )
    assert [a.index for a in seen] == [1, 2]
    assert [a.verdict.passed for a in seen] == [False, True]
    assert seen[-1].output == "kept 3 items"


def test_retry_sequence_is_deterministic() -> None:
    def make():  # type: ignore[no-untyped-def]
        outputs = iter(["bad", "worse", "kept 3 items"])
        return run_loop(
            goal="tighten this",
            router=_router,
            backend=lambda p: next(outputs),
            source="kept 3 items",
            checks=NUMBERS,
            max_attempts=5,
        )

    first, second = make(), make()
    assert [a.output for a in first.attempts] == [a.output for a in second.attempts]
    assert first.status == second.status
    assert first.stopped_at == second.stopped_at
