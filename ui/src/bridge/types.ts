// Types for the Python JS API (app/api.py) and the events it pushes (app/events.py).
// Keep these in step with the Python side.

export type Mode = "dev" | "normal";

export interface ErrorReport {
  id: string;
  kind: "expected" | "unexpected";
  message: string;
  detail: string | null;
  /** The error's UI state, e.g. "reconnect", "offline" (AppError.state in Python). */
  code?: ErrorCode | null;
}

export type ErrorCode =
  | "offline"
  | "reconnect"
  | "paste_new_token"
  | "service_unreachable"
  | "credential_store"
  | "notion_error"
  | "not_connected"
  | "invalid_token"
  | "confirm_replace";

export type AuthKind = "oauth" | "internal" | "pat";
export type PastedKind = "internal" | "pat";

export type WorkspaceIcon = { type: "emoji"; value: string } | { type: "image"; value: string };

export interface ConnectionInfo {
  connected: boolean;
  auth_kind: AuthKind | null;
  workspace_name: string | null;
  workspace_icon: WorkspaceIcon | null;
  account_name: string | null;
  database_id: string | null;
  data_source_id: string | null;
  database_title: string | null;
}

export interface DataSourceChoice {
  id: string;
  name: string;
}

export interface DatabaseGroup {
  database_id: string;
  title: string;
  icon_emoji: string | null;
  data_sources: DataSourceChoice[];
}

export interface DataSourcePage {
  groups: DatabaseGroup[];
  next_cursor: string | null;
  sharing_help_url: string;
}

export interface LogoutResult {
  kind: AuthKind | null;
  revoked: boolean | null;
  revoke_error: string | null;
  cleared_local_data: boolean;
}

export type SignInResult =
  | "connected"
  | "cancelled"
  | "access_denied"
  | "expired"
  | "timeout"
  | "service_unreachable"
  | "notion_error"
  | "error";

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
  get_connection(): Promise<BridgeResponse<ConnectionInfo>>;
  connect_with_token(kind: PastedKind, token: string): Promise<BridgeResponse<ConnectionInfo>>;
  start_sign_in(): Promise<BridgeResponse<{ port: number; reopened: boolean }>>;
  cancel_sign_in(): Promise<BridgeResponse<null>>;
  logout(clearLocalData: boolean): Promise<BridgeResponse<LogoutResult>>;
  list_data_sources(cursor: string | null): Promise<BridgeResponse<DataSourcePage>>;
  choose_data_source(
    databaseId: string,
    dataSourceId: string,
    confirmReplace: boolean,
  ): Promise<BridgeResponse<ConnectionInfo>>;
  open_external(url: string): Promise<BridgeResponse<null>>;
}

/** Events Python pushes to the UI, by name. */
export interface BackendEvents {
  "bridge-check:progress": { run_id: string; step: number; steps: number; thread: string };
  "bridge-check:done": { run_id: string; elapsed_ms: number };
  "app:error": ErrorReport;
  "connect:waiting": { timeout_s: number };
  "connect:done": { result: SignInResult; message?: string; connection?: ConnectionInfo };
}

export type BackendEventName = keyof BackendEvents;

export type BackendEvent = {
  [K in BackendEventName]: { name: K; payload: BackendEvents[K] };
}[BackendEventName];
