import type { SyncProgress, SyncResult } from "../bridge/types";
import type { DisplayOptions } from "../mapping/format";

/** A UTC timestamp in local time, e.g. "Oct 22, 2026, 3:30 PM". */
export function formatWhen(utc: string, options: DisplayOptions = {}): string {
  return new Intl.DateTimeFormat(options.locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: options.timeZone,
  }).format(new Date(utc));
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

/** "3 added · 1 updated · 0 removed" */
export function changeSummary(counts: Pick<SyncResult, "added" | "updated" | "removed">): string {
  return `${counts.added.toLocaleString()} added · ${counts.updated.toLocaleString()} updated · ${counts.removed.toLocaleString()} removed`;
}

/** What a running sync is doing, in a few words. */
export function progressText(progress: SyncProgress): string {
  if (progress.phase === "checking") return "Checking your columns…";
  if (progress.phase === "removing") return "Checking for entries deleted in Notion…";
  const read = plural(progress.pages_fetched, "entry", "entries");
  if (progress.kind === "full") return `Full sync: ${read} read`;
  return progress.pages_fetched > 0 ? `Syncing: ${read} changed` : "Checking for changes…";
}
