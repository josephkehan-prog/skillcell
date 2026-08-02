import pytest

from skillcell.manifest import Decode, ModelSpec
from skillcell.model import (
    BackendError,
    BYOKBackend,
    FrontierBackend,
    SystemNativeBackend,
    resolve_backend,
)


class _Recorder:
    """Injectable transport stand-in; records the request, returns canned text."""

    def __init__(self, text="ok"):
        self.text = text
        self.last = None

    def __call__(self, *, prompt, params):
        self.last = {"prompt": prompt, "params": params}
        return self.text


def _decode():
    return Decode(temperature=0.0, seed=7)


def test_frontier_backend_uses_key_and_forwards_decode():
    rec = _Recorder("frontier-said-hi")
    be = FrontierBackend(base="claude-fable-5", decode=_decode(), api_key="sk-x", transport=rec)
    out = be.complete("hello")
    assert out == "frontier-said-hi"
    assert rec.last["params"]["temperature"] == 0.0
    assert rec.last["params"]["seed"] == 7


def test_frontier_backend_requires_key():
    with pytest.raises(BackendError, match="key"):
        FrontierBackend(base="claude-fable-5", decode=_decode(), api_key=None)


def test_system_native_backend_hits_local_endpoint():
    rec = _Recorder("local-said-hi")
    be = SystemNativeBackend(
        base="qwen2.5-coder-7b",
        decode=_decode(),
        endpoint="http://127.0.0.1:11434",
        transport=rec,
    )
    out = be.complete("hello")
    assert out == "local-said-hi"
    assert rec.last["params"]["endpoint"] == "http://127.0.0.1:11434"


def test_byok_backend_forwards_provider_and_key():
    rec = _Recorder("byok-said-hi")
    be = BYOKBackend(
        base="gpt-4o",
        decode=_decode(),
        provider="openai",
        api_key="sk-user",
        base_url="https://api.openai.com/v1",
        transport=rec,
    )
    out = be.complete("hello")
    assert out == "byok-said-hi"
    assert rec.last["params"]["provider"] == "openai"
    assert rec.last["params"]["api_key"] == "sk-user"


def test_byok_requires_key():
    with pytest.raises(BackendError, match="key"):
        BYOKBackend(
            base="gpt-4o",
            decode=_decode(),
            provider="openai",
            api_key=None,
            base_url="https://api.openai.com/v1",
        )


def test_resolve_offline_returns_none():
    assert resolve_backend(None, env={}) is None


def test_resolve_frontier_reads_env_key():
    spec = ModelSpec(plane="frontier", base="claude-fable-5", decode=_decode())
    be = resolve_backend(spec, env={"ANTHROPIC_API_KEY": "sk-env"}, transport=_Recorder())
    assert isinstance(be, FrontierBackend)


def test_resolve_frontier_missing_key_raises():
    spec = ModelSpec(plane="frontier", base="claude-fable-5", decode=_decode())
    with pytest.raises(BackendError, match="ANTHROPIC_API_KEY"):
        resolve_backend(spec, env={})


def test_resolve_byok_reads_env_key():
    spec = ModelSpec(
        plane="byok",
        base="gpt-4o",
        decode=_decode(),
        provider="openai",
        base_url="https://api.openai.com/v1",
    )
    be = resolve_backend(spec, env={"SKILLCELL_BYOK_KEY": "sk-byok"}, transport=_Recorder())
    assert isinstance(be, BYOKBackend)


def test_resolve_system_native_needs_no_key():
    spec = ModelSpec(
        plane="system",
        base="qwen2.5-coder-7b",
        decode=_decode(),
        endpoint="http://127.0.0.1:11434",
    )
    be = resolve_backend(spec, env={}, transport=_Recorder())
    assert isinstance(be, SystemNativeBackend)


def test_resolve_unknown_plane_raises():
    spec = ModelSpec(plane="quantum", base="x", decode=_decode())
    with pytest.raises(BackendError, match="plane"):
        resolve_backend(spec, env={})
