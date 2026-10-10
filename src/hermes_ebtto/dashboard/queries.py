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

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_ebtto.storage import DEFAULT_DB_NAME, get_storage_path

# Bound result sizes — the UI must never be able to pull the whole DB.
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

_TIME_WINDOWS = {
    "1h": "-1 hour",
    "24h": "-1 day",
    "7d": "-7 days",
    "30d": "-30 days",
    "all": None,
}


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
    _set_flag(conn, "has_guidance_telemetry", "retrieval_guidance_events" in have)


def _set_flag(conn: sqlite3.Connection, name: str, value: bool) -> None:
    """Attach a capability flag to a connection (sqlite3.Connection forbids
    attribute assignment; keep the mapping in this module)."""
    _FLAGS[id(conn)] = value
    _FLAG_OWNER.setdefault(id(conn), conn)


def has_guidance_telemetry(conn: sqlite3.Connection) -> bool:
    """True when the connection points at a schema-v4+ database."""
    return bool(_FLAGS.get(id(conn), False))


# connection -> capability flag map (module-level because sqlite3.Connection
# objects do not accept custom attributes)
_FLAGS: dict = {}
_FLAG_OWNER: dict = {}


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

def _succeeded_sql() -> str:
    """SQL predicate for a successful tool call.

    The production schema records pre-tool rows with ``result_status =
    'PENDING'`` and writes the true outcome to the ``outcomes`` table. The
    two writers assign INDEPENDENT task ids (pre-tool generates its own via
    the recorder; post-tool uses the session-scoped kwargs task_id), so the
    only reliable linkage is the session id embedded at the start of both
    ``turn_id`` values (``<session>:<...>:<...>``). Success is therefore
    judged as: the session of this tool call has any SUCCESS outcome.
    ``result_status IN ('ok','success')`` remains as a fallback for
    synthetic/direct writes (e.g. tests).
    """
    return (
        "(EXISTS (SELECT 1 FROM outcomes o "
        " WHERE substr(o.turn_id, 1, instr(o.turn_id, ':') - 1) = "
        "       substr(tool_calls.turn_id, 1, instr(tool_calls.turn_id, ':') - 1) "
        "   AND o.result = 'SUCCESS') "
        " OR tool_calls.result_status IN ('ok','success'))"
    )


def overview(conn: sqlite3.Connection, window: str = "24h") -> Dict[str, Any]:
    w = _parse_window(window)
    where, params = _time_clause(w)
    ok_pred = _succeeded_sql()

    total = int(conn.execute(f"SELECT COUNT(*) FROM tool_calls {where}", params).fetchone()[0])
    succeeded = int(conn.execute(
        f"SELECT COUNT(*) FROM tool_calls {where} {'AND' if where else 'WHERE'} {ok_pred}",
        params,
    ).fetchone()[0])
    failed = total - succeeded

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
                      SUM(CASE WHEN """ + _succeeded_sql() + """ THEN 1 ELSE 0 END) AS ok,
                      SUM(CASE WHEN """ + _succeeded_sql() + """ THEN 0 ELSE 1 END) AS fail
                 FROM tool_calls
                WHERE created_at >= datetime('now', '-14 days')
                GROUP BY day ORDER BY day"""
        )
    )
    top_tools = _rows(
        conn.execute(
            f"""SELECT tool_name,
                       COUNT(*) AS calls,
                       SUM(CASE WHEN {ok_pred} THEN 1 ELSE 0 END) AS ok,
                       SUM(CASE WHEN {ok_pred} THEN 0 ELSE 1 END) AS fail
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

    return {
        "window": w,
        "tool_calls": {"total": total, "succeeded": succeeded, "failed": failed},
        "success_rate": (succeeded / total) if total else None,
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
        clauses.append(_succeeded_sql())
    elif status == "failure":
        clauses.append(f"NOT {_succeeded_sql()}")
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
    rows = _rows(
        conn.execute(
            f"""SELECT tool_call_id, task_id, turn_id, tool_name, result_status,
                       duration_ms, attempt_number, error_class, error_message,
                       classified_class, created_at
                  FROM tool_calls {where}
                 ORDER BY created_at DESC, tool_call_id DESC
                 LIMIT ? OFFSET ?""",
            params + [ps, (p - 1) * ps],
        )
    )
    return {"rows": rows, "total": total, "page": p, "page_size": ps,
            "pages": (total + ps - 1) // ps}


def tool_call_detail(conn: sqlite3.Connection, tool_call_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """SELECT * FROM tool_calls WHERE tool_call_id = ?""", (tool_call_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["outcomes"] = _rows(
        conn.execute(
            "SELECT * FROM outcomes WHERE task_id = ?", (d["task_id"],)
        )
    )
    d["errors"] = _rows(
        conn.execute(
            "SELECT * FROM errors WHERE tool_call_id = ?", (tool_call_id,)
        )
    )
    d["attempts"] = _rows(
        conn.execute(
            """SELECT tool_call_id, attempt_number, result_status, duration_ms,
                      error_class, created_at
                 FROM tool_calls
                WHERE task_id = ? AND tool_name = ?
                ORDER BY attempt_number""",
            (d["task_id"], d["tool_name"]),
        )
    )
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
            f"NOT {_succeeded_sql()}",
            params,
        ).fetchone()[0]
    )
    rows = _rows(
        conn.execute(
            f"""SELECT tool_call_id, task_id, tool_name, result_status,
                      error_class, error_message, attempt_number, created_at
                 FROM tool_calls {where} {'AND' if where else 'WHERE'}
                 NOT {_succeeded_sql()}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params + [ps, (p - 1) * ps],
        )
    )
    by_class = _rows(
        conn.execute(
            f"""SELECT COALESCE(classified_class, error_class, 'unclassified') AS cls,
                      COUNT(*) AS n
                 FROM tool_calls {where} {'AND' if where else 'WHERE'}
                 NOT {_succeeded_sql()}
                GROUP BY cls ORDER BY n DESC LIMIT 20""",
            params,
        )
    )
    # recovery = a task that had a failure and later a success on the same tool
    # (success judged against the outcomes table, matching _succeeded_sql)
    recoveries = _rows(
        conn.execute(
            "SELECT f.task_id, f.tool_name, "
            "MIN(f.created_at) AS failed_at, "
            "(SELECT MIN(s.created_at) FROM tool_calls s "
            "  WHERE s.task_id = f.task_id AND s.tool_name = f.tool_name "
            "    AND s.result_status IN ('ok','success') "
            "    AND s.created_at > MIN(f.created_at)) AS recovered_at "
            "FROM tool_calls f "
            "WHERE NOT " + _succeeded_sql().replace("tool_calls.", "f.") + " "
            "GROUP BY f.task_id, f.tool_name "
            "HAVING recovered_at IS NOT NULL "
            "ORDER BY failed_at DESC LIMIT 20"
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
    calls = _rows(
        conn.execute(
            """SELECT tool_call_id, tool_name, result_status, attempt_number,
                      duration_ms, error_class, classified_class, created_at
                 FROM tool_calls WHERE task_id = ?
                ORDER BY created_at, attempt_number""",
            (task_id,),
        )
    )
    outcomes = _rows(
        conn.execute(
            "SELECT * FROM outcomes WHERE task_id = ? ORDER BY recorded_at", (task_id,)
        )
    )
    errors = _rows(
        conn.execute(
            "SELECT * FROM errors WHERE task_id = ? ORDER BY created_at", (task_id,)
        )
    )
    events = []
    for c in calls:
        events.append({"stage": "tool_call", "at": c["created_at"], "data": c})
    for o in outcomes:
        events.append({"stage": "outcome", "at": o["recorded_at"], "data": o})
    for e in errors:
        events.append({"stage": "error", "at": e["created_at"], "data": e})
    events.sort(key=lambda e: e["at"] or "")
    missing = []
    if not outcomes:
        missing.append("post-tool outcomes (none persisted for this task)")
    if not errors:
        missing.append("classified failures (none — all calls succeeded or unclassified)")
    return {"task": dict(task), "events": events, "missing_stages": missing}


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
    rows = _rows(
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
    rows = _rows(
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
        "SELECT * FROM strategies WHERE strategy_id = ?", (strategy_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
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
    rows = _rows(
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
    rows = _rows(
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
    return _rows(
        conn.execute(
            """SELECT * FROM evaluations ORDER BY recorded_at DESC LIMIT ?""",
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
