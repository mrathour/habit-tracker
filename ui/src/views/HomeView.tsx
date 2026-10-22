import type { ConnectionInfo } from "../bridge/types";
import { WorkspaceBadge } from "../components/WorkspaceBadge";

/** Connected and a work log chosen. The charts arrive with syncing (PLAN.md phases 5–6). */
export function HomeView({
  info,
  justSaved = null,
  onChangeDatabase,
  onReviewMapping,
}: {
  info: ConnectionInfo;
  /** Set right after the mapping screen saved, to confirm it. */
  justSaved?: { fullSync: boolean } | null;
  onChangeDatabase: () => void;
  onReviewMapping: () => void;
}) {
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
      {info.full_sync_required && (
        <div className="notice warn" role="status" aria-label="Full sync required">
          <strong>
            {justSaved?.fullSync ? "Mapping saved: a full sync is needed" : "A full sync is needed"}
          </strong>
          <p>
            {info.full_sync_required.reason} It runs the next time Habit Tracker syncs your work
            log.
          </p>
        </div>
      )}
      <div className="panel">
        <WorkspaceBadge info={info} />
        <p>
          Habit Tracker is connected and reads{" "}
          <strong>{info.database_title ?? "your work log"}</strong>. Your daily totals, weekly
          trends and streaks appear here once its entries have been copied to this computer.
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
