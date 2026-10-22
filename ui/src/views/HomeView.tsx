import type { ConnectionInfo } from "../bridge/types";
import { WorkspaceBadge } from "../components/WorkspaceBadge";
import { SyncPanel } from "../sync/SyncPanel";
import type { SyncState } from "../sync/useSync";

/** Connected and a work log chosen. The charts arrive with syncing (PLAN.md phases 5–6). */
export function HomeView({
  info,
  sync,
  justSaved = null,
  onChangeDatabase,
  onReviewMapping,
  onPasteNewToken,
}: {
  info: ConnectionInfo;
  sync: SyncState;
  onPasteNewToken: () => void;
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
    <section className="column" aria-labelledby="home-title">
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
      <div className="panel">
        <WorkspaceBadge info={info} />
        <p>
          Habit Tracker is connected and reads{" "}
          <strong>{info.database_title ?? "your work log"}</strong>. Your daily totals, weekly
          trends and streaks arrive here in the next version; for now, this page shows what each
          sync copied and which entries need a look.
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
      <SyncPanel
        info={info}
        state={sync}
        onOpenMapping={onReviewMapping}
        onPasteNewToken={onPasteNewToken}
      />
    </section>
  );
}
