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


def _container_cell(tmp_path):
    dc = tmp_path / ".devcontainer"
    dc.mkdir()
    dc.joinpath("devcontainer.json").write_text('{"image": "python:3.12-slim"}')
    manifest = tmp_path / "cell.yaml"
    manifest.write_text(
        "apiVersion: skillcell.dev/v1alpha1\nkind: Cell\n"
        "metadata: {name: boxed}\n"
        "spec:\n  scope: boxed scope\n  runtime: container\n"
        "  container: {devcontainer: ./.devcontainer/devcontainer.json}\n"
    )
    return manifest


def test_run_container_cell_without_docker_exits_3(tmp_path, capsys, monkeypatch):
    import skillcell.container as container_mod

    monkeypatch.setattr(container_mod.shutil, "which", lambda _: None)
    manifest = _container_cell(tmp_path)
    code = main(["run", str(manifest), "--goal", "g", "--act", "--authorized"])
    captured = capsys.readouterr()
    assert code == 3
    assert "docker" in captured.err


def test_run_container_cell_with_docker_reports_output_json(tmp_path, capsys, monkeypatch):
    import subprocess

    import skillcell.container as container_mod

    monkeypatch.setattr(container_mod.shutil, "which", lambda _: "/usr/bin/docker")

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="container says hi\n", stderr="")

    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    manifest = _container_cell(tmp_path)
    code = main(["run", str(manifest), "--goal", "g", "--act", "--authorized", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["cell"] == "boxed"
    assert payload["runtime"] == "container"
    assert payload["exit_code"] == 0
    assert "container says hi" in payload["output"]


def test_run_container_cell_docker_failure_exits_1(tmp_path, capsys, monkeypatch):
    import subprocess

    import skillcell.container as container_mod

    monkeypatch.setattr(container_mod.shutil, "which", lambda _: "/usr/bin/docker")

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 125, stdout="", stderr="boom\n")

    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    manifest = _container_cell(tmp_path)
    code = main(["run", str(manifest), "--goal", "g", "--act", "--authorized"])
    captured = capsys.readouterr()
    assert code == 1
    assert "exit_code=125" in captured.out


def test_run_container_without_act_is_dry_run_no_docker(tmp_path, capsys, monkeypatch):
    import skillcell.container as container_mod

    monkeypatch.setattr(container_mod.shutil, "which", lambda _: "/usr/bin/docker")
    calls = []

    def fake_run(argv, **kwargs):  # any call = the gate failed
        calls.append(argv)
        raise AssertionError("docker must not run without --act --authorized")

    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    manifest = _container_cell(tmp_path)
    code = main(["run", str(manifest), "--goal", "g"])
    captured = capsys.readouterr()
    assert code == 0
    assert calls == []
    assert "act=skipped" in captured.out
    assert "docker run" in captured.out  # planned argv shown, not executed


def test_run_container_act_without_authorization_is_blocked(tmp_path, capsys, monkeypatch):
    import skillcell.container as container_mod

    monkeypatch.setattr(container_mod.shutil, "which", lambda _: "/usr/bin/docker")

    def fake_run(argv, **kwargs):
        raise AssertionError("docker must not run unauthorized")

    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    manifest = _container_cell(tmp_path)
    code = main(["run", str(manifest), "--goal", "g", "--act"])
    captured = capsys.readouterr()
    assert code == 0
    assert "act=blocked" in captured.out
