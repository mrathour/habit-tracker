import { callPython } from "../bridge/client";
import { noticeFromCallError } from "../errors/reporting";
import type { AppInfoState } from "./useAppInfo";
import type { BridgeCheckState, ReceivedEvent } from "./useBridgeCheck";

/* Diagnostics shown under Settings in dev mode or with --diagnostics: the Python bridge,
   pushed events, and every error path (PLAN.md Phase 2). */

export function AppInfoCard({ state }: { state: AppInfoState }) {
  return (
    <section className="card" aria-labelledby="bridge-title" aria-busy={state.status === "loading"}>
      <h2 id="bridge-title">Desktop bridge</h2>
      {state.status === "loading" && (
        <p className="status">
          <span className="spinner" aria-hidden="true" /> Connecting to the app…
        </p>
      )}
      {state.status === "unavailable" && (
        <p className="status warn">
          This page isn&apos;t running inside the Habit Tracker window, so it can&apos;t reach
          Python. Start the app with <code>uv run habit-tracker --dev</code>.
        </p>
      )}
      {state.status === "error" && (
        <p className="status error">
          Python couldn&apos;t send the app&apos;s details: {state.message}
          {state.errorId !== null && ` (error ID ${state.errorId})`}
        </p>
      )}
      {state.status === "ready" && (
        <>
          <p className="status ok">
            <span className="dot" aria-hidden="true" /> Connected. These details came from Python
            through <code>get_app_info()</code>.
          </p>
          <dl className="facts">
            <dt>Version</dt>
            <dd>{state.info.version}</dd>
            <dt>Python</dt>
            <dd>{state.info.python_version}</dd>
            <dt>pywebview</dt>
            <dd>{state.info.pywebview_version}</dd>
            <dt>SQLite</dt>
            <dd>
              {state.info.sqlite_version} · schema version {state.info.schema_version}
            </dd>
            <dt>Data folder</dt>
            <dd>
              <code>{state.info.data_dir}</code>
            </dd>
            <dt>Database</dt>
            <dd>
              <code>{state.info.database_path}</code>
            </dd>
            <dt>Logs</dt>
            <dd>
              <code>{state.info.log_dir}</code>{" "}
              <button
                type="button"
                className="button small"
                onClick={() => {
                  callPython("open_log_folder").catch((error: unknown) => {
                    noticeFromCallError(error, "The log folder couldn't be opened");
                  });
                }}
              >
                Open
              </button>
            </dd>
            <dt>Started</dt>
            <dd>{new Date(state.info.started_at).toLocaleString()}</dd>
          </dl>
        </>
      )}
    </section>
  );
}

export function BridgeCheckCard({
  state,
  events,
  onStart,
}: {
  state: BridgeCheckState;
  events: readonly ReceivedEvent[];
  onStart: () => void;
}) {
  const busy = state.status === "starting" || state.status === "running";
  const progress =
    state.status === "running" ? state.step / state.steps : state.status === "done" ? 1 : 0;

  return (
    <section className="card" aria-labelledby="events-title">
      <h2 id="events-title">Events from Python</h2>
      <p className="muted">
        Python runs a task on a background thread and pushes a progress event to this window after
        each step, the same way sync progress will be shown.
      </p>
      <div className="actions">
        <button type="button" className="button primary" disabled={busy} onClick={onStart}>
          {busy ? "Running…" : state.status === "done" ? "Run again" : "Run bridge check"}
        </button>
        <span className="muted" aria-live="polite">
          {state.status === "running" && `Step ${state.step} of ${state.steps}`}
          {state.status === "done" && `Received all ${state.steps} steps in ${state.elapsedMs} ms`}
        </span>
      </div>
      <div
        className="progress"
        role="progressbar"
        aria-label="Bridge check progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <div className="progress-fill" style={{ width: `${progress * 100}%` }} />
      </div>
      {events.length === 0 ? (
        <p className="empty-note">No events yet. Run the bridge check to see them arrive.</p>
      ) : (
        <ol className="event-log">
          {events.map((event, index) => (
            <li key={`${event.receivedAt.getTime()}-${index}`}>
              <time>{event.receivedAt.toLocaleTimeString()}</time>
              <code>{event.name}</code>
              <span>{event.detail}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
