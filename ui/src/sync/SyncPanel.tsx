import { useCallback, useEffect, useState } from "react";

import { callPython } from "../bridge/client";
import type {
  ConnectionInfo,
  FlaggedEntry,
  PendingRemoval,
  SyncResult,
  SyncStatus,
} from "../bridge/types";
import { problemFrom, type Problem } from "../connection/problems";
import { SignInStatus } from "../connection/SignInStatus";
import { useSignIn } from "../connection/useSignIn";
import { noticeFromCallError } from "../errors/reporting";
import { changeSummary, formatWhen, plural, progressText } from "./format";
import type { SyncState } from "./useSync";

const PAGE_SIZE = 50;

function openInNotion(url: string) {
  callPython("open_external", url).catch((error: unknown) => {
    noticeFromCallError(error, "Notion couldn't be opened");
  });
}

/**
 * Home's "Last sync" panel: what the last sync did or why it failed, the mass-removal question,
 * and every flagged entry with its explanation (PLAN.md 5, 6).
 */
export function SyncPanel({
  info,
  state,
  onOpenMapping,
  onPasteNewToken,
  onShowFlagged,
}: {
  info: ConnectionInfo;
  state: SyncState;
  onOpenMapping: () => void;
  onPasteNewToken: () => void;
  /** Open the raw log filtered to entries with issues. */
  onShowFlagged?: () => void;
}) {
  const signIn = useSignIn(() => {
    state.start("auto");
  });
  const load = state.load;

  return (
    <section className="panel sync-panel" aria-labelledby="sync-title">
      <div className="panel-head">
        <h2 id="sync-title">Last sync</h2>
        {load.status === "ready" && !load.sync.running && (
          <button
            type="button"
            className="button small"
            onClick={() => {
              state.start("quick");
            }}
          >
            Sync now
          </button>
        )}
      </div>

      {load.status === "idle" && (
        <p className="status" role="status">
          <span className="spinner" aria-hidden="true" /> Loading…
        </p>
      )}
      {load.status === "error" && (
        <div className={`notice ${load.problem.tone}`} role="alert">
          <strong>The sync status couldn&apos;t be read</strong>
          <p>{load.problem.message}</p>
          <div className="actions">
            <button type="button" className="button" onClick={state.refresh}>
              Try again
            </button>
          </div>
        </div>
      )}
      {state.startProblem && (
        <div className={`notice ${state.startProblem.tone}`} role="alert">
          <strong>The sync couldn&apos;t start</strong>
          <p>{state.startProblem.message}</p>
        </div>
      )}

      <SignInStatus
        state={signIn.state}
        onRetry={signIn.start}
        onCancel={signIn.cancel}
        onReopen={signIn.start}
      />

      {load.status === "ready" && (
        <>
          {load.sync.pending_removal && (
            <RemovalQuestion
              pending={load.sync.pending_removal}
              title={info.database_title ?? "your work log"}
              onAnswer={state.resolveRemoval}
            />
          )}
          <SyncSummary
            sync={load.sync}
            onRetry={() => {
              state.start("auto");
            }}
            onReconnect={signIn.start}
            onPasteNewToken={onPasteNewToken}
            onOpenMapping={onOpenMapping}
          />
          <dl className="facts">
            <dt>Entries</dt>
            <dd className="figure">{load.sync.entries.toLocaleString()}</dd>
            <dt>With issues</dt>
            <dd className="figure">{load.sync.flagged.toLocaleString()}</dd>
            {load.sync.last_full_sync && (
              <>
                <dt>Last full sync</dt>
                <dd>{formatWhen(load.sync.last_full_sync)}</dd>
              </>
            )}
          </dl>
          <p className="small muted">
            New and edited entries are copied each time Habit Tracker opens. Formula and rollup
            values refresh with each full sync, which runs at least once a day.
          </p>
          {load.sync.flagged > 0 && (
            <FlaggedList
              key={load.sync.last_result?.finished_at ?? ""}
              total={load.sync.flagged}
              onShowFlagged={onShowFlagged}
            />
          )}
        </>
      )}
    </section>
  );
}

function SyncSummary({
  sync,
  onRetry,
  onReconnect,
  onPasteNewToken,
  onOpenMapping,
}: {
  sync: SyncStatus;
  onRetry: () => void;
  onReconnect: () => void;
  onPasteNewToken: () => void;
  onOpenMapping: () => void;
}) {
  if (sync.running) {
    const full = sync.running.kind === "full";
    return (
      <div className="sync-running" role="status">
        <p>
          <span className="spinner" aria-hidden="true" /> {progressText(sync.running)}
        </p>
        {full && <div className="progress indeterminate" aria-hidden="true" />}
        <p className="small muted">{changeSummary(sync.running)} so far</p>
      </div>
    );
  }
  const result = sync.last_result;
  if (!result) {
    return (
      <p className="muted">Not synced yet. Your entries are copied the first time a sync runs.</p>
    );
  }
  if (!result.ok) {
    return (
      <SyncFailure
        result={result}
        onRetry={onRetry}
        onReconnect={onReconnect}
        onPasteNewToken={onPasteNewToken}
        onOpenMapping={onOpenMapping}
      />
    );
  }
  return (
    <div className="sync-done">
      <p>
        <strong>{result.kind === "full" ? "Full sync" : "Quick sync"}</strong>{" "}
        <span className="muted">· {formatWhen(result.finished_at)}</span>
      </p>
      {result.reason && <p className="small muted">{result.reason}</p>}
      <p className="figure">{changeSummary(result)}</p>
      {result.skipped > 0 && (
        <p className="small warn-text">
          {plural(result.skipped, "page")} from Notion couldn&apos;t be read and{" "}
          {result.skipped === 1 ? "was" : "were"} skipped. Local copies are kept.
        </p>
      )}
      {result.warnings.length > 0 && (
        <div className="notice warn" role="status">
          <strong>Synced without some columns</strong>
          <ul className="issue-list">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
          <div className="actions">
            <button type="button" className="button" onClick={onOpenMapping}>
              Open column mapping
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SyncFailure({
  result,
  onRetry,
  onReconnect,
  onPasteNewToken,
  onOpenMapping,
}: {
  result: SyncResult;
  onRetry: () => void;
  onReconnect: () => void;
  onPasteNewToken: () => void;
  onOpenMapping: () => void;
}) {
  const error = result.error;
  const code = error?.code ?? null;
  const when = formatWhen(result.finished_at);
  if (code === "offline") {
    return (
      <div className="notice warn" role="status">
        <strong>Offline: sync skipped</strong>
        <p>
          Notion couldn&apos;t be reached at {when}. Your local data is still here, and the next
          sync catches up.
        </p>
        <div className="actions">
          <button type="button" className="button" onClick={onRetry}>
            Try again
          </button>
        </div>
      </div>
    );
  }
  const titles: Partial<Record<string, string>> = {
    reconnect: "Reconnect to Notion",
    paste_new_token: "Paste a new token",
    service_unreachable: "Couldn't renew Notion access",
    schema_blocked: "Syncing can't start until the columns are fixed",
  };
  return (
    <div className="notice error" role="alert">
      <strong>{titles[code ?? ""] ?? "The last sync failed"}</strong>
      {code === "schema_blocked" && error && error.issues.length > 0 ? (
        <ul className="issue-list">
          {error.issues.map((issue) => (
            <li key={`${issue.code}-${issue.field ?? issue.property_id ?? ""}`}>{issue.message}</li>
          ))}
        </ul>
      ) : (
        <p>{error?.message ?? "Something went wrong."}</p>
      )}
      <p className="small muted">
        {when}
        {error ? ` · Error ID ${error.id}` : ""}. Your local data is still here.
      </p>
      <div className="actions">
        {code === "reconnect" && (
          <button type="button" className="button primary" onClick={onReconnect}>
            Reconnect to Notion
          </button>
        )}
        {code === "paste_new_token" && (
          <button type="button" className="button primary" onClick={onPasteNewToken}>
            Paste a new token
          </button>
        )}
        {code === "schema_blocked" && (
          <button type="button" className="button primary" onClick={onOpenMapping}>
            Open column mapping
          </button>
        )}
        {code !== "reconnect" && code !== "paste_new_token" && code !== "schema_blocked" && (
          <button type="button" className="button" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

function RemovalQuestion({
  pending,
  title,
  onAnswer,
}: {
  pending: PendingRemoval;
  title: string;
  onAnswer: (remove: boolean) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const answer = (remove: boolean) => {
    setBusy(true);
    setProblem(null);
    onAnswer(remove)
      .catch((error: unknown) => {
        setProblem(problemFrom(error));
      })
      .finally(() => {
        setBusy(false);
      });
  };
  const all = pending.count === pending.total;
  return (
    <div className="notice warn removal" role="alert" aria-label="Entries waiting to be removed">
      <strong>
        {all
          ? `The last full sync found none of your ${plural(pending.total, "entry", "entries")}`
          : `The last full sync didn't find ${pending.count.toLocaleString()} of your ${plural(pending.total, "entry", "entries")}`}
      </strong>
      <p>
        Habit Tracker paused before removing {pending.count === 1 ? "it" : "them"} from this
        computer, because losing this many at once usually means something else is wrong:
      </p>
      <ul className="issue-list">
        <li>
          {title} is no longer shared with Habit Tracker in Notion (check its ••• menu →
          Connections).
        </li>
        <li>You connected to a different Notion workspace than the one that holds it.</li>
        <li>The data source has filters, or the entries were moved to another database.</li>
        <li>They really were deleted in Notion.</li>
      </ul>
      <p className="small">
        Everything else from that sync is already copied. Keeping them changes nothing; the next
        full sync asks again if they&apos;re still missing.
      </p>
      {problem && <p className="field-error">{problem.message}</p>}
      <div className="actions">
        <button
          type="button"
          className="button danger"
          disabled={busy}
          onClick={() => {
            answer(true);
          }}
        >
          Remove them
        </button>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => {
            answer(false);
          }}
        >
          Keep them
        </button>
      </div>
    </div>
  );
}

type ListState =
  | { status: "loading" }
  | { status: "ready"; entries: FlaggedEntry[]; total: number; loadingMore: boolean }
  | { status: "error"; problem: Problem };

function FlaggedList({
  total,
  onShowFlagged,
}: {
  total: number;
  onShowFlagged?: (() => void) | undefined;
}) {
  const [list, setList] = useState<ListState>({ status: "loading" });

  const fetchFrom = useCallback((offset: number, previous: FlaggedEntry[]) => {
    callPython("get_flagged_entries", offset, PAGE_SIZE)
      .then((page) => {
        setList({
          status: "ready",
          entries: [...previous, ...page.entries],
          total: page.total,
          loadingMore: false,
        });
      })
      .catch((error: unknown) => {
        setList({ status: "error", problem: problemFrom(error) });
      });
  }, []);

  useEffect(() => {
    fetchFrom(0, []);
  }, [fetchFrom, total]);

  return (
    <section className="flagged" aria-labelledby="flagged-title">
      <h3 id="flagged-title">Entries with issues ({total.toLocaleString()})</h3>
      <p className="small muted">
        Every entry is copied; these are left out of the charts or have a value to check. Fix them
        in Notion and they clear at the next sync.
      </p>
      {onShowFlagged && (
        <div className="actions">
          <button type="button" className="button small" onClick={onShowFlagged}>
            Open them in the raw log
          </button>
        </div>
      )}
      {list.status === "loading" && (
        <p className="status" role="status">
          <span className="spinner" aria-hidden="true" /> Loading…
        </p>
      )}
      {list.status === "error" && (
        <div className="notice error" role="alert">
          <p>{list.problem.message}</p>
          <div className="actions">
            <button
              type="button"
              className="button"
              onClick={() => {
                setList({ status: "loading" });
                fetchFrom(0, []);
              }}
            >
              Try again
            </button>
          </div>
        </div>
      )}
      {list.status === "ready" && (
        <>
          <ul className="flagged-list" aria-label="Entries with issues">
            {list.entries.map((entry) => (
              <li key={entry.page_id} className="flagged-entry">
                <div className="flagged-head">
                  {entry.display_id && <span className="figure muted">#{entry.display_id}</span>}
                  <span className="flagged-name">{entry.task_name ?? "Untitled"}</span>
                  <span className="small muted">
                    {entry.start_utc ? formatWhen(entry.start_utc) : "No start time"}
                  </span>
                  <button
                    type="button"
                    className="link-button small"
                    onClick={() => {
                      openInNotion(entry.url);
                    }}
                  >
                    Open in Notion
                  </button>
                </div>
                <ul className="issue-list">
                  {entry.issues.map((issue, index) => (
                    <li key={index} className="issue">
                      {issue.message}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          {list.entries.length < list.total && (
            <button
              type="button"
              className="button"
              disabled={list.loadingMore}
              onClick={() => {
                setList({ ...list, loadingMore: true });
                fetchFrom(list.entries.length, list.entries);
              }}
            >
              {list.loadingMore && <span className="spinner" aria-hidden="true" />}
              Show more
            </button>
          )}
        </>
      )}
    </section>
  );
}
