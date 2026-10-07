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
]
