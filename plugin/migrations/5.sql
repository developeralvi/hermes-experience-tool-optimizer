-- Migration 5: per-tool-call outcome correlation.
--
-- The pre-tool hook (pre_tool_call) writes `tool_calls` with the recorder's
-- OWN generated task_id, while the post-tool hook (post_tool_call) writes
-- `outcomes` with the session-scoped kwargs task_id. Those two task ids are
-- INDEPENDENT (verified on a live database: the task_id intersection of
-- tool_calls x outcomes is 0), so a task_id join cannot attribute an outcome
-- to the tool call it belongs to — a session-level success used to mark
-- every call in that session as successful.
--
-- `tool_call_id` IS genuinely shared: both hooks receive Hermes' per-
-- invocation tool_call_id (verified: all `errors` rows join `tool_calls` on
-- tool_call_id with zero task_id joins). This migration adds the column to
-- `outcomes` so the dashboard can join on it directly.
--
-- Purely additive and fail-safe: existing v1-v4 databases keep every row;
-- the plugin's outcome writes tolerate a missing column (the dashboard then
-- reports outcomes as UNKNOWN instead of misattributing them).

ALTER TABLE outcomes ADD COLUMN tool_call_id TEXT;

CREATE INDEX IF NOT EXISTS idx_outcomes_tool_call
    ON outcomes(tool_call_id);
