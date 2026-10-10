-- Migration 4: retrieval/guidance lifecycle telemetry.
--
-- The plugin records tool calls and outcomes, and `record_retrieval()` exists
-- in the storage layer, but no runtime path ever called it: `retrieval_events`
-- stayed at 0 rows in every real installation, so the dashboard could not
-- distinguish "retrieval happened" from "guidance was returned by the hook".
--
-- This migration is purely additive: it adds a table the runtime can write to
-- (see plugins/__init__.py::_record_retrieval_event) without changing any
-- existing table, index, or row. Installations that never upgrade past v3
-- keep working; the plugin's writes are wrapped so a missing table degrades
-- to a debug log line, never an exception.
--
-- `reason_code` uses a fixed vocabulary so the dashboard can group outcomes
-- without parsing free text:
--   none                     - no hook ran retrieval (mode=off / record_only)
--   no_candidate             - retrieval ran, no pattern/strategy matched
--   candidate_below_threshold- a candidate existed but was not qualified
--   qualified_not_selected   - qualified strategies existed, none selected
--   guidance_constructed     - a directive hint was built
--   guidance_returned        - the hook actually returned guidance

CREATE TABLE IF NOT EXISTS retrieval_guidance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guidance_id TEXT NOT NULL UNIQUE,
    task_id TEXT,
    task_fingerprint TEXT NOT NULL,
    hook TEXT NOT NULL,                -- pre_llm_call | pre_tool_call
    candidate_count INTEGER NOT NULL DEFAULT 0,
    qualified_count INTEGER NOT NULL DEFAULT 0,
    selected_strategy_id TEXT,
    guidance_returned INTEGER NOT NULL DEFAULT 0,
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_guidance_task
    ON retrieval_guidance_events(task_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_guidance_reason
    ON retrieval_guidance_events(reason_code);
CREATE INDEX IF NOT EXISTS idx_retrieval_guidance_strategy
    ON retrieval_guidance_events(selected_strategy_id);
