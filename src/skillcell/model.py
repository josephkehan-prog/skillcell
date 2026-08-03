"""The model plane: one interface, several backends — local first.

- LocalBackend    a small model served on this machine (MLX-LM / Ollama /
                  llama.cpp), optionally with a per-cell LoRA adapter. **The
                  canonical plane**: single-tenant, batch size 1, no key, no
                  egress — the only setting where bit-reproducibility is
                  actually available. ``system`` is a deprecated alias.
- FrontierBackend hosted frontier model, key from ANTHROPIC_API_KEY. A
                  fallback for cells with no promoted adapter yet.
- BYOKBackend     bring-your-own-key, any OpenAI-compatible provider.

Decode temperature is pinned at serve time. ``complete(prompt,
temperature=...)`` overrides it, because temperature 0 is a *serving*
invariant, not a training one: rejection sampling needs diverse attempts to
have anything to filter, and the adapter trained on them is then served cold.

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

# Ollama's OpenAI-compatible port; MLX-LM and llama.cpp servers speak the same
# shape on their own ports, so a cell only ever overrides the endpoint.
DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1"


class BackendError(RuntimeError):
    """Raised when a backend is misconfigured or cannot serve."""


class ModelBackend(Protocol):
    def complete(self, prompt: str, *, temperature: float | None = None) -> str: ...


def _decode_params(decode: Decode, temperature: float | None = None) -> dict[str, object]:
    return {
        "temperature": decode.temperature if temperature is None else temperature,
        "seed": decode.seed,
    }


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

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        params = _decode_params(self._decode, temperature) | {
            "model": self._base,
            "api_key": self._key,
        }
        return self._transport(prompt=prompt, params=params)


class LocalBackend:
    """A small model served on this machine, optionally LoRA-adapted.

    No key is read here on any path: a cell on the local plane behaves the
    same whether or not the environment holds provider credentials.
    """

    def __init__(
        self,
        *,
        base: str,
        decode: Decode,
        endpoint: str,
        adapter: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        if not endpoint:
            raise BackendError("local plane requires an endpoint")
        self._base = base
        self._decode = decode
        self._endpoint = endpoint
        self._adapter = adapter
        self._transport = transport or _echo_transport

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        params = _decode_params(self._decode, temperature) | {
            "model": self._base,
            "endpoint": self._endpoint,
            "adapter": self._adapter,
        }
        return self._transport(prompt=prompt, params=params)


# Deprecated alias: `plane: system` was the original name for the local plane.
SystemNativeBackend = LocalBackend


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

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        params = _decode_params(self._decode, temperature) | {
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
      frontier      -> ANTHROPIC_API_KEY
      byok          -> SKILLCELL_BYOK_KEY
      local/system  -> no key required
    """
    if spec is None or spec.plane == "offline":
        return None

    if spec.plane == "frontier":
        key = env.get("ANTHROPIC_API_KEY")
        if not key:
            raise BackendError("frontier plane: ANTHROPIC_API_KEY not set")
        return FrontierBackend(base=spec.base, decode=spec.decode, api_key=key, transport=transport)

    if spec.plane in ("local", "system"):
        endpoint = (
            spec.endpoint
            or env.get("SKILLCELL_LOCAL_ENDPOINT")
            or env.get("SKILLCELL_SYSTEM_ENDPOINT")
            or DEFAULT_LOCAL_ENDPOINT
        )
        return LocalBackend(
            base=spec.base,
            decode=spec.decode,
            endpoint=endpoint,
            adapter=spec.adapter,
            transport=transport,
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
