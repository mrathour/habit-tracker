import type { RawLogColumn, RawLogPage, RawLogRow } from "../bridge/types";

function column(
  key: string,
  label: string,
  kind: RawLogColumn["kind"],
  extra: Partial<RawLogColumn> = {},
): RawLogColumn {
  return {
    key,
    label,
    kind,
    type: null,
    type_label: null,
    filter: null,
    options: [],
    ...extra,
  };
}

export const rawLogColumns: RawLogColumn[] = [
  column("display_id", "ID", "display_id"),
  column("task_name", "Task name", "task_name"),
  column("start", "Start", "start"),
  column("end", "End", "end"),
  column("duration", "Duration", "duration"),
  column("logged_minutes", "Logged minutes", "logged_minutes"),
  column("parent_task", "Parent task", "parent_task"),
  column("extra:mood", "Mood", "extra", {
    type: "select",
    type_label: "Select",
    filter: "options",
    options: ["Focused", "Tired"],
  }),
  column("extra:notes", "Notes", "extra", {
    type: "rich_text",
    type_label: "Text",
    filter: "text",
  }),
  column("extra:score", "Score", "extra", {
    type: "number",
    type_label: "Number",
    filter: "number",
  }),
  column("extra:due", "Due", "extra", { type: "date", type_label: "Date", filter: "date" }),
  column("extra:bill", "Billable", "extra", {
    type: "checkbox",
    type_label: "Checkbox",
    filter: "checkbox",
  }),
  column("extra:rel", "Related", "extra", {
    type: "relation",
    type_label: "Relation",
    filter: "presence",
  }),
  column("overlap", "Overlap", "overlap"),
  column("issues", "Issues", "issues"),
];

const base: RawLogRow = {
  page_id: "p0",
  url: "https://www.notion.so/p0",
  display_id: null,
  task_name: null,
  start_utc: null,
  end_utc: null,
  duration_minutes: null,
  logged_minutes: null,
  parent_task_ids: [],
  parent_urls: [],
  extras: {},
  issues: [],
  overlap_minutes: 0,
  overlaps_with: [],
};

/** Times are UTC; the fixtures' time zone is India (UTC+5:30). */
export const rawLogRows: RawLogRow[] = [
  {
    ...base,
    page_id: "p4",
    url: "https://www.notion.so/p4",
    display_id: "3",
    task_name: "No end",
    start_utc: "2026-10-22T03:00:00.000Z",
    issues: [{ field: "end", code: "missing_time", message: "End time is empty." }],
  },
  {
    ...base,
    page_id: "p3",
    url: "https://www.notion.so/p3",
    display_id: "10",
    task_name: "Réunion équipe",
    start_utc: "2026-10-21T17:30:00.000Z",
    end_utc: "2026-10-21T19:30:00.000Z",
    duration_minutes: 120,
    logged_minutes: 200,
    extras: { notes: { text: "日本語のメモ" } },
    issues: [
      {
        field: "logged_minutes",
        code: "duration_mismatch",
        message: "Logged 200 min, but Start → End is 120 min.",
      },
    ],
  },
  {
    ...base,
    page_id: "p2",
    url: "https://www.notion.so/p2",
    display_id: "2",
    start_utc: "2026-10-20T04:30:00.000Z",
    end_utc: "2026-10-20T05:30:00.000Z",
    duration_minutes: 60,
    logged_minutes: 60,
    parent_task_ids: ["t2", "t1"],
    parent_urls: ["https://www.notion.so/t2", "https://www.notion.so/t1"],
    extras: { mood: { text: "Tired" }, bill: { text: "No" } },
    overlap_minutes: 30,
    overlaps_with: [{ page_id: "p1", label: "#1 Write docs" }],
  },
  {
    ...base,
    page_id: "p1",
    url: "https://www.notion.so/p1",
    display_id: "1",
    task_name: "Write docs",
    start_utc: "2026-10-20T03:30:00.000Z",
    end_utc: "2026-10-20T05:00:00.000Z",
    duration_minutes: 90,
    logged_minutes: 90,
    parent_task_ids: ["t1"],
    parent_urls: ["https://www.notion.so/t1"],
    extras: {
      mood: { text: "Focused" },
      bill: { text: "Yes" },
      due: {
        text: "2026-10-25 09:30",
        start: { utc: "2026-10-25T04:00:00.000Z", date: "2026-10-25", has_time: true },
        end: null,
      },
      rel: {
        text: "2 linked pages",
        links: ["https://www.notion.so/r1", "https://www.notion.so/r2"],
      },
    },
    overlap_minutes: 30,
    overlaps_with: [{ page_id: "p2", label: "#2 Untitled" }],
  },
  {
    ...base,
    page_id: "p5",
    url: "https://www.notion.so/p5",
    display_id: "WL-4",
    task_name: "Backwards",
    start_utc: "2026-10-19T05:00:00.000Z",
    end_utc: "2026-10-19T04:53:00.000Z",
    issues: [
      { field: "end", code: "invalid_range", message: "End time is 7 min before Start time." },
    ],
  },
];

export const rawLogPage: RawLogPage = {
  time_zone: "Asia/Kolkata",
  total_entries: rawLogRows.length,
  matched: rawLogRows.length,
  offset: 0,
  rows: rawLogRows,
  sort: { column: "start", direction: "desc" },
  columns: rawLogColumns,
  parents: [
    { page_id: "t1", url: "https://www.notion.so/t1", entries: 2, latest_task_name: null },
    { page_id: "t2", url: "https://www.notion.so/t2", entries: 1, latest_task_name: null },
  ],
  view: { sort: { column: "start", direction: "desc" }, widths: {}, hidden: [] },
};

export const emptyRawLog: RawLogPage = {
  ...rawLogPage,
  total_entries: 0,
  matched: 0,
  rows: [],
  parents: [],
};
