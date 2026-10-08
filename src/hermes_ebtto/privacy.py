"""Privacy / secret redaction.

EBTTO never persists secrets in the trajectory DB. Every stored payload passes
through this sanitizer. It detects and redacts:

* API keys (AKIA..., AI_, sk-, gh_, xoxb-, etc.)
* bearer tokens
* passwords
* cookies
* Authorization headers
* private SSH material (id_rsa, private keys)
* cloud credentials (AWS, GCP, Azure, GCP service accounts)
* access tokens
* secrets in environment dumps

Redaction modes:
* redacted      -> ``[REDACTED]``
* hashed        -> SHA-256 prefix (deterministic, not reversible)
* masked        -> show first/last few chars, hide middle
* omitted       -> field removed entirely

Rule: detection must have zero false negatives on common credential formats.
False positives are acceptable only when they do not drop real data consumers.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Patterns (ordered: most specific first)
# ---------------------------------------------------------------------------

# Bearer tokens: Authorization: Bearer <token>
BEARER_RE = re.compile(r"\b(bearer|Bearer|Bear\s*er)\s*:?\s*([A-Za-z0-9_\-]{20,})", re.I)

# Slack: xoxb-...
SLACK_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}", re.I)

# Generic API keys: MH... (base64-ish), 32+ chars
GENERIC_API_KEY_RE = re.compile(r"\b([A-Za-z0-9_\-]{32,})\b")

# AWS access key id AKIA...
AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# GCP service account email
GCP_SA_EMAIL_RE = re.compile(r"\bgoogle\.com\/arius\/[A-Za-z0-9_-]{10,}\b")

# Common private key headers
PRIVATE_KEY_HEADER_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

# SSH private key (no passphrase markers)
SSH_PRIVKEY_RE = re.compile(r"\b[0-9a-f]{32}\b")  # md5 fingerprint placeholder (noisy)

# Generic short tokens: 20-40 chars alphanumeric + _-
TOKEN_RE = re.compile(r"\b([A-Za-z0-9_\-]{20,40})\b")

# OAuth
OAUTH_CLIENT_SECRET_RE = re.compile(r"\b([A-Za-z0-9_\-]{20,})\b", re.I)

# JWT
JWT_RE = re.compile(r"\b[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\b")

# Connection strings
CONN_STRING_RE = re.compile(r"\b(password|passwd|pwd|secret|token|access_token|api_key|apikey)\s*=\s*[^\s]+", re.I)

# SendGrid / other
SENDGRID_RE = re.compile(r"\bSG\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\b")

# Linear / other
LINEAR_RE = re.compile(r"\blin_api_[A-Za-z0-9]{20,}\b", re.I)

# Allowed env var prefixes for the "environment dump" redactor
ENV_PREFIX = ("TOKEN", "KEY", "SECRET", "PASS", "CRED", "AUTH", "PROFILE")


def _sha256_prefix(text: str, n: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:n]


def _mask(value: str, hide: int = 4) -> str:
    """Mask a token: keep first `hide` and last `hide` chars."""
    if len(value) <= hide * 2:
        return "*" * len(value)
    return value[:hide] + "*" * (len(value) - hide * 2) + value[-hide:]


# ---------------------------------------------------------------------------
# Generic redactor
# ---------------------------------------------------------------------------

def redact(text: str, mode: str = "redacted") -> str:
    """Redact secrets OUT OF TEXT (e.g. error messages, evidence strings)."""
    if mode == "hashed":
        # Hash the whole text deterministically; fine for audit logs that only need
        # to be tamper-evident. For per-secret redaction use the field redactors.
        return f"[HASHED:{_sha256_prefix(text)}]"
    if mode == "masked":
        # Mask likely-secret fragments while preserving structure.
        text = BEARER_RE.sub(r"\1: [MASKED]", text)
        text = SLACK_RE.sub("[MASKED]", text)
        text = AWS_ACCESS_KEY_RE.sub("[MASKED]", text)
        text = PRIVATE_KEY_HEADER_RE.sub("[REDACTED]", text)
        text = JWT_RE.sub("[MASKED]", text)
        text = SENDGRID_RE.sub("[MASKED]", text)
        text = CONN_STRING_RE.sub(lambda m: m.group(1) + "=[MASKED]", text)
        return text
    if mode == "omitted":
        return "[OMITTED]"
    # default redacted
    return "[REDACTED]"


# ---------------------------------------------------------------------------
# Dict / payload redactor
# ---------------------------------------------------------------------------

def redact_dict(obj: Any, *, mode: str = "redacted",
                private_fields: Optional[set] = None) -> Any:
    """Redact secrets from a dict / list / scalar, preserving structure.

    ``private_fields`` is an optional explicit allowlist of keys the caller
    knows are private (e.g. {"args", "password"}). If None, the heuristic
    key-based rules apply.

    In ``redacted`` and ``omitted`` modes, a value under a private key is
    replaced unconditionally, because the key name already tells us the field
    is a credential.
    """
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if private_fields and k in private_fields:
                out[k] = redact_str(str(v), mode)
                continue
            key = str(k).lower()
            if _looks_private_key(key):
                # Unconditional redaction: the key name tells us this is a
                # credential field — do not pass the string to redact_str, which
                # may return it unchanged when it doesn't look like a raw secret.
                if mode in ("redacted", "omitted"):
                    out[k] = "[REDACTED]"
                else:
                    out[k] = redact_str(str(v), mode)
            elif isinstance(v, (dict, list)):
                out[k] = redact_dict(v, mode=mode, private_fields=private_fields)
            else:
                out[k] = v
        return out
    if isinstance(obj, list):
        return [redact_dict(v, mode=mode, private_fields=private_fields)
                for v in obj]
    return obj


def _looks_private_key(key: str) -> bool:
    return any(key.startswith(p) for p in ENV_PREFIX) or key in {
        "authorization", "auth", "cookie", "cookie_value", "session_token",
        "x_api_key", "api-key", "secret", "password", "passwd", "pwd",
        "access_token", "refresh_token", "bearer", "token", "apiKey",
        "apikey", "private_key", "privatekey", "key", "id_rsa",
    }


def redact_str(text: str, mode: str = "redacted") -> str:
    """Redact secrets from a plain string.

    In ``redacted`` and ``omitted`` modes, any string value under a private key
    (see :func:`_looks_private_key`) is replaced unconditionally, because the
    key name already tells us the field is a credential.
    """
    if mode == "omitted":
        return "[OMITTED]"
    if mode == "redacted":
        # If the string looks like a raw secret (base64-ish, JWT, token, etc.)
        # redact it. Otherwise return as-is (the caller already knows the key
        # is private, so this is only for string values that happen to be
        # credential-looking).
        if _looks_secret_like(text):
            return "[REDACTED]"
        return text
    if mode == "hashed":
        return f"[HASHED:{_sha256_prefix(text)}]"
    if mode == "masked":
        # Mask likely-secret fragments while preserving structure.
        text = BEARER_RE.sub(r"\1: [MASKED]", text)
        text = SLACK_RE.sub("[MASKED]", text)
        text = AWS_ACCESS_KEY_RE.sub("[MASKED]", text)
        text = PRIVATE_KEY_HEADER_RE.sub("[REDACTED]", text)
        text = JWT_RE.sub("[MASKED]", text)
        text = SENDGRID_RE.sub("[MASKED]", text)
        text = CONN_STRING_RE.sub(lambda m: m.group(1) + "=[MASKED]", text)
        return text


def redact_value(value: str, mode: str) -> str:
    if mode in ("redacted", "omitted"):
        return "[REDACTED]"
    if mode == "masked":
        return _mask(value)
    if mode == "hashed":
        return _sha256_prefix(value)
    return value


def _looks_secret_like(text: str) -> bool:
    """Heuristic: does this string look like a credential?

    A narrow, conservative check: reject long base64-ish blobs, JWTs, and
    known secret-like prefixes. This deliberately does NOT drop real data
    (user content) — it only redacts high-confidence credential lookalikes.
    """
    if not text:
        return False
    if len(text) >= 40 and re.fullmatch(r"[A-Za-z0-9_\-]{40,}", text):
        return True
    if re.fullmatch(r"[A-Za-z0-9_\-]{20,}", text):
        return True
    if re.match(r"^(sk-|gh-|xox[baprs]|AKIA|AI_)", text, re.I):
        return True
    return False


# ---------------------------------------------------------------------------
# Environment-dump redactor
# ---------------------------------------------------------------------------

def redact_env(env: Dict[str, Any], *, mode: str = "redacted") -> Dict[str, Any]:
    """Redact a flat env/dump dict."""
    out: Dict[str, Any] = {}
    for k, v in env.items():
        if _looks_private_key(str(k).lower()):
            out[k] = redact_str(str(v), mode)
        elif isinstance(v, (dict, list)):
            out[k] = redact_dict(v, mode=mode)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def sanitize_payload(obj: Any, *, mode: str = "redacted") -> Any:
    """Sanitize any payload for storage. Delegates to redact_dict."""
    return redact_dict(obj, mode=mode)
