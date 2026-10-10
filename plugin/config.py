"""EBTTO configuration.

Exposes the documented configuration schema, defaults, and typed accessors.

The schema is a superset of the installed Hermes plugin configuration:

.. code-block:: yaml

    ebtto:
      enabled: true
      mode: shadow            # OFF | RECORD_ONLY | SHADOW | ADVISORY | GUARDED | CONTROLLED_AUTO
      storage:
        backend: sqlite
        path: "~/.hermes/.hermes-ebtto/ebtto.db"
      retrieval:
        max_results: 3
        min_confidence: 0.80
      intervention:
        allow_block: false
        allow_modify: false
        require_approval: true
      learning:
        min_pattern_occurrences: 5
        min_success_rate: 0.80
      privacy:
        redact_secrets: true
        retention_days: 90

Every key is documented in the source below. Defaults are compiled and
versioned (per :mod:`hermes_ebtto.events`).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Versioned defaults
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Canonical default mode
# ---------------------------------------------------------------------------
# ``DEFAULT_MODE`` is the SINGLE source of truth for "what mode applies when
# neither the EBTTO_MODE environment variable nor an applicable context
# configuration supplies one". ``plugins/__init__.py::register()`` resolves its
# fallback from here so the declared default and the effective registration
# fallback cannot drift apart again.
#
# ``record_only`` is deliberately the default: a fresh install must observe and
# record without injecting guidance into the model's prompt. Guidance injection
# is opt-in via EBTTO_MODE or an explicit config entry.
DEFAULT_MODE = "record_only"

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "mode": DEFAULT_MODE,
    "storage": {
        "backend": "sqlite",
        "path": "~/.hermes/.hermes-ebtto/ebtto.db",
    },
    "retrieval": {
        "max_results": 3,
        "min_confidence": 0.80,
    },
    "intervention": {
        "allow_block": False,
        "allow_modify": False,
        "require_approval": True,
    },
    "learning": {
        "min_pattern_occurrences": 5,
        "min_success_rate": 0.80,
    },
    "privacy": {
        "redact_secrets": True,
        "retention_days": 90,
    },
}

VALID_MODES = ("off", "record_only", "shadow", "advisory", "guarded", "controlled_auto")
VALID_BACKENDS = ("sqlite",)


def _get(d: Dict[str, Any], *path: str, default: Any = None) -> Any:
    """Deep-get a nested dict path; return ``default`` if any key is missing."""
    curr: Any = d
    for key in path:
        if not isinstance(curr, dict) or key not in curr:
            return default
        curr = curr[key]
    return curr


def _get_or_default(d: Dict[str, Any], *path: str, module_default: Any = None) -> Any:
    """Deep-get a nested dict path; return module-level default if any key is missing."""
    curr: Any = d
    for key in path:
        if not isinstance(curr, dict) or key not in curr:
            return module_default
        curr = curr[key]
    return curr if curr is not None else module_default


def _get_def(d: Dict[str, Any], *path: str, module_default: Any = None,
             default: Any = None) -> Any:
    """Deep-get a nested dict path.

    If a key is missing at any level, return ``module_default`` when provided,
    otherwise fall back to ``default``.
    """
    curr: Any = d
    for key in path:
        if not isinstance(curr, dict) or key not in curr:
            return module_default if module_default is not None else default
        curr = curr[key]
    return curr if curr is not None else (default if default is not None else module_default)


class EbttoConfig:
    """Typed, validated EBTTO configuration.

    Attrs:
        enabled: True to activate EBTTO.
        mode: OFF | RECORD_ONLY | SHADOW | ADVISORY | GUARDED | CONTROLLED_AUTO.
        storage: {"backend": "sqlite", "path": str}.
        retrieval: {"max_results": int, "min_confidence": 0..1}.
        intervention: {"allow_block", "allow_modify", "require_approval"}.
        learning: {"min_pattern_occurrences", "min_success_rate"}.
        privacy: {"redact_secrets", "retention_days"}.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        mode: str = "shadow",
        storage: Dict[str, Any] = None,
        retrieval: Dict[str, Any] = None,
        intervention: Dict[str, Any] = None,
        learning: Dict[str, Any] = None,
        privacy: Dict[str, Any] = None,
    ):
        self.enabled = enabled
        self.mode = mode
        self.storage = dict(storage or {})
        self.retrieval = dict(retrieval or {})
        self.intervention = dict(intervention or {})
        self.learning = dict(learning or {})
        self.privacy = dict(privacy or {})

    @property
    def mode_str(self) -> str:
        return self.mode

    @property
    def storage_path(self) -> str:
        return self.storage.get("path", "~/.hermes/.hermes-ebtto/ebtto.db")

    @property
    def retrieval_max_results(self) -> int:
        v = self.retrieval.get("max_results", 3)
        return v if isinstance(v, int) and v >= 1 else 3

    @property
    def retrieval_min_confidence(self) -> float:
        v = self.retrieval.get("min_confidence", 0.80)
        return 0.0 if not isinstance(v, (int, float)) else min(1.0, max(0.0, v))

    @property
    def intervention_allow_block(self) -> bool:
        return bool(self.intervention.get("allow_block", False))

    @property
    def intervention_allow_modify(self) -> bool:
        return bool(self.intervention.get("allow_modify", False))

    @property
    def intervention_require_approval(self) -> bool:
        return bool(self.intervention.get("require_approval", True))

    @property
    def learning_min_occurrences(self) -> int:
        v = self.learning.get("min_pattern_occurrences", 5)
        return v if isinstance(v, int) and v >= 1 else 5

    @property
    def learning_min_success_rate(self) -> float:
        v = self.learning.get("min_success_rate", 0.80)
        return 0.0 if not isinstance(v, (int, float)) else min(1.0, max(0.0, v))

    @property
    def privacy_redact_secrets(self) -> bool:
        return bool(self.privacy.get("redact_secrets", True))

    @property
    def privacy_retention_days(self) -> int:
        v = self.privacy.get("retention_days", 90)
        return v if isinstance(v, int) and v >= 0 else 90

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "storage": self.storage,
            "retrieval": self.retrieval,
            "intervention": self.intervention,
            "learning": self.learning,
            "privacy": self.privacy,
        }

    def __repr__(self) -> str:
        return (f"EbttoConfig(enabled={self.enabled}, mode={self.mode!r}, "
                f"retrieval={self.retrieval!r}, intervention={self.intervention!r}, "
                f"learning={self.learning!r}, privacy={self.privacy!r})")


def get_ebtto(config: Dict[str, Any]) -> "EbttoConfig":
    """Return a typed EbttoConfig from a raw config dict."""
    return EbttoConfig(
        enabled=bool(_get_or_default(config, "ebtto", "enabled",
                                     module_default=DEFAULTS["enabled"])),
        mode=_get_or_default(config, "ebtto", "mode",
                             module_default=DEFAULTS["mode"]),
        storage=dict(_get_or_default(config, "ebtto", "storage",
                                     module_default=DEFAULTS["storage"])),
        retrieval=dict(_get_or_default(config, "ebtto", "retrieval",
                                       module_default=DEFAULTS["retrieval"])),
        intervention=dict(_get_or_default(config, "ebtto", "intervention",
                                          module_default=DEFAULTS["intervention"])),
        learning=dict(_get_or_default(config, "ebtto", "learning",
                                      module_default=DEFAULTS["learning"])),
        privacy=dict(_get_or_default(config, "ebtto", "privacy",
                                     module_default=DEFAULTS["privacy"])),
    )
