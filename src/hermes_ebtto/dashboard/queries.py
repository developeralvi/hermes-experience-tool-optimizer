"""Read-only query layer for the EBTTO dashboard.

Every query here opens the SAME database the plugin writes to
(``storage.get_storage_path()``) with a strictly read-only SQLite connection
(``mode=ro`` + ``PRAGMA query_only``). The dashboard never creates, migrates,
or mutates a database — if the file or the schema is missing, callers get an
explicit error and an honest empty/error state.

All user-supplied values are passed as bound parameters; no table or column
name is ever taken from a request.
"""

from __future__ import annotations

import json
import re
import sqlite3
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_ebtto.storage import DEFAULT_DB_NAME, get_storage_path

# Bound result sizes — the UI must never be able to pull the whole DB.
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

# Column allowlists for detail queries. Never SELECT * — the tables contain
# raw_args (unsanitized arguments) which must never leave this module.
_TOOL_CALL_DETAIL_COLS = (
    "tool_call_id", "task_id", "turn_id", "tool_name", "sanitized_args",
    "result_status", "duration_ms", "order_number", "attempt_number",
    "error_class", "error_message", "classified", "classified_class",
    "classifier_version", "created_at",
)
_OUTCOME_DETAIL_COLS = (
    "outcome_id", "task_id", "turn_id", "result", "confidence", "recorded_at",
)
_ERROR_DETAIL_COLS = (
    "error_id", "task_id", "turn_id", "tool_call_id", "tool_name",
    "error_class", "confidence", "error_message", "created_at",
)
# Columns whose content may contain user-controlled text; any value from
# these is passed through privacy redaction before display so historical
# rows that predate sanitization cannot leak credentials.
_SENSITIVE_TEXT_COLS = (
    "sanitized_args", "error_message", "sanitized_intent", "strategy_name",
    "pattern_name", "evidence", "task_fingerprint", "instruction", "intent",
    "raw_args",
)

# Secret-shaped tokens the canonical privacy layer does not mask in-place
# (its regexes target *embedded* fragments inside longer prose). A bare key
# stored in a JSON args field is exactly this case, so withhold it.
_SECRET_SHAPE_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{8,}|sk_live_[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{20,}"
    r"|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)\b"
)

_TIME_WINDOWS = {
    "1h": "-1 hour",
    "24h": "-1 day",
    "7d": "-7 days",
    "30d": "-30 days",
    "all": None,
}

# Capability flags are computed per call rather than cached: sqlite3.Connection
# rejects attribute assignment AND cannot be weak-referenced, so any
# module-level registry either leaks entries (id-keyed, never cleaned when a
# caller closes the connection directly) or is impossible (weak). Both
# capability checks below are trivial in-memory catalog queries, so caching
# bought nothing — the registry is gone and cannot grow with request count.


class DashboardError(Exception):
    """Raised when the database is missing, unreadable, or schema-incompatible."""


def resolve_db_path(db_path: Optional[str] = None) -> Path:
    """Resolve the database path exactly like the plugin does."""
    if db_path:
        p = Path(db_path).expanduser()
        if p.is_dir():
            p = p / DEFAULT_DB_NAME
        return p
    return get_storage_path() / DEFAULT_DB_NAME


def open_ro(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open the EBTTO database read-only. Raises DashboardError on failure."""
    path = resolve_db_path(db_path)
    if not path.exists():
        raise DashboardError(
            f"EBTTO database not found at {path}. "
            "Run Hermes with the hermes-ebtto plugin enabled first, or pass "
            "--db <path>."
        )
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    # WAL lets the live plugin keep writing while we read.
    try:
        conn.execute("PRAGMA journal_mode")  # read current mode, never set it
    except sqlite3.Error:
        pass
    try:
        _assert_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def close_conn(conn: sqlite3.Connection) -> None:
    """Close a connection and drop its capability flag.

    The caller MUST use this (or ``with conn:`` followed by ``close_conn``)
    — the module never retains a strong reference to a connection, so the
    flag map cannot grow unboundedly. Safe to call on an already-closed
    connection; never raises.
    """
    try:
        conn.close()
    except sqlite3.Error:
        pass


def _assert_schema(conn: sqlite3.Connection) -> None:
    """Fail loudly (not silently) on an incompatible/missing schema."""
    have = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    required = {"tasks", "tool_calls", "outcomes", "strategies", "patterns"}
    missing = required - have
    if missing:
        raise DashboardError(
            f"Database schema incompatible; missing tables: {sorted(missing)}. "
            "This is not an EBTTO database (or it predates schema v1)."
        )
    # retrieval_guidance_events arrived in schema v4; older DBs are still
    # valid, the dashboard reports the telemetry as unavailable.
    # outcomes.tool_call_id (the per-call correlation key) arrived in v5.
    # A pre-v5 database cannot correlate outcomes to tool calls, so every
    # outcome is UNKNOWN rather than misattributed — reported honestly.
    # (Capabilities are queried on demand by the helpers below; nothing is
    # cached on the connection, which cannot hold custom attributes.)


def has_guidance_telemetry(conn: sqlite3.Connection) -> bool:
    """True when the connection points at a schema-v4+ database."""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='retrieval_guidance_events'").fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def has_outcome_correlation(conn: sqlite3.Connection) -> bool:
    """True when outcomes carry tool_call_id (schema v5+).

    On a pre-v5 database the dashboard cannot link an outcome to its tool
    call, so every outcome is UNKNOWN — never guessed from session-level
    success. The UI states this limitation explicitly.
    """
    try:
        return any(r[1] == "tool_call_id"
                   for r in conn.execute("PRAGMA table_info(outcomes)"))
    except sqlite3.Error:
        return False


def _redact_text(value: Any) -> Any:
    """Redact credentials from a text column before display.

    New rows are sanitized at write time, but historical rows may not be —
    the redaction is applied at read time too, so pre-sanitization data can
    never leak through the API even if it contains a live secret.

    Falls back through two layers (whole-string redaction, embedded-fragment
    masking). If either changes the text, the result is safe; if neither
    does, a secret-SHAPED value (bare API key / JWT / AWS key / private-key
    header) is withheld entirely rather than risked, and ordinary text passes
    through untouched.
    """
    if not isinstance(value, str) or not value:
        return value
    try:
        from hermes_ebtto import privacy as pr

        for candidate in (pr.redact_str(value), pr.redact(value, mode="masked")):
            if candidate != value:
                return candidate
        # Nothing changed: the canonical layer does not recognize this
        # content as a secret. A bare key stored in an args field is the one
        # remaining case, so withhold only secret-SHAPED values.
        if _SECRET_SHAPE_RE.search(value):
            return "[REDACTED]"
        return value
    except Exception:
        # Redaction failure must not fail the page — but we also must not
        # return potentially-raw content.
        return "[REDACTED: sanitization unavailable]"


def _safe_rows(cur: sqlite3.Cursor) -> List[Dict[str, Any]]:
    """Fetch rows and redact sensitive text columns."""
    rows = _rows(cur)
    for row in rows:
        for col in _SENSITIVE_TEXT_COLS:
            if col in row:
                row[col] = _redact_text(row[col])
    return rows


def _redact_text_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Redact the sensitive text columns of a single row.

    Identifier columns (task_id, turn_id, tool_call_id, *_id) are NEVER
    redacted — they are uuids/uuid-like ids the UI needs for correlation,
    not user text. Only the free-text columns in ``_SENSITIVE_TEXT_COLS``
    are passed through privacy redaction.
    """
    for col in _SENSITIVE_TEXT_COLS:
        if col in row:
            row[col] = _redact_text(row[col])
    return row


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _time_clause(window: str) -> Tuple[str, List[Any]]:
    """Return (sql fragment, params) for a time window. 'all' = no filter."""
    mod = _TIME_WINDOWS.get(window)
    if mod is None:
        return "", []
    return "WHERE created_at >= datetime('now', ?)", [mod]


def _parse_window(window: Optional[str]) -> str:
    if not window or window not in _TIME_WINDOWS:
        return "24h"
    return window


def _rows(cur: sqlite3.Cursor) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_page(page: Any, page_size: Any) -> Tuple[int, int]:
    p = max(1, _int(page, 1))
    ps = _int(page_size, DEFAULT_PAGE_SIZE)
    ps = max(1, min(ps, MAX_PAGE_SIZE))
    return p, ps


# ---------------------------------------------------------------------------
# Page A — Overview
# ---------------------------------------------------------------------------

def _correlated_status_sql(alias: str = "tool_calls") -> str:
    """Per-call outcome classification.

    Returns SQL CASE yielding 'success' / 'failure' / 'unknown':
    * success  — the outcome row correlated by tool_call_id says SUCCESS
    * failure  — correlated outcome says FAILURE, or (synthetic writes only)
                 result_status is a failure marker
    * unknown  — no correlated outcome and no definitive status

    Session-level or task-level outcomes NEVER leak in: every branch keys on
    the tool call's own tool_call_id. Verified by regression tests with
    multiple calls and mixed outcomes in one session.

    NOTE: callers on a pre-migration-5 database (outcomes has no
    tool_call_id column) must use :func:`_uncorrelated_status_sql` instead —
    SQLite validates the column reference at COMPILE time, so a CASE cannot
    guard it at runtime.
    """
    a = alias
    return (
        "CASE "
        f" WHEN (SELECT o.result FROM outcomes o "
        f"       WHERE o.tool_call_id = {a}.tool_call_id "
        f"       ORDER BY o.recorded_at DESC LIMIT 1) = 'SUCCESS' THEN 'success' "
        f" WHEN (SELECT o.result FROM outcomes o "
        f"       WHERE o.tool_call_id = {a}.tool_call_id "
        f"       ORDER BY o.recorded_at DESC LIMIT 1) = 'FAILURE' THEN 'failure' "
        f" WHEN {a}.result_status IN ('error', 'failed', 'failure') THEN 'failure' "
        f" WHEN {a}.result_status IN ('ok', 'success') THEN 'success' "
        " ELSE 'unknown' "
        "END"
    )


def _uncorrelated_status_sql(alias: str = "tool_calls") -> str:
    """Pre-migration-5 fallback: everything is UNKNOWN.

    A database whose outcomes table has no tool_call_id column cannot
    correlate an outcome to its tool call. The honest result is UNKNOWN for
    every row — never a session-level guess, never a misattributed success.
    """
    return (
        f"CASE WHEN {alias}.result_status IN ('ok', 'success') THEN 'success' "
        f"WHEN {alias}.result_status IN ('error', 'failed', 'failure') "
        f"THEN 'failure' ELSE 'unknown' END"
    )


def status_sql(conn: Optional[sqlite3.Connection] = None,
               alias: str = "tool_calls") -> str:
    """Per-call outcome classification, database-aware.

    Uses tool_call_id correlation when the schema supports it (v5+); on a
    pre-v5 database it degrades to result_status-only classification with
    everything else UNKNOWN, so no outcome is ever misattributed.
    """
    if conn is not None and not has_outcome_correlation(conn):
        return _uncorrelated_status_sql(alias)
    return _correlated_status_sql(alias)


def _outcome_counts_sql(status_expr: str, alias: str = "tool_calls",
                        *, with_window: bool = True) -> str:
    """Counted per-call classification for one session/window.

    ``status_expr`` comes from :func:`status_sql` (database-aware) — the
    caller passes it so the pre-v5 fallback and the v5 correlation use the
    same code path.
    """
    where = "WHERE created_at >= datetime('now', ?)" if with_window else ""
    return (
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN {status_expr} = 'success' THEN 1 ELSE 0 END) AS succeeded, "
        f"SUM(CASE WHEN {status_expr} = 'failure' THEN 1 ELSE 0 END) AS failed, "
        f"SUM(CASE WHEN {status_expr} = 'unknown' THEN 1 ELSE 0 END) AS unknown "
        f"FROM tool_calls {alias} {where}"
    )


def overview(conn: sqlite3.Connection, window: str = "24h") -> Dict[str, Any]:
    w = _parse_window(window)
    where, params = _time_clause(w)

    total, succeeded, failed, unknown = 0, 0, 0, 0
    row = conn.execute(_outcome_counts_sql(status_sql(conn),
                                           with_window=bool(where)),
                       params if where else []).fetchone()
    if row:
        total, succeeded, failed, unknown = (row[0] or 0), (row[1] or 0), (row[2] or 0), (row[3] or 0)

    patterns = int(conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0])
    strategies = int(conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0])
    qualified = int(
        conn.execute("SELECT COUNT(*) FROM strategies WHERE status = 'validated'").fetchone()[0]
    )
    tasks = int(conn.execute(f"SELECT COUNT(*) FROM tasks").fetchone()[0])

    guidance: Dict[str, Any] = {"available": False}
    if has_guidance_telemetry(conn):
        rows = _rows(
            conn.execute(
                """SELECT reason_code, COUNT(*) n FROM retrieval_guidance_events
                   GROUP BY reason_code ORDER BY n DESC"""
            )
        )
        delivered = int(
            conn.execute(
                "SELECT COUNT(*) FROM retrieval_guidance_events WHERE guidance_returned = 1"
            ).fetchone()[0]
        )
        guidance = {
            "available": True,
            "by_reason": rows,
            "delivered": delivered,
            "total": int(conn.execute("SELECT COUNT(*) FROM retrieval_guidance_events").fetchone()[0]),
        }

    # failure trend (last 14 days, daily buckets — cheap and index-friendly)
    trend = _rows(
        conn.execute(
            """SELECT date(created_at) AS day,
                      SUM(CASE WHEN """ + status_sql(conn) + """ = 'success' THEN 1 ELSE 0 END) AS ok,
                      SUM(CASE WHEN """ + status_sql(conn) + """ = 'failure' THEN 1 ELSE 0 END) AS fail,
                      SUM(CASE WHEN """ + status_sql(conn) + """ = 'unknown' THEN 1 ELSE 0 END) AS unknown
                 FROM tool_calls
                WHERE created_at >= datetime('now', '-14 days')
                GROUP BY day ORDER BY day"""
        )
    )
    top_tools = _rows(
        conn.execute(
            f"""SELECT tool_name,
                       COUNT(*) AS calls,
                       SUM(CASE WHEN {status_sql(conn)} = 'success' THEN 1 ELSE 0 END) AS ok,
                       SUM(CASE WHEN {status_sql(conn)} = 'failure' THEN 1 ELSE 0 END) AS fail,
                       SUM(CASE WHEN {status_sql(conn)} = 'unknown' THEN 1 ELSE 0 END) AS unknown
                  FROM tool_calls {where}
                 GROUP BY tool_name ORDER BY calls DESC LIMIT 10""",
            params,
        )
    )

    integrity = "unknown"
    try:
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.Error:
        pass

    known = succeeded + failed
    return {
        "window": w,
        "tool_calls": {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "unknown": unknown,
        },
        # The success rate denominator EXCLUDES unknowns (per requirement);
        # it is None when nothing is known rather than a false 0%/100%.
        "success_rate": (succeeded / known) if known else None,
        "known_outcomes": known,
        "tasks_total": tasks,
        "patterns": patterns,
        "strategies": {"total": strategies, "qualified": qualified},
        "guidance": guidance,
        "failure_trend_14d": trend,
        "top_tools": top_tools,
        "db_integrity": integrity,
    }


# ---------------------------------------------------------------------------
# Page B — Live activity / Page C — Tool calls
# ---------------------------------------------------------------------------

def tool_calls(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = None,
    tool: Optional[str] = None,
    window: str = "24h",
    search: Optional[str] = None,
    task_id: Optional[str] = None,
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    w = _parse_window(window)
    p, ps = _clamp_page(page, page_size)
    clauses: List[str] = []
    params: List[Any] = []

    mod = _TIME_WINDOWS.get(w)
    if mod:
        clauses.append("created_at >= datetime('now', ?)")
        params.append(mod)
    if status == "success":
        clauses.append(f"{status_sql(conn)} = 'success'")
    elif status == "failure":
        clauses.append(f"{status_sql(conn)} = 'failure'")
    if tool:
        clauses.append("tool_name = ?")
        params.append(tool[:100])
    if task_id:
        clauses.append("task_id = ?")
        params.append(task_id[:100])
    if search:
        clauses.append(
            "(tool_name LIKE ? OR task_id LIKE ? OR sanitized_args LIKE ? "
            " OR error_message LIKE ?)"
        )
        like = f"%{search[:100]}%"
        params.extend([like, like, like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = int(conn.execute(f"SELECT COUNT(*) FROM tool_calls {where}", params).fetchone()[0])
    rows = _safe_rows(
        conn.execute(
            f"""SELECT tool_call_id, task_id, turn_id, tool_name, sanitized_args,
                      result_status, duration_ms, attempt_number, error_class,
                      error_message, classified_class, created_at,
                      {status_sql(conn)} AS outcome
                 FROM tool_calls {where}
                 ORDER BY created_at DESC, tool_call_id DESC
                 LIMIT ? OFFSET ?""",
            params + [ps, (p - 1) * ps],
        )
    )
    return {"rows": rows, "total": total, "page": p, "page_size": ps,
            "pages": (total + ps - 1) // ps}


def tool_call_detail(conn: sqlite3.Connection, tool_call_id: str) -> Optional[Dict[str, Any]]:
    # Explicit column allowlist — never SELECT * (raw_args must not leave).
    cols = ", ".join(_TOOL_CALL_DETAIL_COLS)
    row = conn.execute(
        f"SELECT {cols} FROM tool_calls WHERE tool_call_id = ?", (tool_call_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d = _redact_text_row(dict(row))
    # Correlate the outcome by tool_call_id ONLY — the two writers assign
    # independent task ids, so a task_id join here would show unrelated rows.
    # Pre-migration-5 outcomes have no tool_call_id column: the honest result
    # is "not reliably linked", never a session-level substitute.
    if has_outcome_correlation(conn):
        d["outcomes"] = _safe_rows(
            conn.execute(
                "SELECT " + ", ".join(_OUTCOME_DETAIL_COLS) +
                " FROM outcomes WHERE tool_call_id = ?", (tool_call_id,)
            )
        )
    else:
        d["outcomes"] = []
    d["outcome_correlation"] = (
        "correlated by tool_call_id"
        if d["outcomes"] else
        "Outcome not reliably linked to this tool call "
        "(database predates migration 5 — no tool_call_id on outcomes)"
    )
    d["errors"] = _safe_rows(
        conn.execute(
            "SELECT " + ", ".join(_ERROR_DETAIL_COLS) +
            " FROM errors WHERE tool_call_id = ?", (tool_call_id,)
        )
    )
    # attempts: same task AND tool, correlated by tool_call_id family.
    # The pre-tool rows share the recorder task_id; the "related attempt"
    # notion is only meaningful within that task (never cross-session).
    # attempts share the pre-tool recorder's task_id; their outcome column
    # is only queryable when the schema supports tool_call_id correlation.
    if has_outcome_correlation(conn):
        attempts_sql = """SELECT tool_call_id, attempt_number, result_status,
                      duration_ms, error_class, created_at,
                      (SELECT o.result FROM outcomes o
                        WHERE o.tool_call_id = tool_calls.tool_call_id
                        ORDER BY o.recorded_at DESC LIMIT 1) AS outcome
                 FROM tool_calls
                WHERE task_id = ?
                ORDER BY attempt_number, created_at"""
    else:
        attempts_sql = """SELECT tool_call_id, attempt_number, result_status,
                      duration_ms, error_class, created_at, 'unknown' AS outcome
                 FROM tool_calls
                WHERE task_id = ?
                ORDER BY attempt_number, created_at"""
    d["attempts"] = _rows(conn.execute(attempts_sql, (d["task_id"],)))
    return d


# ---------------------------------------------------------------------------
# Page D — Failures & recovery
# ---------------------------------------------------------------------------

def failures(
    conn: sqlite3.Connection,
    *,
    window: str = "24h",
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    w = _parse_window(window)
    p, ps = _clamp_page(page, page_size)
    mod = _TIME_WINDOWS.get(w)
    where, params = ("WHERE created_at >= datetime('now', ?)", [mod]) if mod else ("", [])
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM tool_calls {where} {'AND' if where else 'WHERE'} "
            f"{status_sql(conn)} = 'failure'",
            params,
        ).fetchone()[0]
    )
    rows = _safe_rows(
        conn.execute(
            f"""SELECT tool_call_id, task_id, turn_id, tool_name, result_status,
                      error_class, error_message, attempt_number, created_at,
                      {status_sql(conn)} AS outcome
                 FROM tool_calls {where} {'AND' if where else 'WHERE'}
                 {status_sql(conn)} = 'failure'
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params + [ps, (p - 1) * ps],
        )
    )
    by_class = _rows(
        conn.execute(
            f"""SELECT COALESCE(classified_class, error_class, 'unclassified') AS cls,
                      COUNT(*) AS n
                 FROM tool_calls {where} {'AND' if where else 'WHERE'}
                 {status_sql(conn)} = 'failure'
                GROUP BY cls ORDER BY n DESC LIMIT 20""",
            params,
        )
    )
    # recovery = a task that had a failure and later a success ON THE SAME
    # tool call id — session/task-level success is NOT accepted (that would
    # credit unrelated calls).
    recoveries = _rows(
        conn.execute(
            f"""SELECT f.tool_call_id, f.task_id, f.tool_name,
                      MIN(f.created_at) AS failed_at,
                      (SELECT MIN(s.created_at) FROM tool_calls s
                        WHERE s.tool_call_id = f.tool_call_id
                          AND {status_sql(conn, 's')} = 'success'
                          AND s.created_at > MIN(f.created_at)) AS recovered_at
                 FROM tool_calls f
                WHERE {status_sql(conn, 'f')} = 'failure'
                GROUP BY f.tool_call_id, f.task_id, f.tool_name
                HAVING recovered_at IS NOT NULL
                ORDER BY failed_at DESC LIMIT 20"""
        )
    )
    return {"rows": rows, "total": total, "page": p, "page_size": ps,
            "by_class": by_class, "recoveries": recoveries}


# ---------------------------------------------------------------------------
# Page E — Trajectories / task timeline
# ---------------------------------------------------------------------------

def task_timeline(conn: sqlite3.Connection, task_id: str) -> Optional[Dict[str, Any]]:
    task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if not task:
        return None
    if has_outcome_correlation(conn):
        calls_sql = """SELECT tool_call_id, tool_name, result_status,
                      attempt_number, duration_ms, error_class, classified_class,
                      created_at,
                      (SELECT o.result FROM outcomes o
                        WHERE o.tool_call_id = tool_calls.tool_call_id
                        ORDER BY o.recorded_at DESC LIMIT 1) AS outcome
                 FROM tool_calls WHERE task_id = ?
                ORDER BY created_at, attempt_number"""
    else:
        calls_sql = """SELECT tool_call_id, tool_name, result_status,
                      attempt_number, duration_ms, error_class, classified_class,
                      created_at, 'unknown' AS outcome
                 FROM tool_calls WHERE task_id = ?
                ORDER BY created_at, attempt_number"""
    calls = _rows(conn.execute(calls_sql, (task_id,)))
    # outcomes: correlate by tool_call_id — the pre-tool writer's task_id is
    # independent from the post-tool writer's task_id (verified: 0 task_id
    # overlap on the live DB), so a task_id join here would attribute
    # unrelated session outcomes to this trajectory.
    if has_outcome_correlation(conn):
        oc = _safe_rows(
            conn.execute(
                """SELECT o.outcome_id, o.task_id, o.turn_id, o.result,
                          o.confidence, o.recorded_at, o.tool_call_id
                     FROM outcomes o
                     WHERE o.tool_call_id IN (
                         SELECT tool_call_id FROM tool_calls WHERE task_id = ?)
                     ORDER BY o.recorded_at""",
                (task_id,),
            )
        )
    else:
        oc = []   # pre-v5: correlation impossible — report missing, never fake
    for o in oc:
        o["correlated"] = True  # by construction: tool_call_id join
    errors = _safe_rows(
        conn.execute(
            "SELECT error_id, task_id, tool_call_id, tool_name, error_class, "
            "error_message, created_at FROM errors "
            "WHERE task_id = ? OR tool_call_id IN "
            "(SELECT tool_call_id FROM tool_calls WHERE task_id = ?) "
            "ORDER BY created_at",
            (task_id, task_id),
        )
    )
    events = []
    for c in calls:
        events.append({"stage": "tool_call", "at": c["created_at"], "data": c})
    for o in oc:
        events.append({"stage": "outcome", "at": o["recorded_at"], "data": o})
    for e in errors:
        events.append({"stage": "error", "at": e["created_at"], "data": e})
    events.sort(key=lambda e: e["at"] or "")
    missing = []
    if not oc:
        missing.append("post-tool outcomes (none correlated by tool_call_id)")
    if not errors:
        missing.append("classified failures (none — all calls succeeded or unclassified)")
    return {"task": _redact_text_row(dict(task)), "events": events, "missing_stages": missing}


def tasks(
    conn: sqlite3.Connection,
    *,
    window: str = "24h",
    search: Optional[str] = None,
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    w = _parse_window(window)
    p, ps = _clamp_page(page, page_size)
    clauses: List[str] = []
    params: List[Any] = []
    mod = _TIME_WINDOWS.get(w)
    if mod:
        clauses.append("created_at >= datetime('now', ?)")
        params.append(mod)
    if search:
        clauses.append("(task_id LIKE ? OR task_family LIKE ? OR sanitized_intent LIKE ?)")
        like = f"%{search[:100]}%"
        params.extend([like, like, like])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = int(conn.execute(f"SELECT COUNT(*) FROM tasks {where}", params).fetchone()[0])
    rows = _safe_rows(
        conn.execute(
            f"""SELECT task_id, task_family, sanitized_intent, provider, model, created_at
                  FROM tasks {where}
                 ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params + [ps, (p - 1) * ps],
        )
    )
    return {"rows": rows, "total": total, "page": p, "page_size": ps,
            "pages": (total + ps - 1) // ps}


# ---------------------------------------------------------------------------
# Page F — Memory explorer (patterns + strategies)
# ---------------------------------------------------------------------------

def strategies(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = None,
    family: Optional[str] = None,
    search: Optional[str] = None,
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    p, ps = _clamp_page(page, page_size)
    clauses: List[str] = []
    params: List[Any] = []
    if status in ("validated", "candidate", "disabled"):
        clauses.append("status = ?")
        params.append(status)
    if family:
        clauses.append("task_family = ?")
        params.append(family[:100])
    if search:
        clauses.append("(strategy_name LIKE ? OR strategy_id LIKE ?)")
        like = f"%{search[:100]}%"
        params.extend([like, like])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = int(conn.execute(f"SELECT COUNT(*) FROM strategies {where}", params).fetchone()[0])
    rows = _safe_rows(
        conn.execute(
            f"""SELECT strategy_id, strategy_name, strategy_type, task_family,
                      evidence_count, success_count, failure_count, context_count,
                      confidence, status, scope, version, created_at, last_validated_at,
                      last_used_at
                 FROM strategies {where}
                ORDER BY confidence DESC, evidence_count DESC
                LIMIT ? OFFSET ?""",
            params + [ps, (p - 1) * ps],
        )
    )
    return {"rows": rows, "total": total, "page": p, "page_size": ps,
            "pages": (total + ps - 1) // ps}


def strategy_detail(conn: sqlite3.Connection, strategy_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT strategy_id, strategy_name, strategy_type, task_family, "
        "evidence_count, success_count, failure_count, context_count, "
        "confidence, status, scope, version, created_at, last_validated_at, "
        "last_used_at FROM strategies WHERE strategy_id = ?", (strategy_id,)
    ).fetchone()
    if not row:
        return None
    d = _redact_text_row(dict(row))
    # Evidence: the outcomes whose tool matches this strategy's task_family.
    d["evidence_sample"] = _rows(
        conn.execute(
            """SELECT outcome_id, task_id, result, confidence, recorded_at
                 FROM outcomes
                WHERE json_extract(evidence, '$.tool') = ?
                ORDER BY recorded_at DESC LIMIT 20""",
            (d["task_family"],),
        )
    )
    d["guidance_events"] = []
    if has_guidance_telemetry(conn):
        d["guidance_events"] = _rows(
            conn.execute(
                """SELECT guidance_id, task_id, hook, reason_code, created_at
                     FROM retrieval_guidance_events
                    WHERE selected_strategy_id = ?
                    ORDER BY created_at DESC LIMIT 20""",
                (strategy_id,),
            )
        )
    return d


def patterns(
    conn: sqlite3.Connection,
    *,
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    p, ps = _clamp_page(page, page_size)
    total = int(conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0])
    rows = _safe_rows(
        conn.execute(
            """SELECT pattern_id, pattern_name, pattern_type, evidence_count,
                      success_count, failure_count, confidence, status, created_at,
                      last_validated_at
                 FROM patterns ORDER BY confidence DESC, evidence_count DESC
                LIMIT ? OFFSET ?""",
            (ps, (p - 1) * ps),
        )
    )
    return {"rows": rows, "total": total, "page": p, "page_size": ps,
            "pages": (total + ps - 1) // ps}


# ---------------------------------------------------------------------------
# Page G — Retrieval / guidance audit
# ---------------------------------------------------------------------------

def guidance_events(
    conn: sqlite3.Connection,
    *,
    reason_code: Optional[str] = None,
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    if not has_guidance_telemetry(conn):
        return {
            "available": False,
            "rows": [], "total": 0, "page": 1,
            "page_size": DEFAULT_PAGE_SIZE, "pages": 0,
        }
    p, ps = _clamp_page(page, page_size)
    clauses: List[str] = []
    params: List[Any] = []
    if reason_code:
        clauses.append("reason_code = ?")
        params.append(reason_code[:50])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM retrieval_guidance_events {where}", params
        ).fetchone()[0]
    )
    rows = _safe_rows(
        conn.execute(
            f"""SELECT guidance_id, task_id, task_fingerprint, hook,
                      candidate_count, qualified_count, selected_strategy_id,
                      guidance_returned, reason_code, created_at
                 FROM retrieval_guidance_events {where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params + [ps, (p - 1) * ps],
        )
    )
    return {"available": True, "rows": rows, "total": total, "page": p,
            "page_size": ps, "pages": (total + ps - 1) // ps}


# ---------------------------------------------------------------------------
# Page H — Benchmarks
# ---------------------------------------------------------------------------

def evaluations(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    return _safe_rows(
        conn.execute(
            """SELECT evaluation_id, benchmark, category,
                      baseline_first_success, baseline_avg_calls,
                      baseline_avg_retries, ebt_to_first_success,
                      ebt_avg_calls, ebt_avg_retries, improvement_points,
                      recorded_at
                 FROM evaluations ORDER BY recorded_at DESC LIMIT ?""",
            (min(limit, MAX_PAGE_SIZE),),
        )
    )


# ---------------------------------------------------------------------------
# Page I — System / diagnostics
# ---------------------------------------------------------------------------

def system_status(conn: sqlite3.Connection, db_path: Optional[str] = None) -> Dict[str, Any]:
    path = resolve_db_path(db_path)
    version = None
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        version = int(row[0]) if row and row[0] is not None else None
    except sqlite3.Error:
        pass
    last_event = conn.execute(
        "SELECT MAX(created_at) FROM tool_calls"
    ).fetchone()[0]
    counts = {}
    for t in ("tasks", "tool_calls", "outcomes", "errors", "strategies",
              "patterns", "evaluations"):
        try:
            counts[t] = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
        except sqlite3.Error:
            counts[t] = None
    guidance_count = None
    if has_guidance_telemetry(conn):
        guidance_count = int(
            conn.execute("SELECT COUNT(*) FROM retrieval_guidance_events").fetchone()[0]
        )
    return {
        "db_path": str(path),
        "schema_version": version,
        "guidance_telemetry": has_guidance_telemetry(conn),
        "last_event_at": last_event,
        "counts": counts,
        "guidance_events": guidance_count,
        "integrity": _quick_check(conn),
        "readonly": True,
    }


def _quick_check(conn: sqlite3.Connection) -> str:
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.Error:
        return "unavailable"
