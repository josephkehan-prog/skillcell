from skillcell.loop import STAGES, LoopResult, run_loop


def _router(goal: str) -> str:
    # deterministic specialist selection
    return "firmware-pentest" if "firmware" in goal.lower() else "generalist"


def test_offline_loop_records_all_stages_and_skips_execute():
    result = run_loop(goal="triage firmware", router=_router, backend=None)
    assert isinstance(result, LoopResult)
    assert [s.name for s in result.stages] == STAGES
    act = next(s for s in result.stages if s.name == "act")
    assert act.status == "skipped"
    assert result.route == "firmware-pentest"
    assert result.executed is False


def test_loop_with_backend_executes_act_stage():
    calls = {}

    def backend(prompt: str) -> str:
        calls["prompt"] = prompt
        return "specialist output"

    result = run_loop(goal="triage firmware", router=_router, backend=backend)
    act = next(s for s in result.stages if s.name == "act")
    assert act.status == "done"
    assert result.executed is True
    assert result.output == "specialist output"
    assert "firmware-pentest" in calls["prompt"]


def test_loop_stops_at_decision_boundary():
    result = run_loop(goal="anything", router=_router, backend=None)
    assert result.stages[-1].name == "stop"
    assert result.stopped_at == "decisionBoundary"


def test_act_gate_blocks_without_authorization():
    # act mode requested but authorization missing -> gate fails, execute blocked
    result = run_loop(
        goal="triage firmware",
        router=_router,
        backend=lambda p: "out",
        act_mode=True,
        authorized=False,
    )
    gate = next(s for s in result.stages if s.name == "gate")
    assert gate.status == "blocked"
    assert result.executed is False


def test_act_gate_passes_with_authorization():
    result = run_loop(
        goal="triage firmware",
        router=_router,
        backend=lambda p: "out",
        act_mode=True,
        authorized=True,
    )
    gate = next(s for s in result.stages if s.name == "gate")
    assert gate.status == "done"
    assert result.executed is True


def test_loop_is_deterministic_same_inputs_same_route():
    a = run_loop(goal="triage firmware", router=_router, backend=None)
    b = run_loop(goal="triage firmware", router=_router, backend=None)
    assert a.route == b.route
    assert [s.name for s in a.stages] == [s.name for s in b.stages]
