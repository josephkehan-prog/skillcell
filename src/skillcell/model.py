"""The model plane: three backends behind one interface.

- FrontierBackend    hosted frontier model (Claude), key from ANTHROPIC_API_KEY
- SystemNativeBackend local model served on this machine (MLX / Ollama endpoint)
- BYOKBackend        bring-your-own-key, any OpenAI-compatible provider

Each backend takes an injectable ``transport`` so the loop is testable and
deterministic without a live network. Real transports are attached at the
edges (CLI / provisioner); the core never imports a vendor SDK directly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from .manifest import Decode, ModelSpec

# A transport turns a prompt + params into completion text.
Transport = Callable[..., str]


class BackendError(RuntimeError):
    """Raised when a backend is misconfigured or cannot serve."""


class ModelBackend(Protocol):
    def complete(self, prompt: str) -> str: ...


def _decode_params(decode: Decode) -> dict[str, object]:
    return {"temperature": decode.temperature, "seed": decode.seed}


def _echo_transport(*, prompt: str, params: Mapping[str, object]) -> str:
    # Deterministic default used when no real transport is attached: it makes
    # the plane runnable end to end offline-of-network while still exercising
    # the selected backend and its params.
    return prompt


class FrontierBackend:
    def __init__(
        self,
        *,
        base: str,
        decode: Decode,
        api_key: str | None,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise BackendError("frontier plane requires an API key")
        self._base = base
        self._decode = decode
        self._key = api_key
        self._transport = transport or _echo_transport

    def complete(self, prompt: str) -> str:
        params = _decode_params(self._decode) | {"model": self._base, "api_key": self._key}
        return self._transport(prompt=prompt, params=params)


class SystemNativeBackend:
    def __init__(
        self,
        *,
        base: str,
        decode: Decode,
        endpoint: str,
        transport: Transport | None = None,
    ) -> None:
        if not endpoint:
            raise BackendError("system plane requires an endpoint")
        self._base = base
        self._decode = decode
        self._endpoint = endpoint
        self._transport = transport or _echo_transport

    def complete(self, prompt: str) -> str:
        params = _decode_params(self._decode) | {"model": self._base, "endpoint": self._endpoint}
        return self._transport(prompt=prompt, params=params)


class BYOKBackend:
    def __init__(
        self,
        *,
        base: str,
        decode: Decode,
        provider: str,
        api_key: str | None,
        base_url: str,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise BackendError("byok plane requires an API key")
        self._base = base
        self._decode = decode
        self._provider = provider
        self._key = api_key
        self._base_url = base_url
        self._transport = transport or _echo_transport

    def complete(self, prompt: str) -> str:
        params = _decode_params(self._decode) | {
            "model": self._base,
            "provider": self._provider,
            "api_key": self._key,
            "base_url": self._base_url,
        }
        return self._transport(prompt=prompt, params=params)


def resolve_backend(
    spec: ModelSpec | None,
    *,
    env: Mapping[str, str],
    transport: Transport | None = None,
) -> ModelBackend | None:
    """Build the backend for a cell's model spec, or None for offline.

    Keys are read from the environment by convention, never from the manifest:
      frontier -> ANTHROPIC_API_KEY
      byok     -> SKILLCELL_BYOK_KEY
      system   -> no key required
    """
    if spec is None or spec.plane == "offline":
        return None

    if spec.plane == "frontier":
        key = env.get("ANTHROPIC_API_KEY")
        if not key:
            raise BackendError("frontier plane: ANTHROPIC_API_KEY not set")
        return FrontierBackend(base=spec.base, decode=spec.decode, api_key=key, transport=transport)

    if spec.plane == "system":
        endpoint = spec.endpoint or env.get("SKILLCELL_SYSTEM_ENDPOINT", "")
        return SystemNativeBackend(
            base=spec.base, decode=spec.decode, endpoint=endpoint, transport=transport
        )

    if spec.plane == "byok":
        key = env.get("SKILLCELL_BYOK_KEY")
        if not key:
            raise BackendError("byok plane: SKILLCELL_BYOK_KEY not set")
        return BYOKBackend(
            base=spec.base,
            decode=spec.decode,
            provider=spec.provider or "openai",
            api_key=key,
            base_url=spec.base_url or "",
            transport=transport,
        )

    raise BackendError(f"unknown model plane '{spec.plane}'")
