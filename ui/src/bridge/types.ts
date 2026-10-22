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
  | "mapping_invalid"
  | "not_ready"
  | "schema_blocked"
  | "invalid_request"
  | "invalid_preference"
  | "export_failed";

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

// --- Sync (app/sync/engine.py) ------------------------------------------------------------

export type SyncKind = "quick" | "full";
export type SyncRequest = "auto" | SyncKind;

export interface SyncProgress {
  kind: SyncKind | null;
  phase: "checking" | "fetching" | "removing";
  pages_fetched: number;
  added: number;
  updated: number;
  removed: number;
}

export interface SyncError {
  id: string;
  code: ErrorCode | null;
  message: string;
  /** For "schema_blocked": what changed in Notion. */
  issues: SchemaIssue[];
}

export interface SyncResult {
  kind: SyncKind | null;
  reason: string | null;
  finished_at: string;
  ok: boolean;
  added: number;
  updated: number;
  removed: number;
  flagged: number;
  skipped: number;
  warnings: string[];
  pending_removal: number | null;
  error: SyncError | null;
}

export interface PendingRemoval {
  count: number;
  total: number;
  found_at: string;
}

export interface SyncStatus {
  running: SyncProgress | null;
  last_result: SyncResult | null;
  last_successful_sync: string | null;
  last_full_sync: string | null;
  entries: number;
  flagged: number;
  pending_removal: PendingRemoval | null;
  full_sync_required: boolean;
}

export interface Issue {
  /** "start", "end", "logged_minutes" or "extra:<property id>". */
  field: string;
  code: "missing_time" | "invalid_range" | "duration_mismatch" | "unreadable_extra";
  message: string;
}

export interface FlaggedEntry {
  page_id: string;
  display_id: string | null;
  task_name: string | null;
  start_utc: string | null;
  end_utc: string | null;
  issues: Issue[];
  url: string;
}

export interface FlaggedPage {
  entries: FlaggedEntry[];
  total: number;
}

// --- Raw log (app/rawlog/) ---------------------------------------------------------------

export type IssueCode = Issue["code"];
export type SortDirection = "asc" | "desc";

export interface SortSpec {
  column: string;
  direction: SortDirection;
}

/** The raw log's remembered sort, column widths and hidden columns (`raw_log_view`). */
export interface RawLogViewPrefs {
  sort: SortSpec;
  widths: Record<string, number>;
  hidden: string[];
}

export type ExtraFilterKind = "text" | "number" | "checkbox" | "options" | "date" | "presence";

export type ExtraFilter =
  | { op: "empty" }
  | { op: "not_empty" }
  | { op: "contains"; value: string }
  | { op: "range"; min?: number | null; max?: number | null }
  | { op: "is"; value: boolean }
  | { op: "any_of"; values: string[] }
  | { op: "dates"; from?: string | null; to?: string | null };

export interface RawLogFilters {
  date_from?: string | null;
  date_to?: string | null;
  search?: string;
  parents?: string[];
  no_parent?: boolean;
  duration_min?: number | null;
  duration_max?: number | null;
  issues?: "any" | "none" | null;
  issue_codes?: IssueCode[];
  overlaps?: boolean;
  extra?: Record<string, ExtraFilter>;
}

export interface RawLogRequest {
  time_zone: string;
  filters: RawLogFilters;
  /** Leave out to use the remembered sort. */
  sort?: SortSpec;
  offset: number;
  limit: number;
}

export type RawLogColumnKind =
  | "display_id"
  | "task_name"
  | "start"
  | "end"
  | "duration"
  | "logged_minutes"
  | "parent_task"
  | "extra"
  | "overlap"
  | "issues";

export interface RawLogColumn {
  key: string;
  label: string;
  kind: RawLogColumnKind;
  type: string | null;
  type_label: string | null;
  filter: ExtraFilterKind | null;
  options: string[];
}

export interface MomentCell {
  utc: string | null;
  date: string;
  has_time: boolean;
}

export interface ExtraCell {
  text: string;
  start?: MomentCell;
  end?: MomentCell | null;
  links?: string[];
}

export interface RawLogRow {
  page_id: string;
  url: string;
  display_id: string | null;
  task_name: string | null;
  start_utc: string | null;
  end_utc: string | null;
  duration_minutes: number | null;
  logged_minutes: number | null;
  parent_task_ids: string[];
  parent_urls: string[];
  extras: Record<string, ExtraCell | null>;
  issues: Issue[];
  overlap_minutes: number;
  overlaps_with: { page_id: string; label: string }[];
}

export interface ParentChoice {
  page_id: string;
  url: string;
  entries: number;
  latest_task_name: string | null;
}

export interface RawLogPage {
  time_zone: string;
  total_entries: number;
  matched: number;
  offset: number;
  rows: RawLogRow[];
  sort: SortSpec;
  columns: RawLogColumn[];
  parents: ParentChoice[];
  view: RawLogViewPrefs;
}

export interface ExportResult {
  status: "saved" | "cancelled" | "empty";
  path: string | null;
  rows: number;
}

// --- Dashboard (app/stats/) --------------------------------------------------------------

export type Weekday =
  "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";

export interface Preferences {
  /** 0 means any time at all; otherwise a streak day needs at least this many minutes. */
  streak_threshold_minutes: number;
  week_start: Weekday;
  midnight_rule: "split" | "start_date";
  overlap_rule: "once" | "sum";
}

export type DailyRange = { days: 7 | 30 | 90 } | { from: string; to: string };

export interface DashboardRequest {
  time_zone: string;
  range: DailyRange;
  weeks: 12 | 26 | 52;
  /** null for the last 12 months. */
  year: number | null;
}

export interface DayTotal {
  date: string;
  minutes: number;
  sessions: number;
}

export interface WeekTotal {
  start: string;
  end: string;
  minutes: number;
  rolling_average: number | null;
  partial: boolean;
}

export interface Streak {
  days: number;
  start: string;
  end: string;
}

export interface Dashboard {
  time_zone: string;
  today: string;
  preferences: Preferences;
  entries: number;
  counted_sessions: number;
  excluded: number;
  flagged: number;
  daily: {
    first: string;
    last: string;
    days: DayTotal[];
    total_minutes: number;
    active_days: number;
  };
  weekly: WeekTotal[];
  streaks: {
    current: Streak | null;
    longest: Streak | null;
    today_counts: boolean;
    threshold_minutes: number;
  };
  calendar: {
    first: string;
    last: string;
    year: number | null;
    days: DayTotal[];
    total_minutes: number;
    max_minutes: number;
    years: number[];
  };
}

export interface DetailSession {
  page_id: string;
  display_id: string | null;
  task_name: string | null;
  start_utc: string;
  end_utc: string;
  minutes: number;
  counted_minutes: number;
  crosses_midnight: boolean;
  overlap_minutes: number;
  overlaps_with: { page_id: string; label: string }[];
  url: string;
}

export interface DayDetail {
  date: string;
  time_zone: string;
  minutes: number;
  preferences: Preferences;
  sessions: DetailSession[];
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
  get_sync_status(): Promise<BridgeResponse<SyncStatus>>;
  start_sync(kind: SyncRequest): Promise<BridgeResponse<SyncStatus>>;
  get_flagged_entries(offset: number, limit: number): Promise<BridgeResponse<FlaggedPage>>;
  resolve_pending_removal(remove: boolean): Promise<BridgeResponse<SyncStatus>>;
  get_dashboard(request: DashboardRequest): Promise<BridgeResponse<Dashboard>>;
  get_day_detail(timeZone: string, day: string): Promise<BridgeResponse<DayDetail>>;
  get_preferences(): Promise<BridgeResponse<Preferences>>;
  set_preferences(changes: Partial<Preferences>): Promise<BridgeResponse<Preferences>>;
  get_raw_log(request: RawLogRequest): Promise<BridgeResponse<RawLogPage>>;
  set_raw_log_view(changes: Partial<RawLogViewPrefs>): Promise<BridgeResponse<RawLogViewPrefs>>;
  export_raw_log(
    request: Omit<RawLogRequest, "offset" | "limit">,
    columns: string[],
  ): Promise<BridgeResponse<ExportResult>>;
  show_exported_file(): Promise<BridgeResponse<null>>;
  open_external(url: string): Promise<BridgeResponse<null>>;
}

/** Events Python pushes to the UI, by name. */
export interface BackendEvents {
  "bridge-check:progress": { run_id: string; step: number; steps: number; thread: string };
  "bridge-check:done": { run_id: string; elapsed_ms: number };
  "app:error": ErrorReport;
  "connect:waiting": { timeout_s: number };
  "connect:done": { result: SignInResult; message?: string; connection?: ConnectionInfo };
  "sync:status": SyncStatus;
}

export type BackendEventName = keyof BackendEvents;

export type BackendEvent = {
  [K in BackendEventName]: { name: K; payload: BackendEvents[K] };
}[BackendEventName];
