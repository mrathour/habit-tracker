-- Initial schema (PLAN.md section 11).
--
-- Every timestamp is ISO 8601 UTC ending in "Z", for example 2026-10-17T12:11:00.000Z.
-- The CHECK constraints enforce that, so a local-time value can never be stored by mistake.

CREATE TABLE work_logs (
    page_id          TEXT PRIMARY KEY NOT NULL,  -- Notion page UUID
    display_id       TEXT,
    task_name        TEXT,
    start_utc        TEXT CHECK (start_utc IS NULL OR start_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]*Z'),
    end_utc          TEXT CHECK (end_utc IS NULL OR end_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]*Z'),
    parent_task_id   TEXT,
    logged_minutes   REAL,
    -- {property_id: {name, type, value}}
    extra_fields     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extra_fields) AND json_type(extra_fields) = 'object'),
    -- [{field, code, message}]
    issues           TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(issues) AND json_type(issues) = 'array'),
    created_time     TEXT NOT NULL CHECK (created_time GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]*Z'),
    last_edited_time TEXT NOT NULL CHECK (last_edited_time GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]*Z'),
    synced_at        TEXT NOT NULL CHECK (synced_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]*Z')
) STRICT;

CREATE INDEX idx_work_logs_start_utc ON work_logs (start_utc);
CREATE INDEX idx_work_logs_parent_task_id ON work_logs (parent_task_id);

-- Key-value settings; every value is JSON. Tokens are never stored here (PLAN.md 12.5).
CREATE TABLE settings (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL CHECK (json_valid(value))
) STRICT;
