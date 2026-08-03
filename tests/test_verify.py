"""The composable cell verifier.

The gate is the crown jewel: it is the runtime guarantee, the training-data
filter, and (later) the reward signal. These tests pin its contract.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from skillcell.verify import (
    Check,
    CheckResult,
    Verdict,
    VerifyError,
    edit_ratio,
    run_checks,
)


def _verdict(checks: list[Check], *, source: str = "", output: str = "", cwd: str = ".") -> Verdict:
    return run_checks(tuple(checks), source=source, output=output, cwd=cwd)


# --- empty / aggregate behaviour -------------------------------------------


def test_no_checks_passes_vacuously() -> None:
    v = _verdict([])
    assert v.passed is True
    assert v.checks == ()


def test_verdict_fails_if_any_check_fails() -> None:
    v = _verdict(
        [Check("require", "hello"), Check("forbid", "hello")],
        output="hello world",
    )
    assert v.passed is False
    assert len(v.checks) == 2
    assert [c.passed for c in v.checks] == [True, False]


def test_failures_returns_only_failed_checks() -> None:
    v = _verdict(
        [Check("require", "alpha"), Check("require", "omega")],
        output="alpha only",
    )
    failures = v.failures()
    assert len(failures) == 1
    assert failures[0].name == "require"
    assert "omega" in failures[0].detail


# --- require / forbid -------------------------------------------------------


def test_require_pattern_present() -> None:
    assert _verdict([Check("require", r"^## Summary")], output="## Summary\nbody").passed


def test_require_pattern_absent_fails() -> None:
    assert not _verdict([Check("require", r"^## Summary")], output="body").passed


def test_forbid_pattern_absent_passes() -> None:
    assert _verdict([Check("forbid", r"\bTODO\b")], output="finished text").passed


def test_forbid_pattern_present_fails() -> None:
    assert not _verdict([Check("forbid", r"\bTODO\b")], output="still a TODO here").passed


def test_invalid_regex_is_a_verify_error() -> None:
    with pytest.raises(VerifyError, match="invalid regex"):
        _verdict([Check("require", "([unclosed")], output="x")


# --- preservation guards: the semantic-drift catchers ------------------------


def test_preserves_numbers_passes_when_all_survive() -> None:
    v = _verdict(
        [Check("preserves", "numbers")],
        source="We shipped 3 cells and cut latency by 42.5 percent.",
        output="Latency fell 42.5 percent across the 3 cells we shipped.",
    )
    assert v.passed


def test_preserves_numbers_catches_a_dropped_figure() -> None:
    v = _verdict(
        [Check("preserves", "numbers")],
        source="We shipped 3 cells and cut latency by 42.5 percent.",
        output="We shipped 3 cells and cut latency substantially.",
    )
    assert not v.passed
    assert "42.5" in v.failures()[0].detail


def test_preserves_urls() -> None:
    src = "See https://example.com/spec for detail."
    assert _verdict([Check("preserves", "urls")], source=src, output=f"Detail: {src}").passed
    assert not _verdict([Check("preserves", "urls")], source=src, output="See the spec.").passed


def test_preserves_emails() -> None:
    src = "Contact ops@example.com."
    check = [Check("preserves", "emails")]
    assert _verdict(check, source=src, output="Mail ops@example.com").passed
    assert not _verdict(check, source=src, output="Mail the team").passed


def test_preserves_acronyms() -> None:
    src = "The API returns HTTP 204."
    check = [Check("preserves", "acronyms")]
    assert _verdict(check, source=src, output="HTTP 204 from the API").passed
    assert not _verdict(check, source=src, output="It returns 204").passed


def test_preserves_negations_catches_a_flipped_negation() -> None:
    """The failure mode determinism would otherwise reproduce forever."""
    v = _verdict(
        [Check("preserves", "negations")],
        source="The cell does not reach the network.",
        output="The cell reaches the network.",
    )
    assert not v.passed
    assert "negation" in v.failures()[0].detail.lower()


def test_preserves_negations_allows_equivalent_rewording() -> None:
    v = _verdict(
        [Check("preserves", "negations")],
        source="The cell does not reach the network.",
        output="The network is not reachable from the cell.",
    )
    assert v.passed


def test_unknown_preserve_class_is_a_verify_error() -> None:
    with pytest.raises(VerifyError, match="unknown preserve class"):
        _verdict([Check("preserves", "vibes")], source="a", output="b")


# --- bounded rewrite --------------------------------------------------------


def test_edit_ratio_is_zero_for_identical_text() -> None:
    assert edit_ratio("one two three", "one two three") == 0.0


def test_edit_ratio_is_one_for_disjoint_text() -> None:
    assert edit_ratio("alpha beta", "gamma delta") == 1.0


def test_max_edit_ratio_allows_a_light_rewrite() -> None:
    v = _verdict(
        [Check("max_edit_ratio", 0.5)],
        source="the quick brown fox jumps over the lazy dog",
        output="the quick brown fox leaps over the lazy dog",
    )
    assert v.passed


def test_max_edit_ratio_rejects_a_from_scratch_rewrite() -> None:
    """Stops the model from 'solving' the gate by discarding the input."""
    v = _verdict(
        [Check("max_edit_ratio", 0.3)],
        source="the quick brown fox jumps over the lazy dog",
        output="completely unrelated replacement prose about shipping software",
    )
    assert not v.passed


# --- command check ----------------------------------------------------------


def _script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "gate.sh"
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_command_check_passes_on_exit_zero(tmp_path: Path) -> None:
    v = _verdict([Check("command", _script(tmp_path, "exit 0"))], cwd=str(tmp_path))
    assert v.passed


def test_command_check_fails_on_nonzero_exit(tmp_path: Path) -> None:
    v = _verdict([Check("command", _script(tmp_path, "echo nope >&2; exit 1"))], cwd=str(tmp_path))
    assert not v.passed
    assert "nope" in v.failures()[0].detail


def test_missing_command_fails_rather_than_raising(tmp_path: Path) -> None:
    v = _verdict([Check("command", str(tmp_path / "absent.sh"))], cwd=str(tmp_path))
    assert not v.passed


# --- determinism ------------------------------------------------------------


def test_verdict_is_deterministic() -> None:
    checks = [
        Check("preserves", "numbers"),
        Check("forbid", r"\bTODO\b"),
        Check("max_edit_ratio", 0.5),
    ]
    args = {"source": "ship 3 cells", "output": "3 cells shipped"}
    first = _verdict(checks, **args)
    second = _verdict(checks, **args)
    assert first == second


def test_check_results_are_ordered_as_declared() -> None:
    v = _verdict(
        [Check("require", "a"), Check("forbid", "b"), Check("max_edit_ratio", 1.0)],
        source="a",
        output="a",
    )
    assert [c.name for c in v.checks] == ["require", "forbid", "max_edit_ratio"]


def test_check_result_is_hashable_and_frozen() -> None:
    result = CheckResult(name="require", passed=True, detail="")
    assert hash(result) is not None
