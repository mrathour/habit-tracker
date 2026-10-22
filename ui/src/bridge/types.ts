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
  | "confirm_replace"
  | "no_database"
  | "source_unavailable"
  | "mapping_invalid";

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
  /** A column mapping is saved for the chosen data source (PLAN.md 4). */
  mapping_saved: boolean;
  /** Set when the mapping changed after its first save; a full sync clears it. */
  full_sync_required: FullSyncFlag | null;
}

export interface FullSyncFlag {
  since: string;
  reason: string;
}

// --- Column mapping (app/mapping/review.py) ----------------------------------------------

export type FieldKey =
  "start" | "end" | "task_name" | "parent_task" | "display_id" | "logged_minutes";

export type DatePart = "start" | "end";

/** Where an app field's value comes from. Date fields also name the part of the date. */
export interface FieldRef {
  property_id: string;
  part?: DatePart;
}

export interface SampleMoment {
  /** ISO 8601 UTC, or null for a date without a time. */
  utc: string | null;
  /** The calendar date as written in Notion, YYYY-MM-DD. */
  date: string;
  has_time: boolean;
}

export type Sample =
  { kind: "text"; text: string } | { kind: "date"; start: SampleMoment; end: SampleMoment | null };

export interface ColumnInfo {
  id: string;
  name: string;
  type: string;
  type_label: string;
  readable: boolean;
  reason: string | null;
  note: string | null;
  samples: Sample[];
  filled: number;
  has_range: boolean;
  dates_without_time: number;
  formula_types: string[];
}

export interface FieldOption {
  property_id: string;
  part: DatePart | null;
  label: string;
}

export type FieldStatus =
  "auto" | "saved" | "choose" | "missing" | "removed" | "type_changed" | "unused";

export interface FieldReview {
  key: FieldKey;
  label: string;
  required: boolean;
  description: string;
  needs: string;
  selection: FieldRef | null;
  status: FieldStatus;
  choose_from: string[];
  options: FieldOption[];
  message: string | null;
  missing_help: string | null;
}

export interface SchemaIssue {
  code: string;
  field: string | null;
  property_id: string | null;
  message: string;
}

export interface SchemaCheck {
  ok: boolean;
  blocking: SchemaIssue[];
  warnings: SchemaIssue[];
  renamed: { property_id: string; old_name: string; new_name: string }[];
}

export interface MappingReview {
  data_source_id: string;
  database_title: string | null;
  columns: ColumnInfo[];
  fields: FieldReview[];
  extra: string[];
  saved: boolean;
  saved_at: string | null;
  rows_sampled: number;
  sample_limit: number;
  full_sync_required: FullSyncFlag | null;
  schema_check: SchemaCheck | null;
}

export interface SaveMappingResult {
  changed: boolean;
  full_sync_required: FullSyncFlag | null;
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
  get_mapping_review(): Promise<BridgeResponse<MappingReview>>;
  save_mapping(
    fields: Record<FieldKey, FieldRef | null>,
    extra: string[],
  ): Promise<BridgeResponse<SaveMappingResult>>;
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
