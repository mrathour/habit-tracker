import { vi } from "vitest";

import { DOM_EVENT_NAME } from "../bridge/events";
import type { AppInfo, BackendEvent, BridgeResponse, PythonApi } from "../bridge/types";

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
    ...overrides,
  };
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
