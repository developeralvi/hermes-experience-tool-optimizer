"""EBTTO — Experience-Based Tool Trajectory Optimization.

Public, production-grade, open-source tool-use optimization for Hermes Agent.

Import-time contract (Python): every module is a thin, side-effect-free layer.
No DB access, no hook registration, no network I/O at import time.
"""

from __future__ import annotations

__version__ = "0.1.0"
"""EBTTO version (PEP 396). Mirrors plugin.yaml `version`."""

__all__ = [
    "__version__",
    "register",
]


def register(ctx):
    """Module-level register(ctx) — the Hermes plugin entry point.

    The Hermes plugin system loads the module specified by ``main`` in
    ``plugin.yaml`` and calls its ``register(ctx)`` function. This function
    creates the EBTTOPlugin and registers all hooks via the public
    ``ctx.register_hook()`` API.

    Mode and enabled state come from the ``EBTTO_MODE`` / ``EBTTO_ENABLED``
    environment variables (defaulting to ``record_only`` / enabled) so an
    operator can opt into advisory behaviour without patching code. An
    unrecognised mode falls back to ``record_only`` — the safe default.
    """
    import os

    valid_modes = ("record_only", "shadow", "advisory", "guarded", "controlled_auto", "off")
    mode = os.environ.get("EBTTO_MODE", "record_only").strip().lower()
    if mode not in valid_modes:
        mode = "record_only"
    enabled = os.environ.get("EBTTO_ENABLED", "1").strip().lower() not in ("0", "false", "no")

    from .plugins import EBTTOPlugin
    plugin = EBTTOPlugin(manifest=None, ctx=ctx, config={
        "mode": mode,
        "enabled": enabled,
    })
    plugin.register()
    return plugin
