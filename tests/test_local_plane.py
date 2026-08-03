"""The local plane: small models on this machine, no key, no network egress.

This is the only plane where bit-reproducibility is available (single-tenant,
batch size 1), so it is the canonical one — the others are fallbacks.
"""

from __future__ import annotations

import pytest

from skillcell.manifest import Decode, ModelSpec
from skillcell.model import (
    DEFAULT_LOCAL_ENDPOINT,
    BackendError,
    LocalBackend,
    SystemNativeBackend,
    resolve_backend,
)


class _Recorder:
    def __init__(self, text: str = "ok") -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, prompt: str, params: dict[str, object]) -> str:
        self.calls.append({"prompt": prompt, "params": params})
        return self.text

    @property
    def last(self) -> dict[str, object]:
        return self.calls[-1]


def _decode(temperature: float = 0.0) -> Decode:
    return Decode(temperature=temperature, seed=7)


def test_local_backend_needs_no_key() -> None:
    be = LocalBackend(base="qwen2.5-7b", decode=_decode(), endpoint="http://127.0.0.1:11434/v1")
    assert be.complete("hi") is not None


def test_local_backend_forwards_the_adapter_id() -> None:
    """The serving layer hot-swaps per dispatch; the cell names the adapter."""
    rec = _Recorder()
    be = LocalBackend(
        base="qwen2.5-7b-instruct",
        decode=_decode(),
        endpoint="http://127.0.0.1:11434/v1",
        adapter="wordsmith@v3",
        transport=rec,
    )
    be.complete("hi")
    assert rec.last["params"]["adapter"] == "wordsmith@v3"  # type: ignore[index]


def test_local_backend_serves_at_the_pinned_temperature() -> None:
    rec = _Recorder()
    be = LocalBackend(base="q", decode=_decode(), endpoint="e", transport=rec)
    be.complete("hi")
    assert rec.last["params"]["temperature"] == 0.0  # type: ignore[index]


def test_temperature_override_enables_hot_sampling_for_data_generation() -> None:
    """Temperature 0 is a *serving* invariant, not a training one: rejection
    sampling needs diverse attempts, then the adapter is served cold."""
    rec = _Recorder()
    be = LocalBackend(base="q", decode=_decode(), endpoint="e", transport=rec)
    be.complete("hi", temperature=1.0)
    assert rec.last["params"]["temperature"] == 1.0  # type: ignore[index]
    be.complete("hi")
    assert rec.last["params"]["temperature"] == 0.0  # type: ignore[index]


def test_local_backend_requires_an_endpoint() -> None:
    with pytest.raises(BackendError, match="endpoint"):
        LocalBackend(base="q", decode=_decode(), endpoint="")


def test_system_plane_is_an_alias_for_local() -> None:
    assert SystemNativeBackend is LocalBackend


def test_resolve_local_plane_needs_no_key() -> None:
    spec = ModelSpec(plane="local", base="qwen2.5-7b", decode=_decode(), endpoint="http://x")
    assert isinstance(resolve_backend(spec, env={}, transport=_Recorder()), LocalBackend)


def test_resolve_local_falls_back_to_the_default_endpoint() -> None:
    rec = _Recorder()
    spec = ModelSpec(plane="local", base="qwen2.5-7b-instruct", decode=_decode())
    be = resolve_backend(spec, env={}, transport=rec)
    assert be is not None
    be.complete("hi")
    assert rec.last["params"]["endpoint"] == DEFAULT_LOCAL_ENDPOINT  # type: ignore[index]


def test_resolve_local_reads_the_endpoint_from_env() -> None:
    rec = _Recorder()
    spec = ModelSpec(plane="local", base="q", decode=_decode())
    env = {"SKILLCELL_LOCAL_ENDPOINT": "http://box:8000/v1"}
    be = resolve_backend(spec, env=env, transport=rec)
    assert be is not None
    be.complete("hi")
    assert rec.last["params"]["endpoint"] == "http://box:8000/v1"  # type: ignore[index]


def test_resolve_local_passes_the_adapter_through() -> None:
    rec = _Recorder()
    spec = ModelSpec(plane="local", base="q", decode=_decode(), adapter="wordsmith@v1")
    be = resolve_backend(spec, env={}, transport=rec)
    assert be is not None
    be.complete("hi")
    assert rec.last["params"]["adapter"] == "wordsmith@v1"  # type: ignore[index]


def test_local_plane_never_reads_an_api_key() -> None:
    """Offline-first: a key in the environment must not change local behaviour."""
    rec = _Recorder()
    spec = ModelSpec(plane="local", base="q", decode=_decode())
    be = resolve_backend(spec, env={"ANTHROPIC_API_KEY": "sk-should-be-ignored"}, transport=rec)
    assert be is not None
    be.complete("hi")
    assert "api_key" not in rec.last["params"]  # type: ignore[operator]
