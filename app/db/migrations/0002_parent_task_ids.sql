-- Every page linked in the parent task relation (PLAN.md 4.1, 8).
--
-- parent_task_id keeps the first linked page, which the app shows as the parent task. When an
-- entry links several pages, all of them are kept here, in Notion's order, so none is dropped.
-- The raw log (Phase 7) shows the first link and a "+N more" list of the others.

ALTER TABLE work_logs ADD COLUMN parent_task_ids TEXT NOT NULL DEFAULT '[]'
    CHECK (json_valid(parent_task_ids) AND json_type(parent_task_ids) = 'array');
