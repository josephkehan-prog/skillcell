import json
import textwrap

from skillcell.cli import main


def _cell(tmp_path):
    p = tmp_path / "cell.yaml"
    p.write_text(
        textwrap.dedent(
            """
            apiVersion: skillcell.dev/v1alpha1
            kind: Cell
            metadata: {name: firmware-triage}
            spec:
              scope: triage firmware
              runtime: local
              contract: {inputs: [], outputs: []}
            """
        )
    )
    return p


def test_doctor_reports_ready(capsys):
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "STATUS=ready" in out


def test_run_offline_json(tmp_path, capsys):
    p = _cell(tmp_path)
    rc = main(["run", str(p), "--goal", "triage firmware", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["route"] == "firmware-pentest"
    assert payload["executed"] is False


def test_run_unknown_cell_errors(tmp_path, capsys):
    rc = main(["run", str(tmp_path / "missing.yaml"), "--goal", "x"])
    assert rc != 0
