import { type Mock, vi } from "vitest";

import { DOM_EVENT_NAME } from "../bridge/events";
import type {
  AppInfo,
  BackendEvent,
  BridgeResponse,
  ConnectionInfo,
  DataSourcePage,
  ErrorCode,
  MappingReview,
  PythonApi,
} from "../bridge/types";
import fixtures from "./mappingFixtures.json";

/**
 * Mapping reviews made by the real Python service (tests/support/ui_fixtures.py): the Work
 * Log, no end-time column, a single date-range column, ambiguous columns, an empty database,
 * and a saved mapping whose columns then changed in Notion.
 */
export const reviews = fixtures as unknown as Record<
  "workLog" | "noEnd" | "range" | "ambiguous" | "empty" | "changed",
  MappingReview
>;

export const appInfo: AppInfo = {
  name: "Habit Tracker",
  version: "0.1.0",
  mode: "dev",
  diagnostics: true,
  python_version: "3.12.10",
  sqlite_version: "3.49.1",
  pywebview_version: "6.2.1",
  platform: "Windows-10",
  data_dir: "C:\\Users\\me\\AppData\\Roaming\\HabitTracker",
  database_path: "C:\\Users\\me\\AppData\\Roaming\\HabitTracker\\habit_tracker.db",
  log_dir: "C:\\Users\\me\\AppData\\Roaming\\HabitTracker\\logs",
  schema_version: 1,
  started_at: "2026-10-18T05:00:00Z",
};

export const disconnected: ConnectionInfo = {
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

export const connectedNoDatabase: ConnectionInfo = {
  ...disconnected,
  connected: true,
  auth_kind: "oauth",
  workspace_name: "Mayank's Notion",
  workspace_icon: { type: "emoji", value: "🎯" },
};

export const connectedWithDatabase: ConnectionInfo = {
  ...connectedNoDatabase,
  database_id: "db-1",
  data_source_id: "ds-1",
  database_title: "Work Log (test)",
  mapping_saved: true,
};

/** A database is chosen but its columns aren't mapped yet: the mapping screen shows. */
export const connectedUnmapped: ConnectionInfo = {
  ...connectedWithDatabase,
  database_title: "Work Log",
  mapping_saved: false,
};

export const twoDatabases: DataSourcePage = {
  groups: [
    {
      database_id: "db-1",
      title: "Work Log (test)",
      icon_emoji: "⏱️",
      data_sources: [{ id: "ds-1", name: "Work Log (test)" }],
    },
    {
      database_id: "db-2",
      title: "Reading",
      icon_emoji: null,
      data_sources: [
        { id: "ds-2a", name: "Books" },
        { id: "ds-2b", name: "Articles" },
      ],
    },
  ],
  next_cursor: null,
  sharing_help_url: "https://habit-tracker.mrathour.workers.dev/support",
};

export function failWith(
  code: ErrorCode,
  message: string,
  id = "c0de0001",
): Promise<BridgeResponse<never>> {
  return Promise.resolve({
    ok: false,
    error: { id, kind: "expected", message, detail: null, code },
  });
}

export function ok<T>(data: T): Promise<BridgeResponse<T>> {
  return Promise.resolve({ ok: true, data });
}

export function fail(message: string, id = "abcd1234"): Promise<BridgeResponse<never>> {
  return Promise.resolve({
    ok: false,
    error: { id, kind: "unexpected", message, detail: "RuntimeError: boom" },
  });
}

/** Install a fake `window.pywebview.api`. Pass overrides for the methods a test cares about. */
export function installFakeBridge(overrides: Partial<PythonApi> = {}) {
  const api = {
    get_app_info: vi.fn(() => ok(appInfo)),
    ui_ready: vi.fn(() => ok(null)),
    run_bridge_check: vi.fn((steps: number) => ok({ run_id: "run-1", steps })),
    log_client_error: vi.fn(() => ok({ id: "e1e2e3e4" })),
    open_log_folder: vi.fn(() => ok(null)),
    raise_test_error: vi.fn(() => ok(null)),
    quit: vi.fn(() => ok(null)),
    get_connection: vi.fn(() => ok(disconnected)),
    connect_with_token: vi.fn(() => ok(connectedNoDatabase)),
    start_sign_in: vi.fn(() => ok({ port: 50000, reopened: false })),
    cancel_sign_in: vi.fn(() => ok(null)),
    logout: vi.fn((clear: boolean) =>
      ok({ kind: "oauth" as const, revoked: true, revoke_error: null, cleared_local_data: clear }),
    ),
    list_data_sources: vi.fn(() => ok(twoDatabases)),
    choose_data_source: vi.fn(() => ok(connectedWithDatabase)),
    get_mapping_review: vi.fn(() => ok(reviews.workLog)),
    save_mapping: vi.fn<PythonApi["save_mapping"]>(() =>
      ok({ changed: false, full_sync_required: null }),
    ),
    open_external: vi.fn(() => ok(null)),
  };
  // Overrides replace the default behaviour but stay spies, so tests can assert on calls
  // and change the behaviour again later.
  for (const [name, implementation] of Object.entries(overrides)) {
    const spy = api[name as keyof typeof api] as unknown as Mock;
    spy.mockImplementation(implementation as (...args: unknown[]) => unknown);
  }
  window.pywebview = { api };
  return api;
}

export function removeFakeBridge(): void {
  delete window.pywebview;
}

/** Dispatch an event the way app/events.py does. */
export function pushBackendEvent(event: BackendEvent): void {
  window.dispatchEvent(new CustomEvent(DOM_EVENT_NAME, { detail: event }));
}
