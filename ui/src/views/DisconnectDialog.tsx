import { useState } from "react";

import { callPython } from "../bridge/client";
import type { ConnectionInfo, LogoutResult } from "../bridge/types";
import { Dialog } from "../components/Dialog";
import { connectionLabel } from "../connection/labels";
import { problemFrom, type Problem } from "../connection/problems";

/** Disconnect (PLAN.md 12.7): revoke where possible, remove the token, keep or clear data. */
export function DisconnectDialog({
  info,
  onClose,
  onDisconnected,
}: {
  info: ConnectionInfo;
  onClose: () => void;
  onDisconnected: (result: LogoutResult) => void;
}) {
  const [clear, setClear] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  const disconnect = () => {
    setBusy(true);
    setProblem(null);
    callPython("logout", clear)
      .then(onDisconnected)
      .catch((error: unknown) => {
        setProblem(problemFrom(error));
        setBusy(false);
      });
  };

  return (
    <Dialog title="Disconnect from Notion?" onClose={onClose} busy={busy}>
      <p>
        Habit Tracker stops reading from Notion and removes the token from this computer.
        {info.auth_kind === "oauth"
          ? ` It also asks Notion to cancel its access to ${connectionLabel(info)}.`
          : ""}
      </p>
      <fieldset className="choices">
        <legend className="legend">Entries already copied to this computer</legend>
        <label className="choice">
          <input
            type="radio"
            name="local-data"
            checked={!clear}
            onChange={() => {
              setClear(false);
            }}
          />
          <span>Keep them</span>
          <span className="hint">
            Charts still work offline, and reconnecting picks up where you left off.
          </span>
        </label>
        <label className="choice">
          <input
            type="radio"
            name="local-data"
            checked={clear}
            onChange={() => {
              setClear(true);
            }}
          />
          <span>Delete them</span>
          <span className="hint">
            Removes the copied entries and the database choice. Your Notion data isn&apos;t touched.
          </span>
        </label>
      </fieldset>
      {problem && (
        <div className={`notice ${problem.tone}`} role="alert">
          <strong>{problem.title}</strong>
          <p>{problem.message}</p>
        </div>
      )}
      <div className="actions">
        <button type="button" className="button danger" onClick={disconnect} disabled={busy}>
          {busy && <span className="spinner" aria-hidden="true" />}
          Disconnect
        </button>
        <button type="button" className="button" onClick={onClose} disabled={busy}>
          Stay connected
        </button>
      </div>
    </Dialog>
  );
}
