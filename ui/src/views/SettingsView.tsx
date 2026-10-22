import { useState } from "react";

import { callPython } from "../bridge/client";
import type { ConnectionInfo, LogoutResult } from "../bridge/types";
import { AppInfoCard, BridgeCheckCard } from "../components/DiagnosticsCards";
import { DiagnosticsPanel } from "../components/DiagnosticsPanel";
import type { AppInfoState } from "../components/useAppInfo";
import { useBridgeCheck } from "../components/useBridgeCheck";
import { WorkspaceBadge } from "../components/WorkspaceBadge";
import { authKindLabel, connectionLabel, disconnectSummary } from "../connection/labels";
import { TokenForm } from "../connection/TokenForm";
import { noticeFromCallError } from "../errors/reporting";
import { DashboardSettings } from "../dashboard/DashboardSettings";
import { formatWhen } from "../sync/format";
import type { SyncState } from "../sync/useSync";
import { DisconnectDialog } from "./DisconnectDialog";

export function SettingsView({
  info,
  appInfo,
  onConnectionChanged,
  onChangeDatabase,
  onReviewMapping,
  focusAdvanced = false,
  sync = null,
}: {
  info: ConnectionInfo;
  appInfo: AppInfoState;
  onConnectionChanged: (info: ConnectionInfo | null) => void;
  onChangeDatabase: () => void;
  onReviewMapping: () => void;
  focusAdvanced?: boolean;
  /** Present when syncing is possible: connected, work log chosen, columns mapped. */
  sync?: SyncState | null;
}) {
  const [disconnecting, setDisconnecting] = useState(false);
  const [summary, setSummary] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const bridgeCheck = useBridgeCheck();
  const details = appInfo.status === "ready" ? appInfo.info : null;

  const onDisconnected = (result: LogoutResult) => {
    setDisconnecting(false);
    setSummary(disconnectSummary(result));
    onConnectionChanged(null);
  };

  return (
    <div className="column" data-width="wide">
      <h1 className="section-title">Settings</h1>

      {summary && (
        <div className={`notice ${summary.tone}`} role="status">
          <p>{summary.text}</p>
        </div>
      )}

      <section className="panel" aria-labelledby="settings-connection">
        <h2 id="settings-connection">Notion connection</h2>
        {info.connected ? (
          <>
            <WorkspaceBadge info={info} />
            <dl className="facts">
              <dt>How</dt>
              <dd>{authKindLabel(info.auth_kind)}</dd>
              <dt>Work log</dt>
              <dd>{info.database_title ?? "Not chosen yet"}</dd>
              {info.data_source_id && (
                <>
                  <dt>Columns</dt>
                  <dd>
                    {info.mapping_saved ? "Mapped" : "Not mapped yet"}
                    {(sync?.load.status === "ready"
                      ? sync.load.sync.full_sync_required
                      : Boolean(info.full_sync_required)) && (
                      <span className="chip warn">Full sync required</span>
                    )}
                  </dd>
                </>
              )}
            </dl>
            <div className="actions">
              <button type="button" className="button" onClick={onChangeDatabase}>
                {info.database_title ? "Choose a different database" : "Choose your work log"}
              </button>
              {info.data_source_id && (
                <button type="button" className="button" onClick={onReviewMapping}>
                  {info.mapping_saved ? "Review column mapping" : "Map your columns"}
                </button>
              )}
              <button
                type="button"
                className="button danger"
                onClick={() => {
                  setSummary(null);
                  setDisconnecting(true);
                }}
              >
                Disconnect
              </button>
            </div>
          </>
        ) : (
          <p className="muted">
            Not connected. Use Connect to Notion on the home screen, or a token below.
          </p>
        )}
      </section>

      {sync?.load.status === "ready" && (
        <section className="panel" aria-labelledby="settings-sync">
          <h2 id="settings-sync">Sync</h2>
          <dl className="facts">
            <dt>Last sync</dt>
            <dd>
              {sync.load.sync.last_successful_sync
                ? formatWhen(sync.load.sync.last_successful_sync)
                : "Never"}
            </dd>
            <dt>Last full sync</dt>
            <dd>
              {sync.load.sync.last_full_sync ? formatWhen(sync.load.sync.last_full_sync) : "Never"}
            </dd>
            <dt>Entries</dt>
            <dd className="figure">{sync.load.sync.entries.toLocaleString()}</dd>
          </dl>
          <p className="small muted">
            Each launch copies new and edited entries. A full sync reads every entry again: it
            refreshes formula and rollup values, which Notion doesn&apos;t mark as edits, and
            removes entries deleted in Notion. It runs on its own at least once a day.
          </p>
          <div className="actions">
            <button
              type="button"
              className="button"
              disabled={sync.load.sync.running?.kind === "full"}
              onClick={() => {
                sync.start("full");
              }}
            >
              {sync.load.sync.running?.kind === "full" ? "Full sync running…" : "Run full sync"}
            </button>
            {sync.load.sync.running && sync.load.sync.running.kind !== "full" && (
              <span className="small muted">Runs after the current sync.</span>
            )}
          </div>
          {sync.startProblem && <p className="field-error">{sync.startProblem.message}</p>}
        </section>
      )}

      {sync && <DashboardSettings />}

      <section className="panel" aria-labelledby="settings-advanced">
        <h2 id="settings-advanced" tabIndex={focusAdvanced ? -1 : undefined}>
          Connect with a token
        </h2>
        <p className="muted">
          For workspaces that block Notion sign-in for outside apps, or if you&apos;d rather not use
          Habit Tracker&apos;s sign-in service. The token goes straight from this computer to
          Notion.
        </p>
        <TokenForm
          replacing={info.connected ? connectionLabel(info) : null}
          onConnected={(updated) => {
            setSummary({ tone: "ok", text: `Connected to ${connectionLabel(updated)}.` });
            onConnectionChanged(updated);
          }}
        />
      </section>

      {details && (
        <section className="panel" aria-labelledby="settings-about">
          <h2 id="settings-about">About this copy</h2>
          <dl className="facts">
            <dt>Version</dt>
            <dd className="figure">{details.version}</dd>
            <dt>Data folder</dt>
            <dd>
              <code>{details.data_dir}</code>
            </dd>
            <dt>Logs</dt>
            <dd>
              <code>{details.log_dir}</code>{" "}
              <button
                type="button"
                className="button small"
                onClick={() => {
                  callPython("open_log_folder").catch((error: unknown) => {
                    noticeFromCallError(error, "The log folder couldn't be opened");
                  });
                }}
              >
                Open log folder
              </button>
            </dd>
          </dl>
        </section>
      )}

      {details?.diagnostics && (
        <>
          <h2 className="section-title">Diagnostics</h2>
          <AppInfoCard state={appInfo} />
          <BridgeCheckCard
            state={bridgeCheck.state}
            events={bridgeCheck.events}
            onStart={bridgeCheck.start}
          />
          <DiagnosticsPanel />
        </>
      )}

      {disconnecting && (
        <DisconnectDialog
          info={info}
          onClose={() => {
            setDisconnecting(false);
          }}
          onDisconnected={onDisconnected}
        />
      )}
    </div>
  );
}
