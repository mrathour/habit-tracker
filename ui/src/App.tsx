import { useEffect, useState } from "react";

import { callPython, waitForBridge } from "./bridge/client";
import type { ConnectionInfo } from "./bridge/types";
import { BrandMark } from "./components/BrandMark";
import { ErrorBanners } from "./components/ErrorBanners";
import { useAppInfo } from "./components/useAppInfo";
import { WorkspaceBadge } from "./components/WorkspaceBadge";
import { useConnection } from "./connection/useConnection";
import { ConnectView } from "./views/ConnectView";
import { HomeView } from "./views/HomeView";
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
};

export function App() {
  const appInfo = useAppInfo();
  const connection = useConnection();
  const [view, setView] = useState<View>("home");
  const [choosing, setChoosing] = useState(false);
  const [focusAdvanced, setFocusAdvanced] = useState(false);

  // Tell Python the page's event listeners are attached. Child effects run first, so every
  // hook above has subscribed by now and no pushed event is missed.
  useEffect(() => {
    waitForBridge()
      .then(() => callPython("ui_ready"))
      .catch(() => undefined);
  }, []);

  const details = appInfo.status === "ready" ? appInfo.info : null;
  const info = connection.load.status === "ready" ? connection.load.info : null;

  const go = (next: View) => {
    setView(next);
    setChoosing(false);
    setFocusAdvanced(false);
  };

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">
          <BrandMark />
          Habit Tracker
        </span>
        {info?.connected && <WorkspaceBadge info={info} small />}
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
            onChangeDatabase={() => {
              setView("home");
              setChoosing(true);
            }}
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
            onPasteNewToken={() => {
              setView("settings");
              setFocusAdvanced(true);
            }}
          />
        )}
        {info && view === "home" && info.connected && !choosing && info.data_source_id && (
          <HomeView
            info={info}
            onChangeDatabase={() => {
              setChoosing(true);
            }}
          />
        )}
      </main>
    </div>
  );
}
