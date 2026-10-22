import type { ConnectionInfo } from "../bridge/types";
import { WorkspaceBadge } from "../components/WorkspaceBadge";

/** Connected and a work log chosen. The charts arrive with syncing (PLAN.md phases 5–6). */
export function HomeView({
  info,
  onChangeDatabase,
}: {
  info: ConnectionInfo;
  onChangeDatabase: () => void;
}) {
  return (
    <section className="column" aria-labelledby="home-title">
      <h1 id="home-title" className="section-title">
        {info.database_title ?? "Your work log"}
      </h1>
      <div className="panel">
        <WorkspaceBadge info={info} />
        <p>
          Habit Tracker is connected and reads{" "}
          <strong>{info.database_title ?? "your work log"}</strong>. Your daily totals, weekly
          trends and streaks appear here once its entries have been copied to this computer.
        </p>
        <div className="actions">
          <button type="button" className="button" onClick={onChangeDatabase}>
            Choose a different database
          </button>
        </div>
      </div>
    </section>
  );
}
