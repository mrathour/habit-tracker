import { type Mock, vi } from "vitest";

import { DOM_EVENT_NAME } from "../bridge/events";
import type {
  AppInfo,
  BackendEvent,
  BridgeResponse,
  ConnectionInfo,
  Dashboard,
  DataSourcePage,
  DayDetail,
  DayTotal,
  ErrorCode,
  FlaggedPage,
  MappingReview,
  PythonApi,
  SyncResult,
  SyncStatus,
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

export const neverSynced: SyncStatus = {
  running: null,
  last_result: null,
  last_successful_sync: null,
  last_full_sync: null,
  entries: 0,
  flagged: 0,
  pending_removal: null,
  full_sync_required: false,
};

export const fullSyncDone: SyncResult = {
  kind: "full",
  reason: "First sync of this work log.",
  finished_at: "2026-10-22T10:00:00.000Z",
  ok: true,
  added: 7,
  updated: 0,
  removed: 0,
  flagged: 5,
  skipped: 0,
  warnings: [],
  pending_removal: null,
  error: null,
};

export const synced: SyncStatus = {
  ...neverSynced,
  last_result: fullSyncDone,
  last_successful_sync: "2026-10-22T10:00:00.000Z",
  last_full_sync: "2026-10-22T10:00:00.000Z",
  entries: 7,
  flagged: 5,
};

export const flaggedPage: FlaggedPage = {
  total: 2,
  entries: [
    {
      page_id: "p-mismatch",
      display_id: "9",
      task_name: "Mismatch",
      start_utc: "2026-10-21T03:30:00.000Z",
      end_utc: "2026-10-21T05:33:00.000Z",
      issues: [
        {
          field: "logged_minutes",
          code: "duration_mismatch",
          message: "Logged 148 min, but Start → End is 123 min.",
        },
      ],
      url: "https://www.notion.so/pmismatch",
    },
    {
      page_id: "p-no-start",
      display_id: null,
      task_name: null,
      start_utc: null,
      end_utc: "2026-10-21T03:30:00.000Z",
      issues: [{ field: "start", code: "missing_time", message: "Start time is empty." }],
      url: "https://www.notion.so/pnostart",
    },
  ],
};

export const defaultPreferences = {
  streak_threshold_minutes: 0,
  week_start: "monday",
  midnight_rule: "split",
  overlap_rule: "once",
} as const;

function dayRange(last: string, count: number, minutes: (index: number) => number): DayTotal[] {
  const end = Date.parse(`${last}T00:00:00Z`);
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(end - (count - 1 - i) * 86_400_000).toISOString().slice(0, 10);
    const value = minutes(i);
    return { date, minutes: value, sessions: value > 0 ? 1 : 0 };
  });
}

/** Nothing copied yet: the dashboard's empty state. */
export const emptyDashboard: Dashboard = {
  time_zone: "Asia/Kolkata",
  today: "2026-10-22",
  preferences: defaultPreferences,
  entries: 0,
  counted_sessions: 0,
  excluded: 0,
  flagged: 0,
  daily: {
    first: "2026-09-23",
    last: "2026-10-22",
    days: dayRange("2026-10-22", 30, () => 0),
    total_minutes: 0,
    active_days: 0,
  },
  weekly: [],
  streaks: { current: null, longest: null, today_counts: false, threshold_minutes: 0 },
  calendar: {
    first: "2025-10-23",
    last: "2026-10-22",
    year: null,
    days: [],
    total_minutes: 0,
    max_minutes: 0,
    years: [],
  },
};

const thirtyDays = dayRange("2026-10-22", 30, (i) => (i >= 27 ? 60 + i : i % 3 === 0 ? 45 : 0));

/** A work log with a few weeks of sessions. */
export const dashboard: Dashboard = {
  ...emptyDashboard,
  entries: 12,
  counted_sessions: 10,
  excluded: 2,
  flagged: 3,
  daily: {
    first: "2026-09-23",
    last: "2026-10-22",
    days: thirtyDays,
    total_minutes: thirtyDays.reduce((sum, d) => sum + d.minutes, 0),
    active_days: thirtyDays.filter((d) => d.minutes > 0).length,
  },
  weekly: [
    { start: "2026-10-05", end: "2026-10-11", minutes: 90, rolling_average: 90, partial: false },
    {
      start: "2026-10-12",
      end: "2026-10-18",
      minutes: 135,
      rolling_average: 112.5,
      partial: false,
    },
    { start: "2026-10-19", end: "2026-10-25", minutes: 240, rolling_average: 155, partial: true },
  ],
  streaks: {
    current: { days: 3, start: "2026-10-20", end: "2026-10-22" },
    longest: { days: 3, start: "2026-10-20", end: "2026-10-22" },
    today_counts: true,
    threshold_minutes: 0,
  },
  calendar: {
    first: "2025-10-23",
    last: "2026-10-22",
    year: null,
    days: dayRange("2026-10-22", 365, (i) => (i >= 335 ? (thirtyDays[i - 335]?.minutes ?? 0) : 0)),
    total_minutes: thirtyDays.reduce((sum, d) => sum + d.minutes, 0),
    max_minutes: 89,
    years: [2026, 2025],
  },
};

export const dayDetail: DayDetail = {
  date: "2026-10-21",
  time_zone: "Asia/Kolkata",
  minutes: 120,
  preferences: defaultPreferences,
  sessions: [
    {
      page_id: "p1",
      display_id: "1",
      task_name: "Write",
      start_utc: "2026-10-21T03:30:00.000Z",
      end_utc: "2026-10-21T05:00:00.000Z",
      minutes: 90,
      counted_minutes: 90,
      crosses_midnight: false,
      overlap_minutes: 30,
      overlaps_with: [{ page_id: "p2", label: "#2 Review" }],
      url: "https://www.notion.so/p1",
    },
    {
      page_id: "p2",
      display_id: "2",
      task_name: null,
      start_utc: "2026-10-21T04:30:00.000Z",
      end_utc: "2026-10-21T05:30:00.000Z",
      minutes: 60,
      counted_minutes: 30,
      crosses_midnight: false,
      overlap_minutes: 30,
      overlaps_with: [{ page_id: "p1", label: "#1 Write" }],
      url: "https://www.notion.so/p2",
    },
    {
      page_id: "p3",
      display_id: "3",
      task_name: "Late",
      start_utc: "2026-10-21T17:30:00.000Z",
      end_utc: "2026-10-21T19:30:00.000Z",
      minutes: 120,
      counted_minutes: 60,
      crosses_midnight: true,
      overlap_minutes: 0,
      overlaps_with: [],
      url: "https://www.notion.so/p3",
    },
  ],
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
    get_sync_status: vi.fn<PythonApi["get_sync_status"]>(() => ok(neverSynced)),
    start_sync: vi.fn<PythonApi["start_sync"]>(() => ok(neverSynced)),
    get_flagged_entries: vi.fn<PythonApi["get_flagged_entries"]>(() =>
      ok({ entries: [], total: 0 }),
    ),
    resolve_pending_removal: vi.fn<PythonApi["resolve_pending_removal"]>(() => ok(synced)),
    get_dashboard: vi.fn<PythonApi["get_dashboard"]>(() => ok(emptyDashboard)),
    get_day_detail: vi.fn<PythonApi["get_day_detail"]>(() => ok(dayDetail)),
    get_preferences: vi.fn<PythonApi["get_preferences"]>(() => ok(defaultPreferences)),
    set_preferences: vi.fn<PythonApi["set_preferences"]>((changes) =>
      ok({ ...defaultPreferences, ...changes }),
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
