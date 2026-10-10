-- Migration 2: task-family scoping for strategies.
--
-- Retrieval must be task-scoped, not tool-scoped: the pre-LLM hook derives a
-- coarse task family from the user's message (file_edit, shell, search, ...),
-- while a strategy's `sequence` names concrete tools (read_file, write_file).
-- Matching family -> tool made every pre-LLM lookup miss, so guidance could never
-- reach the model and the Run-1 -> Run-2 loop was impossible.
--
-- Additive only: existing rows default to '' (unknown family) and remain readable
-- by the tool-scoped path, so no existing database is invalidated.
ALTER TABLE strategies ADD COLUMN task_family TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_strategies_family
    ON strategies(task_family, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_strategies_family_status
    ON strategies(task_family, status);
