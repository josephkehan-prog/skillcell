"""Parsing of spec.contract.eval and spec.loop.

These blocks were design-spec only: documented in the example manifest and
enforced by nothing. A gate that is not parsed is not a gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillcell.manifest import ManifestError, load_cell
from skillcell.verify import Check

BASE = """apiVersion: skillcell.dev/v1alpha1
kind: Cell
metadata:
  name: test-cell
spec:
  scope: "a scope"
  runtime: local
"""


def _cell(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "cell.yaml"
    path.write_text(BASE + body)
    return path


def test_cell_without_eval_has_no_checks(tmp_path: Path) -> None:
    cell = load_cell(_cell(tmp_path, ""))
    assert cell.eval.checks == ()
    assert cell.eval.coverage_floor is None


def test_checks_parse_in_declared_order(tmp_path: Path) -> None:
    cell = load_cell(
        _cell(
            tmp_path,
            """
  contract:
    eval:
      checks:
        - command: ./eval/lint.sh
        - preserves: numbers
        - forbid: '\\bTODO\\b'
        - require: '^## Summary'
        - maxEditRatio: 0.5
""",
        )
    )
    assert cell.eval.checks == (
        Check("command", "./eval/lint.sh"),
        Check("preserves", "numbers"),
        Check("forbid", "\\bTODO\\b"),
        Check("require", "^## Summary"),
        Check("max_edit_ratio", 0.5),
    )


def test_legacy_gate_script_becomes_a_command_check(tmp_path: Path) -> None:
    """The old single-script `eval.gate` form still works."""
    cell = load_cell(
        _cell(
            tmp_path,
            """
  contract:
    eval:
      gate: ./eval/run.sh
      coverageFloor: 0.8
""",
        )
    )
    assert cell.eval.checks == (Check("command", "./eval/run.sh"),)
    assert cell.eval.coverage_floor == 0.8


def test_unknown_check_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="unknown check"):
        load_cell(
            _cell(tmp_path, "\n  contract:\n    eval:\n      checks:\n        - vibes: good\n")
        )


def test_check_entry_must_have_exactly_one_key(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="exactly one"):
        load_cell(
            _cell(
                tmp_path,
                "\n  contract:\n    eval:\n      checks:\n"
                "        - require: a\n          forbid: b\n",
            )
        )


def test_unknown_preserve_class_is_caught_at_parse_time(tmp_path: Path) -> None:
    """`skillcell validate` should catch this, not the run that uses it."""
    with pytest.raises(ManifestError, match="unknown preserve class"):
        load_cell(
            _cell(
                tmp_path, "\n  contract:\n    eval:\n      checks:\n        - preserves: vibes\n"
            )
        )


def test_invalid_regex_is_caught_at_parse_time(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="invalid regex"):
        load_cell(
            _cell(
                tmp_path,
                "\n  contract:\n    eval:\n      checks:\n        - require: '([unclosed'\n",
            )
        )


def test_non_numeric_edit_ratio_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="maxEditRatio"):
        load_cell(
            _cell(
                tmp_path, "\n  contract:\n    eval:\n      checks:\n        - maxEditRatio: loose\n"
            )
        )


def test_edit_ratio_must_be_a_fraction(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="between 0 and 1"):
        load_cell(
            _cell(tmp_path, "\n  contract:\n    eval:\n      checks:\n        - maxEditRatio: 4\n")
        )


# --- spec.loop --------------------------------------------------------------


def test_loop_defaults_to_a_single_attempt(tmp_path: Path) -> None:
    cell = load_cell(_cell(tmp_path, ""))
    assert cell.loop.max_attempts == 1
    assert cell.loop.stop_on == "decisionBoundary"


def test_loop_max_attempts_is_parsed(tmp_path: Path) -> None:
    cell = load_cell(_cell(tmp_path, "\n  loop:\n    maxAttempts: 6\n    stopOn: gatePassed\n"))
    assert cell.loop.max_attempts == 6
    assert cell.loop.stop_on == "gatePassed"


def test_max_attempts_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="maxAttempts"):
        load_cell(_cell(tmp_path, "\n  loop:\n    maxAttempts: 0\n"))
