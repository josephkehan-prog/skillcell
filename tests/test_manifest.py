import textwrap

import pytest

from skillcell.manifest import Cell, ManifestError, load_cell


def _write(tmp_path, body: str):
    p = tmp_path / "cell.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_load_minimal_cell(tmp_path):
    p = _write(
        tmp_path,
        """
        apiVersion: skillcell.dev/v1alpha1
        kind: Cell
        metadata:
          name: firmware-triage
        spec:
          scope: triage firmware
          runtime: local
          contract:
            inputs: []
            outputs: []
        """,
    )
    cell = load_cell(p)
    assert isinstance(cell, Cell)
    assert cell.name == "firmware-triage"
    assert cell.runtime == "local"
    assert cell.scope == "triage firmware"


def test_wrong_kind_rejected(tmp_path):
    p = _write(
        tmp_path,
        """
        apiVersion: skillcell.dev/v1alpha1
        kind: Chain
        metadata: {name: x}
        spec: {scope: s, runtime: local, contract: {inputs: [], outputs: []}}
        """,
    )
    with pytest.raises(ManifestError, match="kind"):
        load_cell(p)


def test_invalid_runtime_rejected(tmp_path):
    p = _write(
        tmp_path,
        """
        apiVersion: skillcell.dev/v1alpha1
        kind: Cell
        metadata: {name: x}
        spec: {scope: s, runtime: martian, contract: {inputs: [], outputs: []}}
        """,
    )
    with pytest.raises(ManifestError, match="runtime"):
        load_cell(p)


def test_missing_name_rejected(tmp_path):
    p = _write(
        tmp_path,
        """
        apiVersion: skillcell.dev/v1alpha1
        kind: Cell
        metadata: {}
        spec: {scope: s, runtime: local, contract: {inputs: [], outputs: []}}
        """,
    )
    with pytest.raises(ManifestError, match="name"):
        load_cell(p)


def test_model_defaults_to_offline_when_absent(tmp_path):
    p = _write(
        tmp_path,
        """
        apiVersion: skillcell.dev/v1alpha1
        kind: Cell
        metadata: {name: x}
        spec: {scope: s, runtime: local, contract: {inputs: [], outputs: []}}
        """,
    )
    cell = load_cell(p)
    assert cell.model is None


def test_model_parsed(tmp_path):
    p = _write(
        tmp_path,
        """
        apiVersion: skillcell.dev/v1alpha1
        kind: Cell
        metadata: {name: x}
        spec:
          scope: s
          runtime: local
          contract: {inputs: [], outputs: []}
          model:
            plane: frontier
            base: claude-fable-5
            decode: {temperature: 0.0, seed: 1}
        """,
    )
    cell = load_cell(p)
    assert cell.model is not None
    assert cell.model.plane == "frontier"
    assert cell.model.decode.temperature == 0.0
    assert cell.model.decode.seed == 1
