"""Cell manifest parsing and validation.

A Cell manifest declares one mono-scoped workspace. This module loads and
validates it; it does not execute anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

API_VERSION = "skillcell.dev/v1alpha1"
RUNTIMES = ("local", "container")
PLANES = ("offline", "frontier", "system", "byok")


class ManifestError(ValueError):
    """Raised when a manifest is malformed or violates the schema."""


@dataclass(frozen=True)
class Decode:
    temperature: float = 0.0
    seed: int = 0


@dataclass(frozen=True)
class ModelSpec:
    plane: str
    base: str
    decode: Decode = field(default_factory=Decode)
    endpoint: str | None = None  # system plane
    provider: str | None = None  # byok plane
    base_url: str | None = None  # byok plane
    adapter: str | None = None


@dataclass(frozen=True)
class Cell:
    name: str
    scope: str
    runtime: str
    inputs: tuple[dict[str, Any], ...]
    outputs: tuple[dict[str, Any], ...]
    model: ModelSpec | None = None
    tools: tuple[str, ...] = ()
    network: str = "deny"


@dataclass(frozen=True)
class ChainNode:
    cell: str
    alias: str
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChainEdge:
    source: str
    target: str


@dataclass(frozen=True)
class Chain:
    name: str
    nodes: tuple[ChainNode, ...]
    edges: tuple[ChainEdge, ...]


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise ManifestError(f"missing required field '{key}' in {where}")
    return mapping[key]


def _parse_model(raw: dict[str, Any]) -> ModelSpec:
    plane = raw.get("plane", "offline")
    if plane not in PLANES:
        raise ManifestError(f"invalid model plane '{plane}'; expected one of {PLANES}")
    dec_raw = raw.get("decode", {}) or {}
    decode = Decode(
        temperature=float(dec_raw.get("temperature", 0.0)),
        seed=int(dec_raw.get("seed", 0)),
    )
    return ModelSpec(
        plane=plane,
        base=str(raw.get("base", "")),
        decode=decode,
        endpoint=raw.get("endpoint"),
        provider=raw.get("provider"),
        base_url=raw.get("base_url"),
        adapter=raw.get("adapter"),
    )


def load_cell(path: str | Path) -> Cell:
    text = Path(path).read_text()
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough
        raise ManifestError(f"invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ManifestError("manifest must be a mapping")

    kind = doc.get("kind")
    if kind != "Cell":
        raise ManifestError(f"unexpected kind '{kind}'; expected 'Cell'")

    metadata = doc.get("metadata") or {}
    name = _require(metadata, "name", "metadata")

    spec = doc.get("spec") or {}
    scope = _require(spec, "scope", "spec")
    runtime = _require(spec, "runtime", "spec")
    if runtime not in RUNTIMES:
        raise ManifestError(f"invalid runtime '{runtime}'; expected one of {RUNTIMES}")

    contract = spec.get("contract") or {}
    inputs = tuple(contract.get("inputs") or ())
    outputs = tuple(contract.get("outputs") or ())

    model = None
    if spec.get("model"):
        model = _parse_model(spec["model"])

    return Cell(
        name=str(name),
        scope=str(scope),
        runtime=str(runtime),
        inputs=inputs,
        outputs=outputs,
        model=model,
        tools=tuple(spec.get("tools") or ()),
        network=str(spec.get("network", "deny")),
    )


def _extract_alias_refs(obj: Any) -> set[str]:
    """Extract all ${alias.outputs.field} alias names from a nested structure."""
    aliases: set[str] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            aliases.update(_extract_alias_refs(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            aliases.update(_extract_alias_refs(v))
    elif isinstance(obj, str):
        matches = re.findall(r"\$\{([^.]+)\.", obj)
        aliases.update(matches)
    return aliases


def _parse_nodes(nodes_raw: Any) -> tuple[list[ChainNode], set[str]]:
    """Parse nodes and return (nodes list, declared aliases set). Validates refs."""
    if not nodes_raw:
        raise ManifestError("spec.nodes is required and must be non-empty")
    nodes: list[ChainNode] = []
    declared_aliases: set[str] = set()
    for node_raw in nodes_raw:
        if not isinstance(node_raw, dict):
            raise ManifestError("each node must be a mapping")
        cell = _require(node_raw, "cell", "node")
        alias = _require(node_raw, "as", "node")
        alias_str = str(alias)
        if alias_str in declared_aliases:
            raise ManifestError(f"duplicate alias '{alias_str}'")
        inputs = node_raw.get("inputs") or {}
        nodes.append(ChainNode(cell=str(cell), alias=alias_str, inputs=inputs))
        declared_aliases.add(alias_str)
        # Validate input refs
        refs = _extract_alias_refs(inputs)
        for ref in refs:
            if ref not in declared_aliases:
                raise ManifestError(f"undeclared alias '{ref}' in node {alias_str} input")
    return nodes, declared_aliases


def _parse_edges(edges_raw: Any, declared_aliases: set[str]) -> list[ChainEdge]:
    """Parse edges and validate against declared aliases."""
    edges: list[ChainEdge] = []
    for edge_raw in edges_raw or []:
        if not isinstance(edge_raw, dict):
            raise ManifestError("each edge must be a mapping")
        source = _require(edge_raw, "from", "edge")
        target = _require(edge_raw, "to", "edge")
        source_str = str(source)
        target_str = str(target)
        if source_str not in declared_aliases:
            raise ManifestError(f"undeclared alias '{source_str}' in edge")
        if target_str not in declared_aliases:
            raise ManifestError(f"undeclared alias '{target_str}' in edge")
        edges.append(ChainEdge(source=source_str, target=target_str))
    return edges


def load_chain(path: str | Path) -> Chain:
    text = Path(path).read_text()
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough
        raise ManifestError(f"invalid YAML: {exc}") from exc
    if not docs or not isinstance(docs[0], dict):
        raise ManifestError("manifest must be a mapping")
    doc = docs[0]

    kind = doc.get("kind")
    if kind != "Chain":
        raise ManifestError(f"unexpected kind '{kind}'; expected 'Chain'")

    metadata = doc.get("metadata") or {}
    name = _require(metadata, "name", "metadata")

    spec = doc.get("spec") or {}
    nodes_list, declared_aliases = _parse_nodes(spec.get("nodes"))
    edges_list = _parse_edges(spec.get("edges"), declared_aliases)

    return Chain(name=str(name), nodes=tuple(nodes_list), edges=tuple(edges_list))
