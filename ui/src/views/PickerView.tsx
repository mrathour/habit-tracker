import { useCallback, useEffect, useState } from "react";

import { BridgeCallError, callPython } from "../bridge/client";
import type { ConnectionInfo, DatabaseGroup } from "../bridge/types";
import { Dialog } from "../components/Dialog";
import { problemFrom, type Problem } from "../connection/problems";
import { SignInStatus } from "../connection/SignInStatus";
import { useSignIn } from "../connection/useSignIn";

type ListState =
  | { status: "loading" }
  | { status: "ready"; groups: DatabaseGroup[]; nextCursor: string | null; loadingMore: boolean }
  | { status: "error"; problem: Problem };

interface Selection {
  databaseId: string;
  dataSourceId: string;
}

function merge(existing: DatabaseGroup[], incoming: DatabaseGroup[]): DatabaseGroup[] {
  const byId = new Map(existing.map((group) => [group.database_id, { ...group }]));
  for (const group of incoming) {
    const current = byId.get(group.database_id);
    if (current) {
      const known = new Set(current.data_sources.map((s) => s.id));
      current.data_sources = [
        ...current.data_sources,
        ...group.data_sources.filter((s) => !known.has(s.id)),
      ];
    } else {
      byId.set(group.database_id, group);
    }
  }
  return [...byId.values()];
}

/** Choose the work log: every data source the connection can read, grouped by database. */
export function PickerView({
  info,
  onChosen,
  onCancel,
  onPasteNewToken,
}: {
  info: ConnectionInfo;
  onChosen: (info: ConnectionInfo) => void;
  onCancel?: (() => void) | undefined;
  onPasteNewToken: () => void;
}) {
  const [list, setList] = useState<ListState>({ status: "loading" });
  const [selection, setSelection] = useState<Selection | null>(
    info.database_id && info.data_source_id
      ? { databaseId: info.database_id, dataSourceId: info.data_source_id }
      : null,
  );
  const [saving, setSaving] = useState(false);
  const [saveProblem, setSaveProblem] = useState<Problem | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const fetchFirstPage = useCallback(() => {
    callPython("list_data_sources", null)
      .then((page) => {
        setList({
          status: "ready",
          groups: page.groups,
          nextCursor: page.next_cursor,
          loadingMore: false,
        });
      })
      .catch((error: unknown) => {
        setList({ status: "error", problem: problemFrom(error) });
      });
  }, []);

  useEffect(() => {
    fetchFirstPage();
  }, [fetchFirstPage]);

  const load = useCallback(() => {
    setList({ status: "loading" });
    fetchFirstPage();
  }, [fetchFirstPage]);

  const signIn = useSignIn(() => {
    load();
  });

  const loadMore = () => {
    if (list.status !== "ready" || !list.nextCursor) return;
    const cursor = list.nextCursor;
    setList({ ...list, loadingMore: true });
    callPython("list_data_sources", cursor)
      .then((page) => {
        setList((previous) =>
          previous.status === "ready"
            ? {
                status: "ready",
                groups: merge(previous.groups, page.groups),
                nextCursor: page.next_cursor,
                loadingMore: false,
              }
            : previous,
        );
      })
      .catch((error: unknown) => {
        setList({ status: "error", problem: problemFrom(error) });
      });
  };

  const save = (confirmReplace: boolean) => {
    if (!selection) return;
    setSaving(true);
    setSaveProblem(null);
    callPython("choose_data_source", selection.databaseId, selection.dataSourceId, confirmReplace)
      .then((updated) => {
        setConfirm(null);
        onChosen(updated);
      })
      .catch((error: unknown) => {
        if (error instanceof BridgeCallError && error.report.code === "confirm_replace") {
          setConfirm(error.report.message);
        } else {
          setConfirm(null);
          setSaveProblem(problemFrom(error));
        }
      })
      .finally(() => {
        setSaving(false);
      });
  };

  const helpUrl = "https://habit-tracker.mrathour.workers.dev/support";

  return (
    <section className="column" aria-labelledby="picker-title" data-width="wide">
      <h1 id="picker-title" className="section-title">
        Choose your work log
      </h1>
      <p className="muted">
        Pick the Notion database where you log your work sessions. Habit Tracker reads only this
        one.
      </p>

      {list.status === "loading" && (
        <ul className="picker-list" aria-busy="true" aria-label="Loading databases">
          {[0, 1, 2].map((i) => (
            <li key={i} className="skeleton" />
          ))}
        </ul>
      )}

      {list.status === "error" && (
        <div className={`notice ${list.problem.tone}`} role="alert">
          <strong>{list.problem.title}</strong>
          <p>{list.problem.message}</p>
          {list.problem.errorId && <p className="small muted">Error ID {list.problem.errorId}</p>}
          <div className="actions">
            {list.problem.actions.includes("reconnect") && (
              <button type="button" className="button primary" onClick={signIn.start}>
                Reconnect to Notion
              </button>
            )}
            {list.problem.actions.includes("paste_token") && (
              <button type="button" className="button primary" onClick={onPasteNewToken}>
                Paste a new token
              </button>
            )}
            {list.problem.actions.includes("retry") && (
              <button type="button" className="button" onClick={load}>
                Try again
              </button>
            )}
          </div>
        </div>
      )}

      {list.status === "ready" && list.groups.length === 0 && (
        <div className="empty">
          <h2>No databases are shared with Habit Tracker yet</h2>
          {info.auth_kind === "pat" ? (
            <p>
              A personal access token sees every database you can open in Notion. Check that your
              work log is in this workspace and that you can open it, then refresh.
            </p>
          ) : (
            <>
              <p>Share your work log with the connection, then refresh this list:</p>
              <ol>
                <li>Open the database in Notion.</li>
                <li>
                  Click <strong>•••</strong> at the top right, then <strong>More</strong>.
                </li>
                <li>
                  In <strong>Connections</strong>, click <strong>Add connections</strong> and choose{" "}
                  {info.auth_kind === "oauth" ? <strong>Habit Tracker</strong> : "your connection"}.
                </li>
              </ol>
            </>
          )}
          <div className="actions">
            <button type="button" className="button primary" onClick={load}>
              Refresh
            </button>
            {info.auth_kind === "oauth" && (
              <button type="button" className="button" onClick={signIn.start}>
                Connect again and choose pages
              </button>
            )}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                void callPython("open_external", helpUrl).catch(() => undefined);
              }}
            >
              How sharing works
            </button>
          </div>
        </div>
      )}

      <SignInStatus
        state={signIn.state}
        onRetry={signIn.start}
        onCancel={signIn.cancel}
        onReopen={signIn.start}
      />

      {list.status === "ready" && list.groups.length > 0 && (
        <>
          <ul className="picker-list" aria-label="Databases">
            {list.groups.map((group) => {
              const single = group.data_sources.length === 1 ? group.data_sources[0] : undefined;
              const groupSelected = selection?.databaseId === group.database_id;
              return (
                <li key={group.database_id}>
                  <label className="picker-row">
                    <input
                      type="radio"
                      name="database"
                      checked={groupSelected}
                      onChange={() => {
                        const first = group.data_sources[0];
                        if (first)
                          setSelection({ databaseId: group.database_id, dataSourceId: first.id });
                      }}
                    />
                    <span className="db-emoji" aria-hidden="true">
                      {group.icon_emoji ?? ""}
                    </span>
                    <span>
                      <span className="db-title">{group.title}</span>
                      {!single && (
                        <span className="small muted">
                          {" "}
                          has {group.data_sources.length} data sources
                        </span>
                      )}
                    </span>
                  </label>
                  {!single && groupSelected && (
                    <ul className="picker-sources" aria-label={`Data sources in ${group.title}`}>
                      {group.data_sources.map((source) => (
                        <li key={source.id}>
                          <label>
                            <input
                              type="radio"
                              name="data-source"
                              checked={selection.dataSourceId === source.id}
                              onChange={() => {
                                setSelection({
                                  databaseId: group.database_id,
                                  dataSourceId: source.id,
                                });
                              }}
                            />
                            {source.name}
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
          {list.nextCursor && (
            <button type="button" className="button" onClick={loadMore} disabled={list.loadingMore}>
              {list.loadingMore && <span className="spinner" aria-hidden="true" />}
              {list.loadingMore ? "Loading more…" : "Show more databases"}
            </button>
          )}
        </>
      )}

      {saveProblem && (
        <div className={`notice ${saveProblem.tone}`} role="alert">
          <strong>{saveProblem.title}</strong>
          <p>{saveProblem.message}</p>
        </div>
      )}

      <div className="actions">
        <button
          type="button"
          className="button primary"
          disabled={!selection || saving || list.status !== "ready"}
          onClick={() => {
            save(false);
          }}
        >
          {saving && <span className="spinner" aria-hidden="true" />}
          Use this database
        </button>
        {onCancel && (
          <button type="button" className="link-button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>

      {confirm && (
        <Dialog
          title="Switch to a different database?"
          busy={saving}
          onClose={() => {
            setConfirm(null);
          }}
        >
          <p>{confirm}</p>
          <div className="actions">
            <button
              type="button"
              className="button danger"
              disabled={saving}
              onClick={() => {
                save(true);
              }}
            >
              Switch and remove entries
            </button>
            <button
              type="button"
              className="button"
              disabled={saving}
              onClick={() => {
                setConfirm(null);
              }}
            >
              Keep the current database
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
