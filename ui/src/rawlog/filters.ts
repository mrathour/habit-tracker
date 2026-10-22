import type {
  ExtraFilter,
  IssueCode,
  ParentChoice,
  RawLogColumn,
  RawLogFilters,
} from "../bridge/types";
import { formatCalendarDate } from "./format";

export const ISSUE_LABELS: Record<IssueCode, string> = {
  missing_time: "Missing time",
  invalid_range: "Invalid range",
  duration_mismatch: "Duration mismatch",
  unreadable_extra: "Unreadable extra field",
};

export const ISSUE_CODES = Object.keys(ISSUE_LABELS) as IssueCode[];

export const NO_FILTERS: RawLogFilters = {};

/** A filter the UI holds but can't send yet, with the reason, keyed by the filter's chip ID. */
export type FilterProblems = Record<string, string>;

/** A short label for a parent page: titles aren't read, so its ID and newest entry name it. */
export function parentLabel(parent: ParentChoice): string {
  const short = parent.page_id.replace(/-/g, "").slice(0, 8);
  const name = parent.latest_task_name ? ` · latest: ${parent.latest_task_name}` : "";
  return `Page ${short}${name}`;
}

/** A number the user has entered, or null for an empty box. */
function entered(value: number | null | undefined): number | null {
  return value === null || value === undefined || Number.isNaN(value) ? null : value;
}

/** A copy of `record` without `key`. */
export function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([k]) => k !== key));
}

/**
 * The filters to send: empty parts are dropped, and an unfinished or contradictory part (a range
 * that ends before it starts, "contains" with nothing typed) is held back with a reason instead
 * of failing the whole request.
 */
export function requestFilters(filters: RawLogFilters): {
  filters: RawLogFilters;
  problems: FilterProblems;
} {
  const out: RawLogFilters = {};
  const problems: FilterProblems = {};
  const search = filters.search?.trim();
  if (search) out.search = search;
  if (filters.date_from && filters.date_to && filters.date_to < filters.date_from) {
    problems["date"] = "The date range ends before it starts.";
  } else {
    if (filters.date_from) out.date_from = filters.date_from;
    if (filters.date_to) out.date_to = filters.date_to;
  }
  if (filters.no_parent) out.no_parent = true;
  else if (filters.parents?.length) out.parents = filters.parents;
  const low = entered(filters.duration_min);
  const high = entered(filters.duration_max);
  if ((low !== null && low < 0) || (high !== null && high < 0)) {
    problems["duration"] = "Durations can't be negative.";
  } else if (low !== null && high !== null && high < low) {
    problems["duration"] = "The longest duration is shorter than the shortest.";
  } else {
    if (low !== null) out.duration_min = low;
    if (high !== null) out.duration_max = high;
  }
  if (filters.issues) out.issues = filters.issues;
  if (filters.issue_codes?.length) out.issue_codes = filters.issue_codes;
  if (filters.overlaps) out.overlaps = true;
  const extra: Record<string, ExtraFilter> = {};
  for (const [id, spec] of Object.entries(filters.extra ?? {})) {
    const problem = extraProblem(spec);
    if (problem === undefined) continue;
    if (problem) problems[`extra:${id}`] = problem;
    else extra[id] = spec;
  }
  if (Object.keys(extra).length > 0) out.extra = extra;
  return { filters: out, problems };
}

/**
 * Why an extra filter can't be sent yet: null when it can, undefined when it simply isn't set
 * (nothing typed or chosen yet).
 */
function extraProblem(spec: ExtraFilter): string | null | undefined {
  switch (spec.op) {
    case "contains":
      return spec.value.trim() ? null : undefined;
    case "range": {
      const low = entered(spec.min);
      const high = entered(spec.max);
      if (low === null && high === null) return undefined;
      return low !== null && high !== null && high < low
        ? "The highest value is below the lowest."
        : null;
    }
    case "any_of":
      return spec.values.length > 0 ? null : undefined;
    case "dates":
      if (!spec.from && !spec.to) return undefined;
      if (spec.from && spec.to && spec.to < spec.from)
        return "The date range ends before it starts.";
      return null;
    default:
      return null;
  }
}

export function hasFilters(filters: RawLogFilters): boolean {
  return Object.keys(requestFilters(filters).filters).length > 0;
}

export interface FilterChip {
  id: string;
  label: string;
}

function rangeText(low: string | null, high: string | null): string {
  if (low && high) return `${low} – ${high}`;
  return low ? `from ${low}` : `up to ${high ?? ""}`;
}

/** One removable chip per active filter, in the filter bar's order. */
export function activeChips(
  filters: RawLogFilters,
  columns: RawLogColumn[],
  parents: ParentChoice[],
): FilterChip[] {
  const sent = requestFilters(filters).filters;
  const chips: FilterChip[] = [];
  if (sent.search) chips.push({ id: "search", label: `Task name contains “${sent.search}”` });
  if (sent.date_from || sent.date_to) {
    const first = sent.date_from ? formatCalendarDate(sent.date_from) : null;
    const last = sent.date_to ? formatCalendarDate(sent.date_to) : null;
    chips.push({ id: "date", label: `Started ${rangeText(first, last)}` });
  }
  if (sent.no_parent) chips.push({ id: "parents", label: "No parent task" });
  if (sent.parents?.length) {
    const names = sent.parents.map((id) => {
      const parent = parents.find((p) => p.page_id === id);
      return parent ? parentLabel(parent) : `Page ${id.replace(/-/g, "").slice(0, 8)}`;
    });
    chips.push({
      id: "parents",
      label: names.length === 1 ? `Parent task: ${names[0] ?? ""}` : `${names.length} parent tasks`,
    });
  }
  if (sent.duration_min !== undefined || sent.duration_max !== undefined) {
    const low = sent.duration_min !== undefined ? `${String(sent.duration_min)} min` : null;
    const high = sent.duration_max !== undefined ? `${String(sent.duration_max)} min` : null;
    chips.push({ id: "duration", label: `Duration ${rangeText(low, high)}` });
  }
  if (sent.issues === "any") chips.push({ id: "issues", label: "Has issues" });
  if (sent.issues === "none") chips.push({ id: "issues", label: "No issues" });
  if (sent.issue_codes?.length) {
    chips.push({
      id: "issue_codes",
      label: sent.issue_codes.map((code) => ISSUE_LABELS[code]).join(" or "),
    });
  }
  if (sent.overlaps) chips.push({ id: "overlaps", label: "Overlaps another session" });
  for (const [id, spec] of Object.entries(sent.extra ?? {})) {
    const name = columns.find((c) => c.key === `extra:${id}`)?.label ?? "Field";
    chips.push({ id: `extra:${id}`, label: `${name} ${extraChipText(spec)}` });
  }
  return chips;
}

function extraChipText(spec: ExtraFilter): string {
  switch (spec.op) {
    case "empty":
      return "is empty";
    case "not_empty":
      return "has a value";
    case "contains":
      return `contains “${spec.value.trim()}”`;
    case "range":
      return rangeText(
        entered(spec.min) === null ? null : String(spec.min),
        entered(spec.max) === null ? null : String(spec.max),
      );
    case "is":
      return spec.value ? "is Yes" : "is No";
    case "any_of":
      return `is ${spec.values.join(" or ")}`;
    case "dates":
      return rangeText(
        spec.from ? formatCalendarDate(spec.from) : null,
        spec.to ? formatCalendarDate(spec.to) : null,
      );
  }
}

/** The filters without the chip's part. */
export function removeChip(filters: RawLogFilters, id: string): RawLogFilters {
  const next: RawLogFilters = { ...filters };
  switch (id) {
    case "search":
      delete next.search;
      break;
    case "date":
      delete next.date_from;
      delete next.date_to;
      break;
    case "parents":
      delete next.parents;
      delete next.no_parent;
      break;
    case "duration":
      delete next.duration_min;
      delete next.duration_max;
      break;
    case "issues":
      delete next.issues;
      break;
    case "issue_codes":
      delete next.issue_codes;
      break;
    case "overlaps":
      delete next.overlaps;
      break;
    default:
      if (id.startsWith("extra:")) {
        next.extra = without(next.extra ?? {}, id.slice("extra:".length));
      }
  }
  return next;
}
