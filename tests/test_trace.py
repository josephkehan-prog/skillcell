"""Trace capture: the bridge from runtime to adapter training.

Every attempt is recorded with its gate verdict. Gate-passing attempts are the
rejection-sampled dataset a LoRA is trained on — which is how the adapter plane
bootstraps with no frontier teacher in the loop.
"""

from __future__ import annotations

import json
from pathlib import Path

from skillcell.loop import run_loop
from skillcell.trace import (
    RunIdentity,
    TraceWriter,
    export_sft,
    read_traces,
    run_hash,
)
from skillcell.verify import Check

IDENTITY = RunIdentity(
    cell="wordsmith",
    plane="local",
    base="qwen2.5-7b-instruct",
    adapter="wordsmith@v1",
    temperature=0.0,
    seed=1,
)
NUMBERS = (Check("preserves", "numbers"),)


def _writer(tmp_path: Path, **kw: object) -> TraceWriter:
    defaults: dict[str, object] = {
        "path": tmp_path / "traces.jsonl",
        "identity": IDENTITY,
        "goal": "tighten this",
        "source": "kept 3 items",
    }
    return TraceWriter(**{**defaults, **kw})  # type: ignore[arg-type]


# --- run identity -----------------------------------------------------------


def test_run_hash_is_stable_for_identical_inputs() -> None:
    assert run_hash(IDENTITY, goal="g", source="s") == run_hash(IDENTITY, goal="g", source="s")


def test_run_hash_changes_with_the_adapter() -> None:
    other = RunIdentity(**{**IDENTITY.__dict__, "adapter": "wordsmith@v2"})
    assert run_hash(IDENTITY, goal="g", source="s") != run_hash(other, goal="g", source="s")


def test_run_hash_changes_with_decode_params() -> None:
    hot = RunIdentity(**{**IDENTITY.__dict__, "temperature": 0.7})
    assert run_hash(IDENTITY, goal="g", source="s") != run_hash(hot, goal="g", source="s")


def test_run_hash_changes_with_the_goal() -> None:
    assert run_hash(IDENTITY, goal="a", source="s") != run_hash(IDENTITY, goal="b", source="s")


# --- writing ----------------------------------------------------------------


def test_writer_appends_one_record_per_attempt(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    writer = _writer(tmp_path)
    outputs = iter(["dropped it", "kept 3 items"])

    run_loop(
        goal="tighten this",
        router=lambda g: "wordsmith",
        backend=lambda p: next(outputs),
        source="kept 3 items",
        checks=NUMBERS,
        max_attempts=3,
        on_attempt=writer.record,
    )

    records = read_traces(path)
    assert [r["attempt"] for r in records] == [1, 2]
    assert [r["passed"] for r in records] == [False, True]
    assert records[0]["cell"] == "wordsmith"
    assert records[0]["adapter"] == "wordsmith@v1"


def test_record_carries_per_check_detail(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    run_loop(
        goal="tighten this",
        router=lambda g: "wordsmith",
        backend=lambda p: "dropped it",
        source="kept 3 items",
        checks=NUMBERS,
        on_attempt=writer.record,
    )
    (record,) = read_traces(tmp_path / "traces.jsonl")
    assert record["checks"] == [
        {"name": "preserves", "passed": False, "detail": "numbers dropped: 3"}
    ]


def test_writer_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "traces.jsonl"
    writer = _writer(tmp_path, path=path)
    run_loop(
        goal="tighten this",
        router=lambda g: "wordsmith",
        backend=lambda p: "kept 3 items",
        source="kept 3 items",
        checks=NUMBERS,
        on_attempt=writer.record,
    )
    assert path.exists()


def test_writer_appends_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    for goal in ("first", "second"):
        writer = _writer(tmp_path, goal=goal)
        run_loop(
            goal=goal,
            router=lambda g: "wordsmith",
            backend=lambda p: "kept 3 items",
            source="kept 3 items",
            checks=NUMBERS,
            on_attempt=writer.record,
        )
    assert len(read_traces(path)) == 2


def test_trace_file_is_byte_identical_across_identical_runs(tmp_path: Path) -> None:
    """No wall-clock in the record: two identical runs produce identical logs,
    so reproducibility is checkable with a diff."""

    def emit(name: str) -> bytes:
        path = tmp_path / name
        writer = _writer(tmp_path, path=path)
        outputs = iter(["dropped it", "kept 3 items"])
        run_loop(
            goal="tighten this",
            router=lambda g: "wordsmith",
            backend=lambda p: next(outputs),
            source="kept 3 items",
            checks=NUMBERS,
            max_attempts=3,
            on_attempt=writer.record,
        )
        return path.read_bytes()

    assert emit("a.jsonl") == emit("b.jsonl")


def test_reading_a_missing_trace_file_returns_empty(tmp_path: Path) -> None:
    assert read_traces(tmp_path / "absent.jsonl") == []


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    path.write_text(json.dumps({"attempt": 1}) + "\n\n\n")
    assert len(read_traces(path)) == 1


# --- SFT export -------------------------------------------------------------


def _seed(tmp_path: Path, goal: str, outputs: list[str]) -> None:
    writer = _writer(tmp_path, goal=goal)
    it = iter(outputs)
    run_loop(
        goal=goal,
        router=lambda g: "wordsmith",
        backend=lambda p: next(it),
        source="kept 3 items",
        checks=NUMBERS,
        max_attempts=len(outputs),
        on_attempt=writer.record,
    )


def test_export_keeps_only_gate_passing_runs(tmp_path: Path) -> None:
    _seed(tmp_path, "good", ["kept 3 items"])
    _seed(tmp_path, "bad", ["dropped it", "dropped again"])

    pairs = export_sft(read_traces(tmp_path / "traces.jsonl"))
    assert len(pairs) == 1
    assert pairs[0]["messages"][1]["content"] == "kept 3 items"


def test_star_export_pairs_the_clean_prompt_with_the_passing_output(tmp_path: Path) -> None:
    """Rejection sampling: train on (original task -> output that passed),
    not on (retry-with-feedback -> output). The adapter should learn to
    succeed first time, not to need the feedback."""
    _seed(tmp_path, "tighten", ["dropped it", "kept 3 items"])

    (pair,) = export_sft(read_traces(tmp_path / "traces.jsonl"))
    user = pair["messages"][0]["content"]
    assert "failed the cell gate" not in user
    assert pair["messages"][1]["content"] == "kept 3 items"


def test_repair_export_teaches_self_correction(tmp_path: Path) -> None:
    _seed(tmp_path, "tighten", ["dropped it", "kept 3 items"])

    (pair,) = export_sft(read_traces(tmp_path / "traces.jsonl"), mode="repair")
    assert "failed the cell gate" in pair["messages"][0]["content"]
    assert pair["messages"][1]["content"] == "kept 3 items"


def test_repair_export_is_empty_when_nothing_needed_repair(tmp_path: Path) -> None:
    _seed(tmp_path, "clean", ["kept 3 items"])
    assert export_sft(read_traces(tmp_path / "traces.jsonl"), mode="repair") == []


def test_export_is_deterministic_and_order_stable(tmp_path: Path) -> None:
    _seed(tmp_path, "one", ["kept 3 items"])
    _seed(tmp_path, "two", ["kept 3 items"])
    records = read_traces(tmp_path / "traces.jsonl")
    assert export_sft(records) == export_sft(records)
    assert len(export_sft(records)) == 2
