import { useState } from "react";

import { callPython } from "../bridge/client";
import type { RawLogRequest } from "../bridge/types";
import { problemFrom, type Problem } from "../connection/problems";
import { noticeFromCallError } from "../errors/reporting";
import { plural } from "./format";

type ExportState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; path: string; rows: number }
  | { status: "empty" }
  | { status: "error"; problem: Problem };

/**
 * "Export CSV" (PLAN.md 8): saves exactly the rows, columns and order on screen through the
 * native Save dialog, run by Python. Cancelling the dialog changes nothing.
 */
export function ExportControl({
  request,
  columns,
  matched,
}: {
  request: Omit<RawLogRequest, "offset" | "limit">;
  columns: string[];
  matched: number;
}) {
  const [state, setState] = useState<ExportState>({ status: "idle" });
  const disabledReason =
    matched === 0
      ? "There's nothing to export: no entries match the filters."
      : columns.length === 0
        ? "Show at least one column to export."
        : null;

  const run = () => {
    setState({ status: "saving" });
    callPython("export_raw_log", request, columns)
      .then((result) => {
        if (result.status === "saved" && result.path) {
          setState({ status: "saved", path: result.path, rows: result.rows });
        } else if (result.status === "empty") {
          setState({ status: "empty" });
        } else {
          setState({ status: "idle" });
        }
      })
      .catch((error: unknown) => {
        setState({ status: "error", problem: problemFrom(error) });
      });
  };

  return (
    <>
      <button
        type="button"
        className="button small"
        disabled={disabledReason !== null || state.status === "saving"}
        title={disabledReason ?? "Save the entries shown, with these columns and this order"}
        aria-describedby={disabledReason ? "export-disabled-reason" : undefined}
        onClick={run}
      >
        {state.status === "saving" && <span className="spinner small" aria-hidden="true" />}
        {state.status === "saving" ? "Exporting…" : "Export CSV"}
      </button>
      {disabledReason && (
        <span id="export-disabled-reason" className="visually-hidden">
          {disabledReason}
        </span>
      )}
      <ExportNotice
        state={state}
        onRetry={run}
        onDismiss={() => {
          setState({ status: "idle" });
        }}
      />
    </>
  );
}

function ExportNotice({
  state,
  onRetry,
  onDismiss,
}: {
  state: ExportState;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  if (state.status === "saved") {
    return (
      <div className="notice ok export-notice" role="status">
        <strong>Exported {plural(state.rows, "entry", "entries")}</strong>
        <p className="export-path">
          Saved to <code>{state.path}</code>
        </p>
        <div className="actions">
          <button
            type="button"
            className="button small"
            onClick={() => {
              callPython("show_exported_file").catch((error: unknown) => {
                noticeFromCallError(error, "The file couldn't be shown");
              });
            }}
          >
            Show in folder
          </button>
          <button type="button" className="link-button small" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      </div>
    );
  }
  if (state.status === "empty") {
    return (
      <div className="notice warn export-notice" role="status">
        <p>There was nothing to export: no entries match the filters any more.</p>
        <div className="actions">
          <button type="button" className="link-button small" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="notice error export-notice" role="alert">
        <strong>The CSV file wasn&apos;t saved</strong>
        <p>{state.problem.message}</p>
        {state.problem.errorId && <p className="small muted">Error ID {state.problem.errorId}</p>}
        <div className="actions">
          <button type="button" className="button small" onClick={onRetry}>
            Try again
          </button>
          <button type="button" className="link-button small" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      </div>
    );
  }
  return null;
}
