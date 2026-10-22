import { callPython } from "../bridge/client";
import type { Issue, RawLogColumn, RawLogRow } from "../bridge/types";
import { noticeFromCallError } from "../errors/reporting";
import { extraText, formatMinutes, formatStamp } from "./format";

export function openInNotion(url: string) {
  callPython("open_external", url).catch((error: unknown) => {
    noticeFromCallError(error, "Notion couldn't be opened");
  });
}

/** The issues shown in a column's cell (PLAN.md 5): Invalid range colours Start and End. */
export function cellIssues(row: RawLogRow, column: RawLogColumn): Issue[] {
  switch (column.kind) {
    case "start":
      return row.issues.filter(
        (issue) => issue.field === "start" || issue.code === "invalid_range",
      );
    case "end":
      return row.issues.filter((issue) => issue.field === "end");
    case "logged_minutes":
      return row.issues.filter((issue) => issue.field === "logged_minutes");
    case "extra":
      return row.issues.filter((issue) => issue.field === column.key);
    default:
      return [];
  }
}

export function rowLabel(row: RawLogRow): string {
  const name = row.task_name ?? "Untitled";
  return row.display_id ? `#${row.display_id} ${name}` : name;
}

/** A cell's plain text, for its tooltip and for copying. */
export function cellText(row: RawLogRow, column: RawLogColumn, timeZone: string): string | null {
  switch (column.kind) {
    case "display_id":
      return row.display_id;
    case "task_name":
      return row.task_name;
    case "start":
      return row.start_utc ? formatStamp(row.start_utc, timeZone) : null;
    case "end":
      return row.end_utc ? formatStamp(row.end_utc, timeZone) : null;
    case "duration":
      return row.duration_minutes !== null ? formatMinutes(row.duration_minutes) : null;
    case "logged_minutes":
      return row.logged_minutes !== null ? formatMinutes(row.logged_minutes) : null;
    case "extra":
      return extraText(row.extras[column.key.slice("extra:".length)], timeZone);
    default:
      return null;
  }
}

/** Attributes for a cell's <td>: red with its explanation when the cell has an issue. */
export function cellProps(row: RawLogRow, column: RawLogColumn, timeZone: string) {
  const issues = cellIssues(row, column);
  if (issues.length > 0) {
    return {
      className: "cell-issue",
      "data-tip": issues.map((issue) => issue.message).join("\n"),
    };
  }
  const text = cellText(row, column, timeZone);
  return { className: undefined, title: text && text.length > 24 ? text : undefined };
}
