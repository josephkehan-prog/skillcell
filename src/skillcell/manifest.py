"""Cell manifest parsing and validation.

A Cell manifest declares one mono-scoped workspace. This module loads and
validates it; it does not execute anything.
"""

from __future__ import annotations

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
