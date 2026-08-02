"""Container runtime: pure argv construction + injectable runner, no daemon needed."""

from pathlib import Path

import pytest

from skillcell.container import (
    ContainerError,
    build_command,
    run_command,
    run_in_container,
)
from skillcell.manifest import load_cell

EXAMPLES = Path(__file__).parent.parent / "examples"


def _cell(tmp_path, *, network="deny", image=None, dockerfile=None):
    dc_dir = tmp_path / ".devcontainer"
    dc_dir.mkdir(exist_ok=True)
    if image is not None:
        dc_dir.joinpath("devcontainer.json").write_text(f'{{"image": "{image}"}}')
    else:
        df = dockerfile or "Dockerfile"
        dc_dir.joinpath("devcontainer.json").write_text(f'{{"build": {{"dockerfile": "{df}"}}}}')
    manifest = tmp_path / "cell.yaml"
    manifest.write_text(
        f"""\
apiVersion: skillcell.dev/v1alpha1
kind: Cell
metadata: {{name: demo}}
spec:
  scope: demo scope
  runtime: container
  container:
    devcontainer: ./.devcontainer/devcontainer.json
  network: {network}
"""
    )
    return load_cell(manifest)


def test_manifest_parses_container_devcontainer_path(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim")
    assert cell.container is not None
    assert cell.container.devcontainer == "./.devcontainer/devcontainer.json"


def test_example_cell_container_block_parsed():
    cell = load_cell(EXAMPLES / "cell.yaml")
    assert cell.container is not None
    assert cell.container.devcontainer.endswith("devcontainer.json")


def test_build_command_none_for_prebuilt_image(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim")
    assert build_command(cell, cell_dir=tmp_path) is None


def test_build_command_for_dockerfile(tmp_path):
    cell = _cell(tmp_path, dockerfile="Dockerfile")
    cmd = build_command(cell, cell_dir=tmp_path)
    assert cmd is not None
    assert cmd[:2] == ["docker", "build"]
    assert "skillcell/demo:latest" in cmd
    assert str(tmp_path) in cmd


def test_run_command_network_deny_maps_to_none(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim", network="deny")
    cmd = run_command(cell, cell_dir=tmp_path, goal="do the thing")
    assert cmd[:2] == ["docker", "run"]
    assert "--network=none" in cmd
    assert "--rm" in cmd
    assert "python:3.12-slim" in cmd


def test_run_command_network_open_uses_default_bridge(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim", network="open")
    cmd = run_command(cell, cell_dir=tmp_path, goal="g")
    assert "--network=none" not in cmd


def test_run_command_allowlist_is_conservative_none(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim", network="allowlist")
    assert "--network=none" in run_command(cell, cell_dir=tmp_path, goal="g")


def test_run_command_mounts_cell_dir_at_workdir(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim")
    cmd = run_command(cell, cell_dir=tmp_path, goal="g")
    assert f"{tmp_path}:/cell" in " ".join(cmd)
    assert "--workdir=/cell" in cmd


def test_run_command_is_deterministic(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim")
    a = run_command(cell, cell_dir=tmp_path, goal="same goal")
    b = run_command(cell, cell_dir=tmp_path, goal="same goal")
    assert a == b


def test_run_in_container_invokes_build_then_run(tmp_path):
    cell = _cell(tmp_path, dockerfile="Dockerfile")
    calls = []

    def fake_runner(argv):
        calls.append(argv)
        return 0, "ok"

    code, output = run_in_container(
        cell, cell_dir=tmp_path, goal="g", runner=fake_runner, docker_path="docker"
    )
    assert code == 0
    assert len(calls) == 2
    assert calls[0][:2] == ["docker", "build"]
    assert calls[1][:2] == ["docker", "run"]


def test_run_in_container_skips_build_for_prebuilt(tmp_path):
    cell = _cell(tmp_path, image="python:3.12-slim")
    calls = []

    def fake_runner(argv):
        calls.append(argv)
        return 0, "ok"

    run_in_container(cell, cell_dir=tmp_path, goal="g", runner=fake_runner, docker_path="docker")
    assert len(calls) == 1
    assert calls[0][:2] == ["docker", "run"]


def test_run_in_container_without_docker_raises(tmp_path, monkeypatch):
    import skillcell.container as container_mod

    monkeypatch.setattr(container_mod.shutil, "which", lambda _: None)
    cell = _cell(tmp_path, image="python:3.12-slim")
    with pytest.raises(ContainerError, match="docker"):
        run_in_container(cell, cell_dir=tmp_path, goal="g", runner=None, docker_path=None)


def test_local_cell_without_container_block_raises(tmp_path):
    manifest = tmp_path / "local.yaml"
    manifest.write_text(
        "apiVersion: skillcell.dev/v1alpha1\nkind: Cell\n"
        "metadata: {name: loc}\nspec: {scope: s, runtime: local}\n"
    )
    cell = load_cell(manifest)
    with pytest.raises(ContainerError, match="container"):
        run_in_container(cell, cell_dir=tmp_path, goal="g", runner=lambda a: (0, ""),
                         docker_path="docker")
