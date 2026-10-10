-- Migration 3: make error persistence idempotent on the natural business key.
--
-- ``errors.error_id`` is a random surrogate generated per call, so a redelivered
-- tool_call_id (retry, replayed turn, second observer) would append a second
-- row for the SAME failure. The logical identity of a failure is
-- (task_id, turn_id, tool_call_id) — one tool call produces at most one error.
--
-- Existing rows are de-duplicated first (keeping the earliest created_at, which
-- is the first observation) so the UNIQUE index can be created on legacy data.
-- A NULL/empty tool_call_id (legacy rows written before the field was always
-- populated) cannot be de-duplicated safely, so those rows are left untouched
-- by the index: SQLite treats NULLs as distinct in a UNIQUE index.

DELETE FROM errors
 WHERE id NOT IN (
   SELECT MIN(id) FROM errors
    WHERE tool_call_id IS NOT NULL AND tool_call_id <> ''
    GROUP BY task_id, turn_id, tool_call_id
 )
   AND tool_call_id IS NOT NULL AND tool_call_id <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_errors_logical_key
    ON errors(task_id, turn_id, tool_call_id)
    WHERE tool_call_id IS NOT NULL AND tool_call_id <> '';
