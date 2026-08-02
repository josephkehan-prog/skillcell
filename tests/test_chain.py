import pytest

from skillcell.cli import main
from skillcell.manifest import ManifestError, load_chain


def test_load_chain_parses_chain_yaml():
    chain = load_chain("examples/chain.yaml")
    assert chain.name == "firmware-audit-report"
    assert len(chain.nodes) == 3
    assert chain.nodes[0].alias == "triage"
    assert chain.nodes[1].alias == "correlate"
    assert chain.nodes[2].alias == "writer"
    assert len(chain.edges) == 2
    assert chain.edges[0].source == "triage"
    assert chain.edges[0].target == "correlate"


def test_load_chain_parses_refactor_audit_chain_yaml():
    chain = load_chain("examples/refactor-audit-chain.yaml")
    assert chain.name == "refactor-then-audit"
    assert len(chain.nodes) == 2
    assert chain.nodes[0].alias == "surgeon"
    assert chain.nodes[1].alias == "auditor"
    assert len(chain.edges) == 1
    assert chain.edges[0].source == "surgeon"
    assert chain.edges[0].target == "auditor"


def test_load_chain_unknown_kind_raises():
    with pytest.raises(ManifestError, match="unexpected kind"):
        load_chain("examples/cell.yaml")


def test_load_chain_edge_to_undeclared_alias_raises():
    import tempfile
    from pathlib import Path

    yaml_content = """apiVersion: skillcell.dev/v1alpha1
kind: Chain
metadata:
  name: bad-chain
spec:
  nodes:
    - cell: foo
      as: foo_node
  edges:
    - from: foo_node
      to: undefined_node
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            with pytest.raises(ManifestError, match="undeclared"):
                load_chain(f.name)
        finally:
            Path(f.name).unlink()


def test_load_chain_input_ref_undeclared_alias_raises():
    import tempfile
    from pathlib import Path

    yaml_content = """apiVersion: skillcell.dev/v1alpha1
kind: Chain
metadata:
  name: bad-chain
spec:
  nodes:
    - cell: foo
      as: foo_node
      inputs:
        data: ${undefined.outputs.result}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            with pytest.raises(ManifestError, match="undeclared"):
                load_chain(f.name)
        finally:
            Path(f.name).unlink()


def test_cli_validate_chain_exits_zero(capsys):
    exit_code = main(["validate", "examples/chain.yaml"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "VALID kind=Chain" in captured.out
    assert "firmware-audit-report" in captured.out


def test_cli_validate_cell_exits_zero(capsys):
    exit_code = main(["validate", "examples/cell.yaml"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "VALID kind=Cell" in captured.out


def test_cli_validate_bogus_kind_exits_two(capsys):
    import tempfile
    from pathlib import Path

    yaml_content = """apiVersion: skillcell.dev/v1alpha1
kind: Unknown
metadata:
  name: bad
spec: {}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            exit_code = main(["validate", f.name])
            assert exit_code == 2
            captured = capsys.readouterr()
            assert "error:" in captured.err
        finally:
            Path(f.name).unlink()


def test_load_chain_duplicate_alias_raises():
    import tempfile
    from pathlib import Path

    yaml_content = """apiVersion: skillcell.dev/v1alpha1
kind: Chain
metadata:
  name: bad-chain
spec:
  nodes:
    - cell: foo
      as: dup
    - cell: bar
      as: dup
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            with pytest.raises(ManifestError, match="duplicate"):
                load_chain(f.name)
        finally:
            Path(f.name).unlink()


def test_cli_validate_cell_missing_name_reports_actual_error(capsys):
    import tempfile
    from pathlib import Path

    yaml_content = """apiVersion: skillcell.dev/v1alpha1
kind: Cell
metadata: {}
spec:
  scope: test
  runtime: local
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            exit_code = main(["validate", f.name])
            assert exit_code == 2
            captured = capsys.readouterr()
            assert "error:" in captured.err
            assert "name" in captured.err.lower()
        finally:
            Path(f.name).unlink()
