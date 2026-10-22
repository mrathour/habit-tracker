import { useCallback, useEffect, useMemo, useState } from "react";

import { callPython } from "../bridge/client";
import type {
  ColumnInfo,
  ConnectionInfo,
  DatePart,
  FieldKey,
  FieldReview,
  FieldStatus,
  MappingReview,
  SaveMappingResult,
} from "../bridge/types";
import { problemFrom, type Problem } from "../connection/problems";
import { SignInStatus } from "../connection/SignInStatus";
import { useSignIn } from "../connection/useSignIn";
import { formatSample } from "../mapping/format";
import {
  blockingReasons,
  choose,
  columnUsers,
  decodeRef,
  encodeRef,
  initialSelections,
  isDirty,
  NOT_USED,
  type Selections,
  UNCHOSEN,
  visibleOptions,
} from "../mapping/selection";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; review: MappingReview }
  | { status: "error"; problem: Problem };

const STATUS_LABELS: Record<FieldStatus, { text: string; tone: "ok" | "warn" | "error" | "" }> = {
  auto: { text: "Matched automatically", tone: "ok" },
  saved: { text: "Saved", tone: "ok" },
  choose: { text: "Please choose", tone: "warn" },
  missing: { text: "Missing", tone: "error" },
  removed: { text: "Column removed in Notion", tone: "error" },
  type_changed: { text: "Column type changed", tone: "error" },
  unused: { text: "Not used", tone: "" },
};

/**
 * Review and change which Notion column feeds each app field (PLAN.md 4.2), with sample values
 * from the latest entries so a wrong match is obvious at a glance.
 */
export function MappingView({
  info,
  onSaved,
  onCancel,
  onChooseDatabase,
  onPasteNewToken,
}: {
  info: ConnectionInfo;
  onSaved: (info: ConnectionInfo, result: SaveMappingResult) => void;
  onCancel?: (() => void) | undefined;
  onChooseDatabase: () => void;
  onPasteNewToken: () => void;
}) {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [selections, setSelections] = useState<Selections | null>(null);
  const [decided, setDecided] = useState<ReadonlySet<FieldKey>>(new Set());
  const [extra, setExtra] = useState<ReadonlySet<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saveProblem, setSaveProblem] = useState<Problem | null>(null);

  const fetchReview = useCallback(() => {
    callPython("get_mapping_review")
      .then((review) => {
        setSelections(initialSelections(review));
        setDecided(new Set());
        setExtra(new Set(review.extra));
        setLoad({ status: "ready", review });
      })
      .catch((error: unknown) => {
        setLoad({ status: "error", problem: problemFrom(error) });
      });
  }, []);

  useEffect(() => {
    fetchReview();
  }, [fetchReview]);

  const reload = useCallback(() => {
    setLoad({ status: "loading" });
    setSaveProblem(null);
    fetchReview();
  }, [fetchReview]);

  const signIn = useSignIn(() => {
    reload();
  });

  const review = load.status === "ready" ? load.review : null;
  const title = review?.database_title ?? info.database_title ?? "your work log";

  return (
    <section className="column mapping" aria-labelledby="mapping-title" data-width="mapping">
      <h1 id="mapping-title" className="section-title">
        {info.mapping_saved ? "Column mapping" : "Map your columns"}
      </h1>
      <p className="muted">
        Habit Tracker reads <strong>{title}</strong>. Check that each app field uses the right
        Notion column: the sample values come from your latest entries. Columns are remembered by
        their Notion ID, so renaming one later doesn&apos;t break anything.
      </p>

      {load.status === "loading" && (
        <ul className="picker-list" aria-busy="true" aria-label="Loading columns">
          {[0, 1, 2, 3].map((i) => (
            <li key={i} className="skeleton" />
          ))}
        </ul>
      )}

      {load.status === "error" && (
        <ProblemNotice
          problem={load.problem}
          onRetry={reload}
          onReconnect={signIn.start}
          onPasteNewToken={onPasteNewToken}
          onChooseDatabase={onChooseDatabase}
        />
      )}

      <SignInStatus
        state={signIn.state}
        onRetry={signIn.start}
        onCancel={signIn.cancel}
        onReopen={signIn.start}
      />

      {review && selections && (
        <MappingForm
          review={review}
          selections={selections}
          decided={decided}
          extra={extra}
          saving={saving}
          saveProblem={saveProblem}
          onChange={(key, value) => {
            setSelections(choose(selections, key, decodeRef(value)));
            setDecided(new Set([...decided, key]));
          }}
          onToggleExtra={(id, on) => {
            const next = new Set(extra);
            if (on) next.add(id);
            else next.delete(id);
            setExtra(next);
          }}
          onSave={(fields, extras) => {
            setSaving(true);
            setSaveProblem(null);
            callPython("save_mapping", fields, extras)
              .then(async (result) => {
                const updated = await callPython("get_connection");
                onSaved(updated, result);
              })
              .catch((error: unknown) => {
                setSaveProblem(problemFrom(error));
              })
              .finally(() => {
                setSaving(false);
              });
          }}
          onCancel={onCancel}
          onChooseDatabase={onChooseDatabase}
          onRetry={reload}
          onReconnect={signIn.start}
          onPasteNewToken={onPasteNewToken}
        />
      )}
    </section>
  );
}

function ProblemNotice({
  problem,
  onRetry,
  onReconnect,
  onPasteNewToken,
  onChooseDatabase,
}: {
  problem: Problem;
  onRetry: () => void;
  onReconnect: () => void;
  onPasteNewToken: () => void;
  onChooseDatabase: () => void;
}) {
  return (
    <div className={`notice ${problem.tone}`} role="alert">
      <strong>{problem.title}</strong>
      <p>{problem.message}</p>
      {problem.errorId && <p className="small muted">Error ID {problem.errorId}</p>}
      {problem.actions.length > 0 && (
        <div className="actions">
          {problem.actions.includes("reconnect") && (
            <button type="button" className="button primary" onClick={onReconnect}>
              Reconnect to Notion
            </button>
          )}
          {problem.actions.includes("paste_token") && (
            <button type="button" className="button primary" onClick={onPasteNewToken}>
              Paste a new token
            </button>
          )}
          {problem.actions.includes("choose_database") && (
            <button type="button" className="button primary" onClick={onChooseDatabase}>
              Choose the database again
            </button>
          )}
          {problem.actions.includes("retry") && (
            <button type="button" className="button" onClick={onRetry}>
              Try again
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function MappingForm({
  review,
  selections,
  decided,
  extra,
  saving,
  saveProblem,
  onChange,
  onToggleExtra,
  onSave,
  onCancel,
  onChooseDatabase,
  onRetry,
  onReconnect,
  onPasteNewToken,
}: {
  review: MappingReview;
  selections: Selections;
  decided: ReadonlySet<FieldKey>;
  extra: ReadonlySet<string>;
  saving: boolean;
  saveProblem: Problem | null;
  onChange: (key: FieldKey, value: string) => void;
  onToggleExtra: (id: string, on: boolean) => void;
  onSave: (fields: Selections, extra: string[]) => void;
  onCancel?: (() => void) | undefined;
  onChooseDatabase: () => void;
  onRetry: () => void;
  onReconnect: () => void;
  onPasteNewToken: () => void;
}) {
  const columns = useMemo(() => new Map(review.columns.map((c) => [c.id, c])), [review.columns]);
  const users = columnUsers(selections);
  const effectiveExtra = [...extra].filter((id) => !users.has(id) && columns.has(id));
  const reasons = blockingReasons(review, selections, decided);
  const dirty = isDirty(review, selections, new Set(effectiveExtra));
  const unmapped = review.columns.filter((c) => !users.has(c.id));
  const check = review.schema_check;
  const renamed = new Map(check?.renamed.map((r) => [r.property_id, r.old_name]));
  const labels = new Map(review.fields.map((f) => [f.key, f.label]));

  return (
    <>
      {review.full_sync_required && (
        <div className="notice warn" role="status">
          <strong>A full sync is needed</strong>
          <p>
            {review.full_sync_required.reason} It runs the next time Habit Tracker syncs your work
            log.
          </p>
        </div>
      )}

      {check && check.blocking.length > 0 && (
        <div className="notice error" role="alert">
          <strong>Syncing can&apos;t start until this is fixed</strong>
          <ul className="issue-list">
            {check.blocking.map((issue) => (
              <li key={`${issue.code}-${issue.field ?? issue.property_id ?? ""}`}>
                {issue.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {check && check.warnings.length > 0 && (
        <div className="notice warn" role="status">
          <strong>Some columns changed in Notion</strong>
          <ul className="issue-list">
            {check.warnings.map((issue) => (
              <li key={`${issue.code}-${issue.field ?? issue.property_id ?? ""}`}>
                {issue.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {review.rows_sampled === 0 && (
        <div className="notice ok" role="status">
          <strong>No entries yet</strong>
          <p>
            {review.database_title ?? "This database"} has no entries, so there are no sample values
            to show. Mapping works from the columns alone; you can check it again here after
            you&apos;ve logged a session.
          </p>
        </div>
      )}

      <section aria-labelledby="fields-title" className="mapping-section">
        <div className="mapping-section-head">
          <h2 id="fields-title">App fields</h2>
          {review.rows_sampled > 0 && (
            <span className="small muted">
              Samples from the latest {review.rows_sampled}{" "}
              {review.rows_sampled === 1 ? "entry" : "entries"}
            </span>
          )}
        </div>
        <ol className="mapping-fields">
          {review.fields.map((field) => (
            <FieldRow
              key={field.key}
              field={field}
              value={selections[field.key]}
              selections={selections}
              decided={decided.has(field.key)}
              columns={columns}
              users={users}
              labels={labels}
              renamedFrom={
                selections[field.key]
                  ? renamed.get(selections[field.key]?.property_id ?? "")
                  : undefined
              }
              rowsSampled={review.rows_sampled}
              onChange={(value) => {
                onChange(field.key, value);
              }}
            />
          ))}
        </ol>
      </section>

      <section aria-labelledby="extra-title" className="mapping-section">
        <div className="mapping-section-head">
          <h2 id="extra-title">Additional fields</h2>
        </div>
        <p className="muted">
          Tick any other column you want copied too. Ticked columns appear in the raw log, with
          filters that suit their type.
        </p>
        {unmapped.length === 0 ? (
          <p className="empty-note">Every column is already used by an app field.</p>
        ) : (
          <ul className="extra-list" aria-label="Additional fields">
            {unmapped.map((column) => (
              <ExtraRow
                key={column.id}
                column={column}
                checked={extra.has(column.id)}
                rowsSampled={review.rows_sampled}
                renamedFrom={renamed.get(column.id)}
                onToggle={(on) => {
                  onToggleExtra(column.id, on);
                }}
              />
            ))}
          </ul>
        )}
      </section>

      {reasons.length > 0 && (
        <div className="notice error" role="alert" aria-label="Before you can save">
          <strong>Before you can save</strong>
          <ul className="issue-list">
            {reasons.map((reason) => (
              <li key={reason.key}>
                <strong>{labels.get(reason.key)}:</strong> {reason.text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {saveProblem && (
        <ProblemNotice
          problem={saveProblem}
          onRetry={onRetry}
          onReconnect={onReconnect}
          onPasteNewToken={onPasteNewToken}
          onChooseDatabase={onChooseDatabase}
        />
      )}

      {review.saved && dirty && reasons.length === 0 && (
        <p className="small muted">
          Saving changes to a saved mapping means a full sync is needed, so entries already copied
          get the new columns.
        </p>
      )}

      <div className="actions">
        <button
          type="button"
          className="button primary"
          disabled={saving || reasons.length > 0}
          onClick={() => {
            onSave(selections, effectiveExtra);
          }}
        >
          {saving && <span className="spinner" aria-hidden="true" />}
          Save mapping
        </button>
        {onCancel && (
          <button type="button" className="button" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        )}
        <button type="button" className="link-button" onClick={onChooseDatabase}>
          Choose a different database
        </button>
      </div>
    </>
  );
}

function FieldRow({
  field,
  value,
  selections,
  decided,
  columns,
  users,
  labels,
  renamedFrom,
  rowsSampled,
  onChange,
}: {
  field: FieldReview;
  value: Selections[FieldKey];
  selections: Selections;
  decided: boolean;
  columns: Map<string, ColumnInfo>;
  users: Map<string, FieldKey>;
  labels: Map<FieldKey, string>;
  renamedFrom: string | undefined;
  rowsSampled: number;
  onChange: (value: string) => void;
}) {
  const id = `field-${field.key}`;
  const pending = field.status === "choose" && !decided;
  const selectValue = value
    ? encodeRef(value)
    : field.required || pending || field.status === "missing"
      ? UNCHOSEN
      : NOT_USED;
  const status = decided
    ? { text: value ? "Your choice" : "Not used", tone: "" as const }
    : STATUS_LABELS[field.status];
  const column = value ? columns.get(value.property_id) : undefined;
  const candidates = field.choose_from
    .map((pid) => columns.get(pid)?.name)
    .filter((name): name is string => Boolean(name));

  return (
    <li className="mapping-field" data-status={decided ? "decided" : field.status}>
      <div className="mapping-field-head">
        <label htmlFor={id} className="mapping-label">
          {field.label}
        </label>
        <span className={`badge${field.required ? " required" : ""}`}>
          {field.required ? "Required" : "Optional"}
        </span>
        <span className={`chip ${status.tone}`}>{status.text}</span>
      </div>
      <p className="small muted">{field.description}</p>

      <div className="mapping-field-body">
        <div className="mapping-choice">
          <select
            id={id}
            className="input select"
            value={selectValue}
            aria-describedby={`${id}-samples`}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          >
            {selectValue === UNCHOSEN && (
              <option value={UNCHOSEN} disabled>
                {pending ? "Please choose…" : `Choose a ${field.needs} column…`}
              </option>
            )}
            {!field.required && <option value={NOT_USED}>Not used</option>}
            {visibleOptions(field, selections).map((option) => {
              const user = users.get(option.property_id);
              const takenBy =
                option.part !== "end" && user && user !== field.key ? labels.get(user) : undefined;
              const typeLabel = columns.get(option.property_id)?.type_label;
              return (
                <option
                  key={`${option.part ?? ""}|${option.property_id}`}
                  value={encodeRef({
                    property_id: option.property_id,
                    ...(option.part ? { part: option.part } : {}),
                  })}
                  disabled={Boolean(takenBy)}
                >
                  {option.label}
                  {option.part !== "end" && typeLabel ? ` · ${typeLabel}` : ""}
                  {takenBy ? ` (used for ${takenBy})` : ""}
                </option>
              );
            })}
          </select>
          {pending && candidates.length > 1 && (
            <p className="small hint">
              {candidates.map((name) => `“${name}”`).join(" and ")} fit equally well, so Habit
              Tracker didn&apos;t guess. Pick the column that holds the {field.label.toLowerCase()}.
            </p>
          )}
          {renamedFrom && column && (
            <p className="small muted">
              Renamed in Notion from “{renamedFrom}”. The mapping still works.
            </p>
          )}
        </div>
        <FieldSamples
          id={`${id}-samples`}
          field={field}
          column={column}
          part={value?.part ?? null}
          rowsSampled={rowsSampled}
        />
      </div>

      {!decided && field.message && (
        <p className={`field-note ${field.required ? "error" : "warn"}`}>{field.message}</p>
      )}
      {field.required && !value && field.missing_help && (
        <div className="notice error" role="note">
          <strong>Your database is missing a column for {field.label.toLowerCase()}</strong>
          <p>{field.missing_help}</p>
        </div>
      )}
    </li>
  );
}

function FieldSamples({
  id,
  field,
  column,
  part,
  rowsSampled,
}: {
  id: string;
  field: FieldReview;
  column: ColumnInfo | undefined;
  part: DatePart | null;
  rowsSampled: number;
}) {
  if (!column) {
    return (
      <div id={id} className="samples empty-samples">
        <span className="small muted">No column chosen</span>
      </div>
    );
  }
  if (rowsSampled === 0) {
    return (
      <div id={id} className="samples empty-samples">
        <span className="small muted">No entries yet</span>
      </div>
    );
  }
  const formatted = column.samples
    .map((sample) => formatSample(sample, part))
    .filter((sample): sample is NonNullable<typeof sample> => sample !== null);
  const isDate = field.key === "start" || field.key === "end";
  return (
    <div id={id} className="samples" aria-label={`Sample values for ${field.label}`}>
      {formatted.length === 0 ? (
        <span className="small muted">
          {part === "end"
            ? `None of the latest ${rowsSampled} entries has an end date in “${column.name}”.`
            : `Empty in the latest ${rowsSampled} entries.`}
        </span>
      ) : (
        <ul className="sample-list">
          {formatted.map((sample, index) => (
            <li key={index} className={sample.noTime ? "sample warn" : "sample"}>
              <span className="figure">{sample.text}</span>
              {sample.noTime && isDate && <span className="sample-tag">no time</span>}
            </li>
          ))}
        </ul>
      )}
      {isDate && column.dates_without_time > 0 && (
        <p className="small warn-text">
          {column.dates_without_time} of the latest {rowsSampled} entries have a date without a
          time. Those entries will be flagged as Missing time.
        </p>
      )}
    </div>
  );
}

function ExtraRow({
  column,
  checked,
  rowsSampled,
  renamedFrom,
  onToggle,
}: {
  column: ColumnInfo;
  checked: boolean;
  rowsSampled: number;
  renamedFrom: string | undefined;
  onToggle: (on: boolean) => void;
}) {
  const samples = column.samples
    .map((sample) => formatSample(sample))
    .filter((sample): sample is NonNullable<typeof sample> => sample !== null);
  return (
    <li className={column.readable ? "extra-row" : "extra-row unusable"}>
      <label className="extra-label">
        <input
          type="checkbox"
          checked={column.readable && checked}
          disabled={!column.readable}
          onChange={(event) => {
            onToggle(event.target.checked);
          }}
        />
        <span className="extra-name">{column.name}</span>
        <span className="badge">{column.type_label}</span>
      </label>
      <div className="extra-detail">
        {column.readable ? (
          rowsSampled === 0 ? (
            <span className="small muted">No entries yet</span>
          ) : samples.length === 0 ? (
            <span className="small muted">Empty in the latest {rowsSampled} entries.</span>
          ) : (
            <ul className="sample-list">
              {samples.map((sample, index) => (
                <li key={index} className="sample">
                  <span className="figure">{sample.text}</span>
                </li>
              ))}
            </ul>
          )
        ) : (
          <p className="small field-note warn">Can&apos;t be used: {column.reason}</p>
        )}
        {column.readable && column.note && <p className="small muted">{column.note}</p>}
        {renamedFrom && <p className="small muted">Renamed in Notion from “{renamedFrom}”.</p>}
      </div>
    </li>
  );
}
