"""The composable cell verifier — the gate a cell must pass to report done.

The gate does three jobs with one artifact:

1. **Runtime guarantee.** The loop retries until the gate passes, so "completes
   the task every time" is an inference-time property, not a weights property.
2. **Training filter.** Only gate-passing attempts become adapter training
   data, which makes rejection sampling possible without a frontier teacher.
3. **Reward signal.** The same pass/fail is what an RL pass would optimize.

Every check is offline, deterministic, and model-free: a check is a pure
function of (source, output) or a subprocess exit code. Nothing here reaches
the network, and no check needs a second model to adjudicate it.

Checks are declared in the manifest under ``spec.contract.eval.checks``:

    checks:
      - command: ./eval/lint.sh     # exit 0 to pass
      - preserves: numbers          # every figure in the input survives
      - preserves: negations        # negation count is unchanged
      - forbid: '\\bTODO\\b'
      - require: '^## Summary'
      - maxEditRatio: 0.5           # reject a from-scratch rewrite
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .evalgate import run_gate

CHECK_KINDS = ("command", "preserves", "require", "forbid", "max_edit_ratio")

# Preservation classes. Each is a high-precision regex, deliberately not NER:
# a heuristic guard that is right when it fires, not a semantic model.
_PRESERVE_PATTERNS: dict[str, str] = {
    "numbers": r"\d+(?:\.\d+)?",
    "urls": r"https?://[^\s)>\]]+",
    "emails": r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}",
    "acronyms": r"\b[A-Z]{2,}\b",
}

# Counted rather than matched: a rewrite may reword a negation, but dropping or
# adding one changes the meaning. This is the drift determinism would otherwise
# reproduce identically, forever, behind a green gate.
_NEGATION_RE = re.compile(
    r"\b(?:cannot|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't"
    r"|shouldn't|wouldn't|couldn't|hasn't|haven't|hadn't|not|never|no|none"
    r"|neither|nor|without)\b",
    re.IGNORECASE,
)

PRESERVE_CLASSES = (*_PRESERVE_PATTERNS, "negations")


class VerifyError(ValueError):
    """Raised when a check is malformed — a manifest bug, not a run failure."""


@dataclass(frozen=True)
class Check:
    """One declared check. ``value`` is a pattern, class name, or threshold."""

    kind: str
    value: str | float


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Verdict:
    passed: bool
    checks: tuple[CheckResult, ...] = ()

    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def reason(self) -> str:
        """One-line summary of why the gate failed (empty when it passed)."""
        return "; ".join(f"{c.name}: {c.detail}" for c in self.failures())


def _compile(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        raise VerifyError(f"invalid regex {pattern!r}: {exc}") from exc


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def edit_ratio(source: str, output: str) -> float:
    """Token-level dissimilarity in [0, 1]. 0.0 = identical, 1.0 = disjoint.

    ``autojunk`` is off: its popular-element heuristic makes the score depend
    on input length, and this number feeds a gate that must be reproducible.
    """
    matcher = SequenceMatcher(None, _tokens(source), _tokens(output), autojunk=False)
    return round(1.0 - matcher.ratio(), 12)


def _check_preserves(klass: str, source: str, output: str) -> CheckResult:
    if klass == "negations":
        before = len(_NEGATION_RE.findall(source))
        after = len(_NEGATION_RE.findall(output))
        ok = before == after
        detail = "" if ok else f"negation count changed: {before} -> {after}"
        return CheckResult("preserves", ok, detail)

    pattern = _PRESERVE_PATTERNS.get(klass)
    if pattern is None:
        raise VerifyError(f"unknown preserve class {klass!r}; expected one of {PRESERVE_CLASSES}")

    required = re.findall(pattern, source)
    present = set(re.findall(pattern, output))
    missing = [tok for tok in dict.fromkeys(required) if tok not in present]
    if missing:
        return CheckResult("preserves", False, f"{klass} dropped: {', '.join(missing)}")
    return CheckResult("preserves", True)


def _check_edit_ratio(limit: float, source: str, output: str) -> CheckResult:
    ratio = edit_ratio(source, output)
    ok = ratio <= limit
    detail = "" if ok else f"rewrote {ratio:.2f} of the input (limit {limit:.2f})"
    return CheckResult("max_edit_ratio", ok, detail)


def _check_command(script: str, cwd: str, timeout: int) -> CheckResult:
    result = run_gate(script, cwd=cwd, timeout=timeout)
    detail = "" if result.passed else f"exit {result.exit_code}: {result.output.strip()[:400]}"
    return CheckResult("command", result.passed, detail)


def validate_check(check: Check) -> None:
    """Raise VerifyError if a check is malformed.

    Called at manifest-parse time so ``skillcell validate`` catches a broken
    gate, rather than the run that depends on it discovering it mid-flight.
    """
    if check.kind == "preserves" and str(check.value) not in PRESERVE_CLASSES:
        raise VerifyError(
            f"unknown preserve class {str(check.value)!r}; expected one of {PRESERVE_CLASSES}"
        )
    if check.kind in ("require", "forbid"):
        _compile(str(check.value))
    if check.kind not in CHECK_KINDS:
        raise VerifyError(f"unknown check kind {check.kind!r}; expected one of {CHECK_KINDS}")


def run_check(
    check: Check,
    *,
    source: str,
    output: str,
    cwd: str,
    timeout: int = 600,
) -> CheckResult:
    """Evaluate one check. Raises VerifyError only for a malformed check."""
    if check.kind == "command":
        return _check_command(str(check.value), cwd, timeout)

    if check.kind == "preserves":
        return _check_preserves(str(check.value), source, output)

    if check.kind == "max_edit_ratio":
        return _check_edit_ratio(float(check.value), source, output)

    if check.kind == "require":
        pattern = _compile(str(check.value))
        ok = pattern.search(output) is not None
        return CheckResult("require", ok, "" if ok else f"pattern not found: {check.value}")

    if check.kind == "forbid":
        pattern = _compile(str(check.value))
        ok = pattern.search(output) is None
        return CheckResult("forbid", ok, "" if ok else f"forbidden pattern present: {check.value}")

    raise VerifyError(f"unknown check kind {check.kind!r}; expected one of {CHECK_KINDS}")


def run_checks(
    checks: tuple[Check, ...],
    *,
    source: str = "",
    output: str = "",
    cwd: str = ".",
    timeout: int = 600,
) -> Verdict:
    """Run every check in declaration order and aggregate one verdict.

    Order-stable and side-effect free apart from ``command`` checks, so the
    same (checks, source, output) always yields the same Verdict.
    """
    results = tuple(
        run_check(check, source=source, output=output, cwd=cwd, timeout=timeout)
        for check in checks
    )
    return Verdict(passed=all(r.passed for r in results), checks=results)
