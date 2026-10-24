import type { ConnectionInfo } from "../bridge/types";
import { WorkspaceBadge } from "../components/WorkspaceBadge";
import { DashboardSection } from "../dashboard/DashboardView";
import { MappingSuggestions } from "../sync/MappingSuggestions";
import { SyncPanel } from "../sync/SyncPanel";
import type { SyncState } from "../sync/useSync";

/** Connected, a work log chosen and mapped: the dashboard, then the last sync (PLAN.md 6, 7). */
export function HomeView({
  info,
  sync,
  justSaved = null,
  onChangeDatabase,
  onReviewMapping,
  onPasteNewToken,
  onShowFlagged,
}: {
  info: ConnectionInfo;
  sync: SyncState;
  onPasteNewToken: () => void;
  /** Open the raw log filtered to entries with issues. */
  onShowFlagged: () => void;
  /** Set right after the mapping screen saved, to confirm it. */
  justSaved?: { fullSync: boolean } | null;
  onChangeDatabase: () => void;
  onReviewMapping: () => void;
}) {
  // The sync status is live; the connection's copy of the flag is only as fresh as its last read.
  const fullSyncNeeded =
    sync.load.status === "ready"
      ? sync.load.sync.full_sync_required && sync.load.sync.running?.kind !== "full"
      : Boolean(info.full_sync_required);

  return (
    <section className="column" aria-labelledby="home-title" data-width="dashboard">
      <h1 id="home-title" className="section-title">
        {info.database_title ?? "Your work log"}
      </h1>
      {justSaved && !justSaved.fullSync && (
        <div className="notice ok" role="status">
          <p>Column mapping saved.</p>
        </div>
      )}
      {fullSyncNeeded && info.full_sync_required && (
        <div className="notice warn" role="status" aria-label="Full sync required">
          <strong>
            {justSaved?.fullSync ? "Mapping saved: a full sync is needed" : "A full sync is needed"}
          </strong>
          <p>{info.full_sync_required.reason} It runs with the next sync.</p>
        </div>
      )}
      <MappingSuggestions sync={sync} onReviewMapping={onReviewMapping} />
      <DashboardSection
        sync={sync.load.status === "ready" ? sync.load.sync : null}
        onShowFlagged={onShowFlagged}
      />
      <SyncPanel
        info={info}
        state={sync}
        onOpenMapping={onReviewMapping}
        onPasteNewToken={onPasteNewToken}
        onShowFlagged={onShowFlagged}
      />
      <div className="panel">
        <WorkspaceBadge info={info} />
        <p>
          Habit Tracker is connected and reads{" "}
          <strong>{info.database_title ?? "your work log"}</strong>.
        </p>
        <div className="actions">
          <button type="button" className="button" onClick={onReviewMapping}>
            Review column mapping
          </button>
          <button type="button" className="button" onClick={onChangeDatabase}>
            Choose a different database
          </button>
        </div>
      </div>
    </section>
  );
}
