"""SQLite storage layer for EBTTO.

Design:
* Local-first, zero external dependencies, single file.
* WAL mode for concurrent readers + single writer.
* busy_timeout for lock contention.
* Foreign keys ON.
* Migrations versioned in ``db/migrations`` (numbered, applied once).
* Crash-safe: all writes through transactions; no partial writes on abort.

Database lives at ``<storage_path>/ebtto.db``. The directory is created on
open. The file is portable and can be backed up with ``VACUUM INTO``.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from hermes_ebtto import events as ev

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB_NAME = "ebtto.db"
WAL_MODE = "wal"
BUSY_TIMEOUT_MS = 5000

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class _Connection:
    """Thread-local connection with WAL+busy_timeout+FK enabled."""

    __slots__ = ("_conn", "row_factory")

    def __init__(self, uri: str):
        self._conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000.0)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def executescript(self, sql: str) -> None:
        self._conn.executescript(sql)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _get_conn(storage_path: Path) -> sqlite3.Connection:
    uri = f"file:{storage_path.as_posix()}?mode=rwc"
    # Always create a fresh connection. sqlite3 connections are not guaranteed to
    # be reusable after a prior thread has closed them; caching leads to stale
    # connections that return stale data (the "SELECT 1" probe succeeds on a
    # closed-but-not-yet-collectable connection). Create one connection per call
    # and let the GC reclaim it.
    conn = _Connection(uri)
    return conn._conn


def get_storage_path() -> Path:
    """Storage directory: ``$HERMES_HOME/.hermes-ebtto`` + db file.

    Never writes outside the Hermes home directory.
    """
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        base = Path(env_home).expanduser()
    else:
        # Resolve ~ explicitly to the real home so that MSYS/bash doesn't pass a
        # literal "~" to Path, which sqlite3 would treat as an invalid relative path.
        try:
            base = Path(os.path.expanduser("~")).resolve()
        except Exception:
            base = Path.cwd().resolve()
    return base / ".hermes-ebtto"


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _migration_files() -> List[Path]:
    if not MIGRATIONS_DIR.is_dir():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: int(p.stem))


def _apply_migration(conn: sqlite3.Connection, version: int) -> None:
    path = MIGRATIONS_DIR / f"{version}.sql"
    if not path.exists():
        return
    conn.executescript(path.read_text(encoding="utf-8"))


def ensure_schema(storage_path: Optional[Path] = None) -> int:
    """Open (creating if needed) the DB, apply migrations, return current version."""
    storage_path = Path(storage_path or get_storage_path())
    storage_path.mkdir(parents=True, exist_ok=True)
    db_path = storage_path / DEFAULT_DB_NAME
    # "rwc" = read-write + create (mode=rw is not accepted by the installed
    # SQLite version).
    uri = f"file:{db_path.as_posix()}?mode=rwc"
    conn = _Connection(uri)
    current = _read_version(conn)
    for m in _migration_files():
        if int(m.stem) > current:
            _apply_migration(conn._conn, int(m.stem))
            _write_version(conn, int(m.stem))
            current = int(m.stem)
    conn.commit()
    conn.close()
    return current


def _read_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT version FROM schema_version ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["version"]) if row else 0


def _write_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (version, _utcnow_iso()),
    )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    task_fingerprint TEXT NOT NULL,
    task_family TEXT NOT NULL,
    sanitized_intent TEXT,
    workspace_identifier TEXT,
    profile TEXT,
    model TEXT,
    provider TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    start_timestamp TEXT NOT NULL,
    start_epoch_ms INTEGER NOT NULL,
    end_timestamp TEXT,
    end_epoch_ms INTEGER,
    tool_count INTEGER NOT NULL DEFAULT 0,
    total_duration_ms INTEGER NOT NULL DEFAULT 0,
    outcome TEXT
);

CREATE INDEX IF NOT EXISTS idx_turns_task ON turns(task_id);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_call_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    order_number INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    tool_name TEXT NOT NULL,
    raw_args TEXT NOT NULL,
    sanitized_args TEXT NOT NULL,
    result_status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error_class TEXT,
    error_message TEXT,
    classified INTEGER NOT NULL DEFAULT 0,
    classified_class TEXT,
    classifier_version TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_turn ON tool_calls(turn_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool_name);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    result TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence TEXT,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outcomes_task ON outcomes(task_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_result ON outcomes(result);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    error_class TEXT NOT NULL,
    confidence REAL NOT NULL,
    error_message TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_errors_task ON errors(task_id);
CREATE INDEX IF NOT EXISTS idx_errors_class ON errors(error_class);

CREATE TABLE IF NOT EXISTS trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trajectory_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    task_fingerprint TEXT NOT NULL,
    task_family TEXT NOT NULL,
    tool_calls_json TEXT NOT NULL,
    outcome TEXT,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    total_duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_trajectories_family ON trajectories(task_family);
CREATE INDEX IF NOT EXISTS idx_trajectories_fingerprint ON trajectories(task_fingerprint);

CREATE TABLE IF NOT EXISTS tool_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL UNIQUE,
    average_success REAL NOT NULL DEFAULT 0,
    first_pass_success REAL NOT NULL DEFAULT 0,
    recovery_success REAL NOT NULL DEFAULT 0,
    average_duration_ms INTEGER NOT NULL DEFAULT 0,
    call_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS task_families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_family TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL UNIQUE,
    strategy_name TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    sequence TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    context_count INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    last_validated_at TEXT,
    last_used_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    scope TEXT NOT NULL DEFAULT 'global',
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status);
CREATE INDEX IF NOT EXISTS idx_strategies_confidence ON strategies(confidence DESC);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id TEXT NOT NULL UNIQUE,
    pattern_name TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    last_validated_at TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_patterns_status ON patterns(status);

CREATE TABLE IF NOT EXISTS retrieval_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retrieval_id TEXT NOT NULL UNIQUE,
    task_fingerprint TEXT NOT NULL,
    retrieved_count INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_events_task ON learning_events(task_id);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id TEXT NOT NULL UNIQUE,
    benchmark TEXT NOT NULL,
    category TEXT NOT NULL,
    baseline_first_success REAL,
    baseline_avg_calls REAL,
    baseline_avg_retries REAL,
    ebt_to_first_success REAL,
    ebt_avg_calls REAL,
    ebt_avg_retries REAL,
    improvement_points REAL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluations_benchmark ON evaluations(benchmark);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    period TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);

CREATE TABLE IF NOT EXISTS regressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regression_id TEXT NOT NULL UNIQUE,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    degradation_start TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'degraded',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_regressions_strategy ON regressions(strategy_id);
"""


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class Store:
    """Thread-safe SQLite store. One connection per thread, transactions for writes."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = Path(storage_path or get_storage_path())
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_path / DEFAULT_DB_NAME
        self._ensure_ready()

    def _ensure_ready(self) -> None:
        # sqlite3.connect with uri=True requires a STRING uri, not a Path.
        # Use as_posix() so the Windows path has forward slashes (required by
        # the URI syntax). Backslash paths break the query string.
        # Create the directory first (the DB file may not exist yet).
        self.storage_path.mkdir(parents=True, exist_ok=True)
        db_string = self.db_path.as_posix()
        # "rwc" = read-write + create: opens a new or existing DB.
        # (mode=rw is not accepted by the installed SQLite version.)
        uri = f"file:{db_string}?mode=rwc"
        conn = _Connection(uri)
        # Read the current schema version (may fail if the DB is fresh).
        try:
            current = _read_version(conn._conn)
        except sqlite3.OperationalError:
            # Fresh database: the schema_version table does not exist yet.
            _create_schema(conn._conn)
            _write_version(conn._conn, SCHEMA_VERSION)
            current = SCHEMA_VERSION
        for m in _migration_files():
            if int(m.stem) > current:
                _apply_migration(conn._conn, int(m.stem))
                _write_version(conn._conn, int(m.stem))
                current = int(m.stem)
        conn.commit()
        conn.close()

    def close(self) -> None:
        """Close any open connections (best-effort)."""
        pass

    def __del__(self) -> None:
        self.close()

    def _conn(self) -> sqlite3.Connection:
        return _get_conn(self.db_path)

    def _execute(
        self, sql: str, params: Iterable[Any] = (), commit: bool = True
    ) -> sqlite3.Cursor:
        conn = self._conn()
        cur = conn.execute(sql, params)
        if commit:
            conn.commit()
        return cur

    def execute(self, sql: str, params: Iterable[Any] = (), commit: bool = True) -> sqlite3.Cursor:
        """Alias for _execute (public API)."""
        return self._execute(sql, params, commit)

    # ---- tasks -----------------------------------------------------------

    def record_task(self, task: ev.Task) -> str:
        data = ev.event_to_dict(task)
        data["sanitized_intent"] = task.sanitized_intent
        data["workspace_identifier"] = task.workspace_identifier
        data["profile"] = task.profile
        data["model"] = task.model
        data["provider"] = task.provider
        self._execute(
            """INSERT OR IGNORE INTO tasks
               (task_id, task_fingerprint, task_family, sanitized_intent,
                workspace_identifier, profile, model, provider, created_at)
               VALUES (:task_id, :task_fingerprint, :task_family, :sanitized_intent,
                       :workspace_identifier, :profile, :model, :provider, :created_at)""",
            data,
        )
        return task.event_id

    def task_exists(self, task_id: str) -> bool:
        row = self._execute(
            "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,), commit=False
        ).fetchone()
        return row is not None

    # ---- turns ---------------------------------------------------------

    def record_turn(self, turn: ev.Turn) -> str:
        self._execute(
            """INSERT INTO turns
               (turn_id, task_id, session_id, start_timestamp, start_epoch_ms,
                end_timestamp, end_epoch_ms, tool_count, total_duration_ms, outcome)
               VALUES (:turn_id, :task_id, :session_id, :start_timestamp,
                       :start_epoch_ms, :end_timestamp, :end_epoch_ms,
                       :tool_count, :total_duration_ms, :outcome)""",
            ev.event_to_dict(turn),
        )
        return turn.event_id

    def record_turn_end(self, turn_id: str, *, task_id: str,
                        end_timestamp: str, end_epoch_ms: int,
                        tool_count: int, total_duration_ms: int,
                        outcome: Optional[str]) -> None:
        self._execute(
            """UPDATE turns SET end_timestamp = ?, end_epoch_ms = ?, tool_count = ?,
               total_duration_ms = ?, outcome = ? WHERE turn_id = ? AND task_id = ?""",
            (end_timestamp, end_epoch_ms, tool_count, total_duration_ms,
             outcome, turn_id, task_id),
        )

    # ---- tool calls --------------------------------------------------

    def record_tool_call(self, call: ev.ToolCall) -> str:
        raw = call.raw_args
        san = call.sanitized_args
        evidence = call.evidence
        self._execute(
            """INSERT INTO tool_calls
               (tool_call_id, task_id, turn_id, order_number, attempt_number,
                tool_name, raw_args, sanitized_args, result_status, duration_ms,
                error_class, error_message, classified, classified_class,
                classifier_version, evidence, created_at)
               VALUES (:tool_call_id, :task_id, :turn_id, :order_number,
                       :attempt_number, :tool_name, :raw_args, :sanitized_args,
                       :result_status, :duration_ms, :error_class,
                       :error_message, :classified, :classified_class,
                       :classifier_version, :evidence, :created_at)""",
            {
                **ev.event_to_dict(call),
                "raw_args": self._json(raw),
                "sanitized_args": self._json(san),
                "evidence": self._json(evidence),
            },
        )
        return call.event_id

    @staticmethod
    def _json(obj: Any) -> str:
        if obj is None:
            return ""
        import json

        return json.dumps(obj, ensure_ascii=False, default=str)

    # ---- outcomes --------------------------------------------------

    def record_outcome(self, outcome: ev.Outcome) -> str:
        self._execute(
            """INSERT INTO outcomes
               (outcome_id, task_id, turn_id, result, confidence, evidence,
                recorded_at)
               VALUES (:outcome_id, :task_id, :turn_id, :result, :confidence,
                       :evidence, :recorded_at)""",
            {
                **ev.event_to_dict(outcome),
                "evidence": self._json(outcome.evidence),
            },
        )
        return outcome.event_id

    # ---- errors --------------------------------------------------

    def record_error(self, error: ev.Error) -> str:
        self._execute(
            """INSERT INTO errors
               (error_id, task_id, turn_id, tool_call_id, tool_name, error_class,
                confidence, error_message, evidence, created_at)
               VALUES (:error_id, :task_id, :turn_id, :tool_call_id, :tool_name,
                       :error_class, :confidence, :error_message, :evidence,
                       :created_at)""",
            {
                **ev.event_to_dict(error),
                "evidence": self._json(error.evidence),
            },
        )
        return error.event_id

    # ---- trajectories ----------------------------------------------

    def record_trajectory(self, traj: ev.Trajectory) -> str:
        self._execute(
            """INSERT OR REPLACE INTO trajectories
               (trajectory_id, task_id, task_fingerprint, task_family,
                tool_calls_json, outcome, success_count, failure_count,
                total_duration_ms, created_at, updated_at)
               VALUES (:trajectory_id, :task_id, :task_fingerprint,
                       :task_family, :tool_calls_json, :outcome, :success_count,
                       :failure_count, :total_duration_ms, :created_at,
                       :updated_at)""",
            {
                **ev.event_to_dict(traj),
                "tool_calls_json": self._json([ev.event_to_dict(c) for c in traj.tool_calls]),
                "outcome": traj.outcome,
            },
        )
        return traj.event_id

    def trajectory_by_task(self, task_id: str) -> Optional[ev.Trajectory]:
        row = self._execute(
            "SELECT * FROM trajectories WHERE task_id = ?", (task_id,), commit=False
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        return ev.Trajectory(
            task_id=data["task_id"],
            task_fingerprint=data["task_fingerprint"],
            task_family=data["task_family"],
            tool_calls=[ev.ToolCall(**c) for c in json_loads(data["tool_calls_json"])],
            outcome=data["outcome"],
            success_count=data["success_count"],
            failure_count=data["failure_count"],
            total_duration_ms=data["total_duration_ms"],
        )

    # ---- tool profiles -------------------------------------------

    def record_tool_profile(self, tool_name: str, *, average_success: float,
                            first_pass_success: float, recovery_success: float,
                            average_duration_ms: float, call_count: int,
                            last_seen_at: Optional[str]) -> None:
        self._execute(
            """INSERT INTO tool_profiles
               (tool_name, average_success, first_pass_success, recovery_success,
                average_duration_ms, call_count, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tool_name) DO UPDATE SET
               average_success = ?,
               first_pass_success = ?,
               recovery_success = ?,
               average_duration_ms = ?,
               call_count = ?,
               last_seen_at = ?""",
            (
                tool_name, average_success, first_pass_success, recovery_success,
                average_duration_ms, call_count, last_seen_at,
                average_success, first_pass_success, recovery_success,
                average_duration_ms, call_count, last_seen_at,
            ),
        )

    # ---- strategies ---------------------------------------------

    def record_strategy(self, strategy: ev.ToolCall) -> str:
        """Placeholder — strategies are strings; see ``learning`` module."""
        raise NotImplementedError

    # ---- patterns ---------------------------------------------

    def record_pattern(self, pattern: ev.ToolCall) -> str:
        raise NotImplementedError

    # ---- retrieval ---------------------------------------------

    def record_retrieval(self, retrieval_id: str, *, task_fingerprint: str,
                         retrieved_count: int) -> str:
        self._execute(
            """INSERT INTO retrieval_events
               (retrieval_id, task_fingerprint, retrieved_count, retrieved_at)
               VALUES (?, ?, ?, ?)""",
            (retrieval_id, task_fingerprint, retrieved_count, _utcnow_iso()),
        )
        return retrieval_id

    # ---- learning ---------------------------------------------

    def record_learning_event(self, event_type: str, payload: Dict[str, Any],
                              *, task_id: str) -> str:
        self._execute(
            """INSERT INTO learning_events
               (learning_id, task_id, event_type, payload, recorded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (ev.new_id(), task_id, event_type, self._json(payload), _utcnow_iso()),
        )
        return ev.new_id()

    # ---- evaluations -------------------------------------------

    def record_evaluation(self, benchmark: str, category: str,
                          *,
                          baseline_first_success: Optional[float],
                          baseline_avg_calls: Optional[float],
                          baseline_avg_retries: Optional[float],
                          ebt_to_first_success: Optional[float],
                          ebt_avg_calls: Optional[float],
                          ebt_avg_retries: Optional[float],
                          improvement_points: Optional[float]) -> str:
        self._execute(
            """INSERT INTO evaluations
               (evaluation_id, benchmark, category, baseline_first_success,
                baseline_avg_calls, baseline_avg_retries, ebt_to_first_success,
                ebt_avg_calls, ebt_avg_retries, improvement_points,
                recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ev.new_id(), benchmark, category,
                baseline_first_success, baseline_avg_calls, baseline_avg_retries,
                ebt_to_first_success, ebt_avg_calls, ebt_avg_retries,
                improvement_points, _utcnow_iso(),
            ),
        )
        return ev.new_id()

    # ---- metrics ---------------------------------------------

    def record_metric(self, metric_name: str, value: float,
                      period: str) -> str:
        self._execute(
            """INSERT INTO metrics
               (metric_name, value, period, recorded_at)
               VALUES (?, ?, ?, ?)""",
            (metric_name, value, period, _utcnow_iso()),
        )
        return ev.new_id()

    # ---- regressions ------------------------------------------

    def record_regression(self, strategy_id: str, strategy_name: str,
                          *, degradation_start: str,
                          evidence: Optional[Dict[str, Any]] = None,
                          status: str = "degraded") -> str:
        self._execute(
            """INSERT INTO regressions
               (regression_id, strategy_id, strategy_name, degradation_start,
                evidence, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ev.new_id(), strategy_id, strategy_name, degradation_start,
             self._json(evidence) if evidence else None, status, _utcnow_iso()),
        )
        return ev.new_id()

    # ---- migrations ----------------------------------------------

    def migrations(self) -> List[Dict[str, Any]]:
        rows = self._execute(
            "SELECT version, applied_at FROM schema_version ORDER BY id"
        ).fetchall()
        return [{"version": r["version"], "applied_at": r["applied_at"]}
                for r in rows]
