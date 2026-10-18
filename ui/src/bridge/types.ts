// Types for the Python JS API (app/api.py) and the events it pushes (app/events.py).
// Keep these in step with the Python side.

export type Mode = "dev" | "normal";

export interface ErrorReport {
  id: string;
  kind: "expected" | "unexpected";
  message: string;
  detail: string | null;
}

export type BridgeResponse<T> = { ok: true; data: T } | { ok: false; error: ErrorReport };

export interface AppInfo {
  name: string;
  version: string;
  mode: Mode;
  diagnostics: boolean;
  python_version: string;
  sqlite_version: string;
  pywebview_version: string;
  platform: string;
  data_dir: string;
  database_path: string;
  log_dir: string;
  schema_version: number;
  started_at: string;
}

export interface BridgeCheckStarted {
  run_id: string;
  steps: number;
}

export interface ClientErrorReport {
  source: "render" | "window" | "promise";
  message: string;
  stack?: string | undefined;
  componentStack?: string | undefined;
}

export type TestErrorLocation = "call" | "thread";

/** Methods on `window.pywebview.api`. Each resolves to a {@link BridgeResponse}. */
export interface PythonApi {
  get_app_info(): Promise<BridgeResponse<AppInfo>>;
  ui_ready(): Promise<BridgeResponse<null>>;
  run_bridge_check(steps: number): Promise<BridgeResponse<BridgeCheckStarted>>;
  log_client_error(report: ClientErrorReport): Promise<BridgeResponse<{ id: string }>>;
  open_log_folder(): Promise<BridgeResponse<null>>;
  raise_test_error(where: TestErrorLocation): Promise<BridgeResponse<null>>;
  quit(): Promise<BridgeResponse<null>>;
}

/** Events Python pushes to the UI, by name. */
export interface BackendEvents {
  "bridge-check:progress": { run_id: string; step: number; steps: number; thread: string };
  "bridge-check:done": { run_id: string; elapsed_ms: number };
  "app:error": ErrorReport;
}

export type BackendEventName = keyof BackendEvents;

export type BackendEvent = {
  [K in BackendEventName]: { name: K; payload: BackendEvents[K] };
}[BackendEventName];
