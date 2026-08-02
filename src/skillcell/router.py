"""Deterministic specialist routing.

Keyword-based, order-stable — same goal always selects the same specialist.
Real cells replace this with their own routing table; the default keeps the
loop runnable offline.
"""

from __future__ import annotations

_RULES: tuple[tuple[str, str], ...] = (
    ("firmware", "firmware-pentest"),
    ("apk", "apk-analysis"),
    ("burp", "burp-mcp"),
    ("ctf", "ctf-workflow"),
    ("web", "web-recon"),
)


def default_router(goal: str) -> str:
    low = goal.lower()
    for keyword, specialist in _RULES:
        if keyword in low:
            return specialist
    return "generalist"
