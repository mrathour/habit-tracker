import type { SyncStatus } from "../bridge/types";
import { formatWhen, progressText } from "./format";

/**
 * The top bar's sync state: subtle while a quick sync runs, a progress bar for a full sync,
 * and the last outcome otherwise (PLAN.md 6.4 "States the UI shows").
 */
export function SyncIndicator({ sync }: { sync: SyncStatus }) {
  const running = sync.running;
  if (running) {
    const full = running.kind === "full";
    return (
      <span className={`sync-indicator${full ? " full" : ""}`} role="status">
        <span className="spinner small" aria-hidden="true" />
        <span>{full ? progressText(running) : "Syncing…"}</span>
        {full && <span className="progress indeterminate" aria-hidden="true" />}
      </span>
    );
  }
  const result = sync.last_result;
  if (!result) {
    return <span className="sync-indicator muted">Not synced yet</span>;
  }
  if (!result.ok) {
    const offline = result.error?.code === "offline";
    return (
      <span className={`sync-indicator ${offline ? "warn" : "error"}`}>
        <span className="dot" aria-hidden="true" />
        {offline ? "Offline: sync skipped" : "Sync failed"}
      </span>
    );
  }
  return (
    <span className="sync-indicator muted">
      <span className="dot ok" aria-hidden="true" />
      Synced {formatWhen(result.finished_at)}
    </span>
  );
}
