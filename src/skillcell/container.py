"""Container runtime (phase 1): build and run a cell as an OCI container.

Pure argv construction plus an injectable runner, mirroring the transport
seam in ``model.py``: tests assert exact ``docker`` command lines without a
daemon, and the real subprocess runner attaches only at the CLI edge.

Hermetic mapping is conservative by design: ``network: deny`` and
``network: allowlist`` both become ``--network=none`` (allowlist enforcement
is not implemented yet, so it must not silently open the network); only an
explicit ``network: open`` gets the default bridge.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - runs the local docker CLI with a fixed argv
from collections.abc import Callable
from pathlib import Path

from .manifest import Cell

# A runner executes an argv and returns (exit_code, combined_output).
Runner = Callable[[list[str]], tuple[int, str]]


class ContainerError(RuntimeError):
    """Raised when a cell cannot be built or run as a container."""


def _devcontainer(cell: Cell, cell_dir: Path) -> tuple[Path, dict[str, object]]:
    if cell.container is None:
        raise ContainerError("cell declares no container block (runtime: container required)")
    dc_path = (cell_dir / cell.container.devcontainer).resolve()
    try:
        spec = json.loads(dc_path.read_text())
    except FileNotFoundError as exc:
        raise ContainerError(f"devcontainer spec not found: {dc_path}") from exc
    except json.JSONDecodeError as exc:
        raise ContainerError(f"invalid devcontainer JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise ContainerError("devcontainer spec must be a JSON object")
    return dc_path, spec


def _image_tag(cell: Cell) -> str:
    return f"skillcell/{cell.name}:latest"


def image_for(cell: Cell, cell_dir: str | Path) -> str:
    """The image a cell runs as: prebuilt devcontainer image, or the built tag."""
    _, spec = _devcontainer(cell, Path(cell_dir))
    image = spec.get("image")
    if isinstance(image, str) and image:
        return image
    return _image_tag(cell)


def build_command(cell: Cell, *, cell_dir: str | Path) -> list[str] | None:
    """The ``docker build`` argv for a cell, or None when a prebuilt image is declared."""
    dc_path, spec = _devcontainer(cell, Path(cell_dir))
    image = spec.get("image")
    if isinstance(image, str) and image:
        return None
    build = spec.get("build")
    dockerfile = "Dockerfile"
    if isinstance(build, dict) and isinstance(build.get("dockerfile"), str):
        dockerfile = str(build["dockerfile"])
    dockerfile_path = (dc_path.parent / dockerfile).resolve()
    return [
        "docker",
        "build",
        "-t",
        _image_tag(cell),
        "-f",
        str(dockerfile_path),
        str(Path(cell_dir)),
    ]


def run_command(cell: Cell, *, cell_dir: str | Path, goal: str) -> list[str]:
    """The ``docker run`` argv for one cell dispatch. Deterministic for equal inputs."""
    cmd = ["docker", "run", "--rm"]
    if cell.network != "open":
        cmd.append("--network=none")
    cmd += [
        "-v",
        f"{Path(cell_dir)}:/cell",
        "--workdir=/cell",
        image_for(cell, cell_dir),
        goal,
    ]
    return cmd


def _subprocess_runner(argv: list[str]) -> tuple[int, str]:  # pragma: no cover - CLI edge
    proc = subprocess.run(  # noqa: S603  # nosec B603 - fixed docker argv, shell=False
        argv, capture_output=True, text=True, check=False
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_in_container(
    cell: Cell,
    *,
    cell_dir: str | Path,
    goal: str,
    runner: Runner | None = None,
    docker_path: str | None = None,
) -> tuple[int, str]:
    """Build (if needed) and run a cell's container. Returns (exit_code, output)."""
    if docker_path is None:
        docker_path = shutil.which("docker")
    if docker_path is None:
        raise ContainerError("docker not found on PATH; install Docker to use runtime: container")
    active_runner = runner or _subprocess_runner

    build = build_command(cell, cell_dir=cell_dir)
    if build is not None:
        code, output = active_runner(build)
        if code != 0:
            return code, output

    return active_runner(run_command(cell, cell_dir=cell_dir, goal=goal))
