-- Migration 3: make error persistence idempotent on the natural business key.
--
-- ``errors.error_id`` is a random surrogate generated per call, so a redelivered
-- tool_call_id (retry, replayed turn, second observer) would append a second
-- row for the SAME failure. The logical identity of a failure is
-- (task_id, turn_id, tool_call_id) — one tool call produces at most one error.
--
-- Step 1: de-duplicate existing rows (keep earliest created_at per triple).
-- NULL/empty tool_call_id rows cannot be safely de-duplicated (SQLite treats
-- NULLs as distinct in a UNIQUE index), so those are left untouched.
--
-- Step 2: create a UNIQUE index on (task_id, turn_id, tool_call_id). Because
-- going-forward code always populates tool_call_id, a full (non-partial) index
-- is safe and lets INSERT OR IGNORE detect duplicates at the DB level.

-- De-duplicate: keep the earliest-created row per (task_id, turn_id, tool_call_id)
DELETE FROM errors
 WHERE id NOT IN (
   SELECT MIN(id) FROM errors
    WHERE tool_call_id IS NOT NULL AND tool_call_id <> ''
    GROUP BY task_id, turn_id, tool_call_id
 )
   AND tool_call_id IS NOT NULL AND tool_call_id <> '';

-- Now safe: full UNIQUE index on the logical key (no WHERE clause needed
-- because going-forward code always sets tool_call_id).
CREATE UNIQUE INDEX IF NOT EXISTS idx_errors_logical_key
    ON errors(task_id, turn_id, tool_call_id);
