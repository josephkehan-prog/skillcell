import textwrap

from skillcell.evalgate import EvalResult, run_gate


def _script(tmp_path, body: str, name="gate.sh"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    p.chmod(0o755)
    return p


def test_gate_passes_on_zero_exit(tmp_path):
    g = _script(tmp_path, "#!/bin/sh\nexit 0\n")
    res = run_gate(str(g), cwd=str(tmp_path))
    assert isinstance(res, EvalResult)
    assert res.passed is True
    assert res.exit_code == 0


def test_gate_fails_on_nonzero_exit(tmp_path):
    g = _script(tmp_path, "#!/bin/sh\necho boom 1>&2\nexit 3\n")
    res = run_gate(str(g), cwd=str(tmp_path))
    assert res.passed is False
    assert res.exit_code == 3
    assert "boom" in res.output


def test_gate_missing_script_fails_gracefully(tmp_path):
    res = run_gate(str(tmp_path / "nope.sh"), cwd=str(tmp_path))
    assert res.passed is False
    assert res.exit_code != 0
