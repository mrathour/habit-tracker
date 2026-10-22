import { useEffect, useRef, useState } from "react";

import { callPython, waitForBridge } from "./bridge/client";
import type { ConnectionInfo } from "./bridge/types";
import { BrandMark } from "./components/BrandMark";
import { ErrorBanners } from "./components/ErrorBanners";
import { useAppInfo } from "./components/useAppInfo";
import { WorkspaceBadge } from "./components/WorkspaceBadge";
import { useConnection } from "./connection/useConnection";
import { SyncIndicator } from "./sync/SyncIndicator";
import { useSync } from "./sync/useSync";
import { ConnectView } from "./views/ConnectView";
import { HomeView } from "./views/HomeView";
import { MappingView } from "./views/MappingView";
import { PickerView } from "./views/PickerView";
import { SettingsView } from "./views/SettingsView";

type View = "home" | "settings";

const DISCONNECTED: ConnectionInfo = {
  connected: false,
  auth_kind: null,
  workspace_name: null,
  workspace_icon: null,
  account_name: null,
  database_id: null,
  data_source_id: null,
  database_title: null,
  mapping_saved: false,
  full_sync_required: null,
};

export function App() {
  const appInfo = useAppInfo();
  const connection = useConnection();
  const [view, setView] = useState<View>("home");
  const [choosing, setChoosing] = useState(false);
  const [mapping, setMapping] = useState(false);
  const [focusAdvanced, setFocusAdvanced] = useState(false);
  const [mappingSaved, setMappingSaved] = useState<{ fullSync: boolean } | null>(null);

  // Tell Python the page's event listeners are attached. Child effects run first, so every
  // hook above has subscribed by now and no pushed event is missed.
  useEffect(() => {
    waitForBridge()
      .then(() => callPython("ui_ready"))
      .catch(() => undefined);
  }, []);

  const details = appInfo.status === "ready" ? appInfo.info : null;
  const info = connection.load.status === "ready" ? connection.load.info : null;

  // Syncing needs a connection, a chosen work log and a saved mapping. Each launch runs one
  // sync ("auto": quick, or full when it's due), once those are in place (PLAN.md 6.1).
  const canSync = Boolean(info?.connected && info.data_source_id && info.mapping_saved);
  const sync = useSync(canSync);
  const launched = useRef(false);
  const startSync = sync.start;
  useEffect(() => {
    if (canSync && !launched.current) {
      launched.current = true;
      startSync("auto");
    }
  }, [canSync, startSync]);

  const go = (next: View) => {
    setView(next);
    setChoosing(false);
    setMapping(false);
    setFocusAdvanced(false);
    setMappingSaved(null);
  };

  const pasteNewToken = () => {
    setView("settings");
    setMapping(false);
    setFocusAdvanced(true);
  };

  const chooseDatabase = () => {
    setView("home");
    setMapping(false);
    setChoosing(true);
  };

  const ready = info?.connected && !choosing && info.data_source_id;

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">
          <BrandMark />
          Habit Tracker
        </span>
        {info?.connected && <WorkspaceBadge info={info} small />}
        {canSync && sync.load.status === "ready" && <SyncIndicator sync={sync.load.sync} />}
        {details?.mode === "dev" && <span className="dev-flag">Dev mode</span>}
        <nav aria-label="Main">
          <button
            type="button"
            className="nav-link"
            aria-current={view === "home" ? "page" : undefined}
            onClick={() => {
              go("home");
            }}
          >
            Home
          </button>
          <button
            type="button"
            className="nav-link"
            aria-current={view === "settings" ? "page" : undefined}
            onClick={() => {
              go("settings");
            }}
          >
            Settings
          </button>
        </nav>
      </header>
      <ErrorBanners />
      <main className="page">
        {connection.load.status === "loading" && (
          <p className="status" role="status">
            <span className="spinner" aria-hidden="true" /> Starting…
          </p>
        )}
        {connection.load.status === "unavailable" && (
          <div className="notice warn" role="alert">
            <strong>Open this inside Habit Tracker</strong>
            <p>
              This page isn&apos;t running inside the Habit Tracker window, so it can&apos;t reach
              Python. Start the app with <code>uv run habit-tracker --dev</code>.
            </p>
          </div>
        )}
        {connection.load.status === "error" && (
          <div className="notice error" role="alert">
            <strong>The Notion connection couldn&apos;t be read</strong>
            <p>{connection.load.message}</p>
            {connection.load.errorId && (
              <p className="small muted">Error ID {connection.load.errorId}</p>
            )}
            <div className="actions">
              <button type="button" className="button" onClick={connection.reload}>
                Try again
              </button>
            </div>
          </div>
        )}
        {info && view === "settings" && (
          <SettingsView
            info={info}
            appInfo={appInfo}
            focusAdvanced={focusAdvanced}
            onConnectionChanged={(updated) => {
              connection.setInfo(updated ?? { ...DISCONNECTED });
              if (updated === null) connection.reload();
            }}
            onChangeDatabase={chooseDatabase}
            onReviewMapping={() => {
              setView("home");
              setMappingSaved(null);
              setMapping(true);
            }}
            sync={canSync ? sync : null}
          />
        )}
        {info && view === "home" && !info.connected && (
          <ConnectView onConnected={connection.setInfo} />
        )}
        {info && view === "home" && info.connected && (choosing || !info.data_source_id) && (
          <PickerView
            info={info}
            onChosen={(updated) => {
              connection.setInfo(updated);
              setChoosing(false);
            }}
            onCancel={
              info.data_source_id
                ? () => {
                    setChoosing(false);
                  }
                : undefined
            }
            onPasteNewToken={pasteNewToken}
          />
        )}
        {info && view === "home" && ready && (mapping || !info.mapping_saved) && (
          <MappingView
            info={info}
            onSaved={(updated, result) => {
              connection.setInfo(updated);
              setMapping(false);
              setMappingSaved({ fullSync: result.changed });
              // First setup copies every entry; a changed mapping refreshes them all.
              launched.current = true;
              sync.start("auto");
            }}
            onCancel={
              info.mapping_saved
                ? () => {
                    setMapping(false);
                  }
                : undefined
            }
            onChooseDatabase={chooseDatabase}
            onPasteNewToken={pasteNewToken}
          />
        )}
        {info && view === "home" && ready && !mapping && info.mapping_saved && (
          <HomeView
            info={info}
            sync={sync}
            onPasteNewToken={pasteNewToken}
            justSaved={mappingSaved}
            onChangeDatabase={chooseDatabase}
            onReviewMapping={() => {
              setMappingSaved(null);
              setMapping(true);
            }}
          />
        )}
      </main>
    </div>
  );
}
