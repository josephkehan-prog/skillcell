"""CLI wiring for the gate, retries, traces, and the SFT export."""

from __future__ import annotations

import json
from pathlib import Path

from skillcell.cli import main

CELL = """apiVersion: skillcell.dev/v1alpha1
kind: Cell
metadata: {name: wordsmith}
spec:
  scope: tighten prose
  runtime: local
  loop:
    maxAttempts: 3
  contract:
    inputs: []
    outputs: []
    eval:
      checks:
        - preserves: numbers
        - forbid: '\\bTODO\\b'
  model:
    plane: local
    base: qwen2.5-7b-instruct
    decode: {temperature: 0.0, seed: 1}
"""


def _cell(tmp_path: Path) -> Path:
    path = tmp_path / "cell.yaml"
    path.write_text(CELL)
    return path


def _source(tmp_path: Path, text: str = "we shipped 3 cells") -> Path:
    path = tmp_path / "input.md"
    path.write_text(text)
    return path


# The echo transport returns the prompt, which contains the source text — so a
# `preserves: numbers` gate passes, and the whole path runs with no network.


def test_run_reports_verified_and_attempt_count(tmp_path: Path, capsys) -> None:
    rc = main(
        [
            "run",
            str(_cell(tmp_path)),
            "--goal",
            "tighten this",
            "--source",
            str(_source(tmp_path)),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["verified"] is True
    assert payload["status"] == "done"
    assert payload["attempts"] == 1


def test_failing_gate_exits_one_so_ci_can_see_it(tmp_path: Path, capsys) -> None:
    """A cell that cannot satisfy its contract must not report success."""
    rc = main(
        [
            "run",
            str(_cell(tmp_path)),
            "--goal",
            "tighten this",
            "--source",
            str(_source(tmp_path, "ship it TODO")),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["verified"] is False
    assert payload["status"] == "blocked"
    assert payload["attempts"] == 3  # maxAttempts from the manifest


def test_attempts_flag_overrides_the_manifest(tmp_path: Path, capsys) -> None:
    main(
        [
            "run",
            str(_cell(tmp_path)),
            "--goal",
            "g",
            "--source",
            str(_source(tmp_path, "ship it TODO")),
            "--attempts",
            "2",
            "--json",
        ]
    )
    assert json.loads(capsys.readouterr().out)["attempts"] == 2


def test_missing_source_file_is_a_manifest_grade_error(tmp_path: Path, capsys) -> None:
    rc = main(
        ["run", str(_cell(tmp_path)), "--goal", "g", "--source", str(tmp_path / "absent.md")]
    )
    assert rc == 2
    assert "absent.md" in capsys.readouterr().err


def test_offline_cell_writes_no_trace_file(tmp_path: Path) -> None:
    path = tmp_path / "offline.yaml"
    path.write_text(
        "apiVersion: skillcell.dev/v1alpha1\nkind: Cell\n"
        "metadata: {name: off}\nspec:\n  scope: s\n  runtime: local\n"
    )
    traces = tmp_path / "traces.jsonl"
    rc = main(["run", str(path), "--goal", "g", "--traces", str(traces)])
    assert rc == 0
    assert not traces.exists()


def test_run_writes_one_trace_record_per_attempt(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    main(
        [
            "run",
            str(_cell(tmp_path)),
            "--goal",
            "tighten this",
            "--source",
            str(_source(tmp_path, "ship it TODO")),
            "--traces",
            str(traces),
        ]
    )
    records = [json.loads(line) for line in traces.read_text().splitlines() if line.strip()]
    assert len(records) == 3
    assert records[0]["cell"] == "wordsmith"
    assert records[0]["base"] == "qwen2.5-7b-instruct"
    assert records[0]["passed"] is False


def test_traces_summary_reports_the_first_attempt_pass_rate(tmp_path: Path, capsys) -> None:
    """The one number that says whether an adapter is earning its keep."""
    traces = tmp_path / "traces.jsonl"
    for text in ("we shipped 3 cells", "ship it TODO"):
        main(
            [
                "run",
                str(_cell(tmp_path)),
                "--goal",
                f"tighten {text}",
                "--source",
                str(_source(tmp_path, text)),
                "--traces",
                str(traces),
            ]
        )
    capsys.readouterr()  # discard the run output; only the summary is under test
    rc = main(["traces", str(traces), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["runs"] == 2
    assert payload["passed"] == 1
    assert payload["first_attempt_pass_rate"] == 0.5


def test_traces_export_writes_sft_pairs(tmp_path: Path, capsys) -> None:
    traces = tmp_path / "traces.jsonl"
    main(
        [
            "run",
            str(_cell(tmp_path)),
            "--goal",
            "tighten this",
            "--source",
            str(_source(tmp_path)),
            "--traces",
            str(traces),
        ]
    )
    out = tmp_path / "sft.jsonl"
    rc = main(["traces", str(traces), "--export", str(out)])
    assert rc == 0
    pairs = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(pairs) == 1
    assert pairs[0]["messages"][0]["role"] == "user"
    assert "EXPORTED=1" in capsys.readouterr().out


def test_traces_on_a_missing_log_reports_zero(tmp_path: Path, capsys) -> None:
    rc = main(["traces", str(tmp_path / "absent.jsonl"), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["runs"] == 0


def test_doctor_lists_the_local_plane_first(capsys) -> None:
    main(["doctor"])
    out = capsys.readouterr().out
    assert "PLANES=local,offline,frontier,byok" in out
