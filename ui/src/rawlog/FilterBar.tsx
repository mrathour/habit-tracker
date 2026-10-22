import { useEffect, useId, useRef, useState } from "react";

import type {
  ExtraFilter,
  IssueCode,
  ParentChoice,
  RawLogColumn,
  RawLogFilters,
} from "../bridge/types";
import {
  activeChips,
  ISSUE_CODES,
  ISSUE_LABELS,
  parentLabel,
  removeChip,
  without,
  type FilterProblems,
} from "./filters";

/** How long typing in a search box waits before the table updates. */
export const SEARCH_DELAY_MS = 250;

function numberOrNull(text: string): number | null {
  if (text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** A text input that reports its value after typing pauses. */
function SearchInput({
  value,
  onChange,
  label,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(value);
  const [shown, setShown] = useState(value);
  const report = useRef(onChange);
  useEffect(() => {
    report.current = onChange;
  }, [onChange]);
  // A change from outside (a chip removed, "Clear all") replaces what is typed.
  if (value !== shown) {
    setShown(value);
    setDraft(value);
  }
  useEffect(() => {
    if (draft === value) return undefined;
    const timer = window.setTimeout(() => {
      report.current(draft);
    }, SEARCH_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [draft, value]);
  return (
    <input
      type="search"
      className="input"
      aria-label={label}
      placeholder={placeholder}
      value={draft}
      onChange={(event) => {
        setDraft(event.target.value);
      }}
    />
  );
}

/**
 * The raw log's filters (PLAN.md 8). The common ones are always visible; the rest, including one
 * per extra field, open under "More filters". Every active filter shows as a removable chip.
 */
export function FilterBar({
  filters,
  onChange,
  columns,
  parents,
  problems,
}: {
  filters: RawLogFilters;
  onChange: (filters: RawLogFilters) => void;
  columns: RawLogColumn[];
  parents: ParentChoice[];
  problems: FilterProblems;
}) {
  const [more, setMore] = useState(false);
  const panelId = useId();
  const chips = activeChips(filters, columns, parents);
  const set = (changes: Partial<RawLogFilters>) => {
    onChange({ ...filters, ...changes });
  };
  const hasParent = columns.some((c) => c.kind === "parent_task");
  const extras = columns.filter((c) => c.kind === "extra" && c.filter);

  return (
    <div className="filter-bar">
      <div className="filter-row">
        <label className="filter-field grow">
          <span className="filter-label">Task name</span>
          <SearchInput
            label="Search task names"
            placeholder="Search task names"
            value={filters.search ?? ""}
            onChange={(search) => {
              set({ search });
            }}
          />
        </label>
        <fieldset className="filter-field">
          <legend className="filter-label">Started</legend>
          <span className="input-pair">
            <input
              type="date"
              className="input"
              aria-label="Started on or after"
              value={filters.date_from ?? ""}
              onChange={(event) => {
                set({ date_from: event.target.value || null });
              }}
            />
            <span aria-hidden="true">–</span>
            <input
              type="date"
              className="input"
              aria-label="Started on or before"
              value={filters.date_to ?? ""}
              onChange={(event) => {
                set({ date_to: event.target.value || null });
              }}
            />
          </span>
          {problems["date"] && <span className="field-error">{problems["date"]}</span>}
        </fieldset>
        <label className="filter-field">
          <span className="filter-label">Issues</span>
          <select
            className="input select"
            value={filters.issues ?? ""}
            onChange={(event) => {
              const value = event.target.value;
              set({ issues: value === "any" || value === "none" ? value : null });
            }}
          >
            <option value="">All entries</option>
            <option value="any">Has issues</option>
            <option value="none">No issues</option>
          </select>
        </label>
        <label className="filter-toggle">
          <input
            type="checkbox"
            checked={filters.overlaps ?? false}
            onChange={(event) => {
              set({ overlaps: event.target.checked });
            }}
          />
          Overlaps another session
        </label>
        <button
          type="button"
          className="button small"
          aria-expanded={more}
          aria-controls={panelId}
          onClick={() => {
            setMore(!more);
          }}
        >
          {more ? "Fewer filters" : "More filters"}
        </button>
      </div>
      {more && (
        <div className="filter-panel" id={panelId}>
          {hasParent && <ParentFilter filters={filters} parents={parents} onChange={set} />}
          <fieldset className="filter-field">
            <legend className="filter-label">Duration (minutes)</legend>
            <span className="input-pair">
              <input
                type="number"
                min={0}
                className="input"
                aria-label="Shortest duration in minutes"
                placeholder="Min"
                value={filters.duration_min ?? ""}
                onChange={(event) => {
                  set({ duration_min: numberOrNull(event.target.value) });
                }}
              />
              <span aria-hidden="true">–</span>
              <input
                type="number"
                min={0}
                className="input"
                aria-label="Longest duration in minutes"
                placeholder="Max"
                value={filters.duration_max ?? ""}
                onChange={(event) => {
                  set({ duration_max: numberOrNull(event.target.value) });
                }}
              />
            </span>
            <span className="hint">Entries without a valid start and end are left out.</span>
            {problems["duration"] && <span className="field-error">{problems["duration"]}</span>}
          </fieldset>
          <fieldset className="filter-field">
            <legend className="filter-label">Issue type</legend>
            {ISSUE_CODES.map((code) => (
              <label key={code} className="filter-toggle">
                <input
                  type="checkbox"
                  checked={filters.issue_codes?.includes(code) ?? false}
                  onChange={(event) => {
                    const current = filters.issue_codes ?? [];
                    const next: IssueCode[] = event.target.checked
                      ? [...current, code]
                      : current.filter((c) => c !== code);
                    set({ issue_codes: next });
                  }}
                />
                {ISSUE_LABELS[code]}
              </label>
            ))}
          </fieldset>
          {extras.map((column) => (
            <ExtraFilterField
              key={column.key}
              column={column}
              value={filters.extra?.[column.key.slice("extra:".length)]}
              problem={problems[column.key]}
              onChange={(spec) => {
                const id = column.key.slice("extra:".length);
                const rest = without(filters.extra ?? {}, id);
                set({ extra: spec ? { ...rest, [id]: spec } : rest });
              }}
            />
          ))}
        </div>
      )}
      {chips.length > 0 && (
        <ul className="filter-chips" aria-label="Active filters">
          {chips.map((chip) => (
            <li key={chip.id}>
              <span>{chip.label}</span>
              <button
                type="button"
                className="chip-remove"
                aria-label={`Remove filter: ${chip.label}`}
                onClick={() => {
                  onChange(removeChip(filters, chip.id));
                }}
              >
                ×
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="link-button small"
              onClick={() => {
                onChange({});
              }}
            >
              Clear all
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}

function ParentFilter({
  filters,
  parents,
  onChange,
}: {
  filters: RawLogFilters;
  parents: ParentChoice[];
  onChange: (changes: Partial<RawLogFilters>) => void;
}) {
  const chosen = new Set(filters.parents ?? []);
  return (
    <fieldset className="filter-field parent-filter">
      <legend className="filter-label">Parent task</legend>
      <span className="hint">
        Linked pages are listed by ID and their newest entry&apos;s name, because Habit Tracker
        doesn&apos;t read the Task Tracker. An entry matches when any of its links does.
      </span>
      <label className="filter-toggle">
        <input
          type="checkbox"
          checked={filters.no_parent ?? false}
          onChange={(event) => {
            onChange({ no_parent: event.target.checked, parents: [] });
          }}
        />
        No parent task
      </label>
      {parents.length === 0 ? (
        <span className="muted small">No entry links a parent task yet.</span>
      ) : (
        <div className="parent-list">
          {parents.map((parent) => (
            <label key={parent.page_id} className="filter-toggle">
              <input
                type="checkbox"
                checked={chosen.has(parent.page_id)}
                disabled={filters.no_parent ?? false}
                onChange={(event) => {
                  const next = new Set(chosen);
                  if (event.target.checked) next.add(parent.page_id);
                  else next.delete(parent.page_id);
                  onChange({ parents: [...next] });
                }}
              />
              <span className="parent-name">{parentLabel(parent)}</span>
              <span className="muted small">
                {parent.entries.toLocaleString()} {parent.entries === 1 ? "entry" : "entries"}
              </span>
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

type Mode = "any" | "match" | "empty" | "not_empty";

function modeOf(spec: ExtraFilter | undefined): Mode {
  if (!spec) return "any";
  if (spec.op === "empty" || spec.op === "not_empty") return spec.op;
  return "match";
}

const MATCH_LABELS: Record<NonNullable<RawLogColumn["filter"]>, string | null> = {
  text: "Contains",
  number: "Between",
  checkbox: null,
  options: "Is any of",
  date: "Between",
  presence: null,
};

function emptySpec(kind: NonNullable<RawLogColumn["filter"]>): ExtraFilter | null {
  switch (kind) {
    case "text":
      return { op: "contains", value: "" };
    case "number":
      return { op: "range", min: null, max: null };
    case "options":
      return { op: "any_of", values: [] };
    case "date":
      return { op: "dates", from: null, to: null };
    default:
      return null;
  }
}

/** One extra field's filter, shaped by its type (PLAN.md 8). */
function ExtraFilterField({
  column,
  value,
  problem,
  onChange,
}: {
  column: RawLogColumn;
  value: ExtraFilter | undefined;
  problem: string | undefined;
  onChange: (spec: ExtraFilter | null) => void;
}) {
  const kind = column.filter ?? "presence";
  const mode = modeOf(value);
  const name = column.label;
  const matchLabel = MATCH_LABELS[kind];

  const modeSelect =
    kind === "checkbox" ? (
      <select
        className="input select"
        aria-label={`${name} filter`}
        value={value?.op === "is" ? (value.value ? "yes" : "no") : mode}
        onChange={(event) => {
          const choice = event.target.value;
          if (choice === "yes" || choice === "no") onChange({ op: "is", value: choice === "yes" });
          else onChange(choice === "any" ? null : ({ op: choice } as ExtraFilter));
        }}
      >
        <option value="any">Any</option>
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </select>
    ) : (
      <select
        className="input select"
        aria-label={`${name} filter`}
        value={mode}
        onChange={(event) => {
          const choice = event.target.value as Mode;
          if (choice === "any") onChange(null);
          else if (choice === "match") onChange(emptySpec(kind));
          else onChange({ op: choice });
        }}
      >
        <option value="any">Any</option>
        {matchLabel && <option value="match">{matchLabel}</option>}
        <option value="empty">Is empty</option>
        <option value="not_empty">Has a value</option>
      </select>
    );

  return (
    <fieldset className="filter-field extra-filter">
      <legend className="filter-label">
        {name}
        {column.type_label && <span className="muted small"> · {column.type_label}</span>}
      </legend>
      <span className="input-pair">
        {modeSelect}
        {value?.op === "contains" && (
          <SearchInput
            label={`${name} contains`}
            value={value.value}
            onChange={(text) => {
              onChange({ op: "contains", value: text });
            }}
          />
        )}
        {value?.op === "range" && (
          <>
            <input
              type="number"
              className="input"
              aria-label={`${name}: lowest`}
              placeholder="Min"
              value={value.min ?? ""}
              onChange={(event) => {
                onChange({ ...value, min: numberOrNull(event.target.value) });
              }}
            />
            <input
              type="number"
              className="input"
              aria-label={`${name}: highest`}
              placeholder="Max"
              value={value.max ?? ""}
              onChange={(event) => {
                onChange({ ...value, max: numberOrNull(event.target.value) });
              }}
            />
          </>
        )}
        {value?.op === "dates" && (
          <>
            <input
              type="date"
              className="input"
              aria-label={`${name}: from`}
              value={value.from ?? ""}
              onChange={(event) => {
                onChange({ ...value, from: event.target.value || null });
              }}
            />
            <input
              type="date"
              className="input"
              aria-label={`${name}: to`}
              value={value.to ?? ""}
              onChange={(event) => {
                onChange({ ...value, to: event.target.value || null });
              }}
            />
          </>
        )}
      </span>
      {value?.op === "any_of" && (
        <div className="option-list">
          {column.options.length === 0 ? (
            <span className="muted small">No entry has a value here yet.</span>
          ) : (
            column.options.map((option) => (
              <label key={option} className="filter-toggle">
                <input
                  type="checkbox"
                  checked={value.values.includes(option)}
                  onChange={(event) => {
                    const values = event.target.checked
                      ? [...value.values, option]
                      : value.values.filter((v) => v !== option);
                    onChange({ op: "any_of", values });
                  }}
                />
                {option}
              </label>
            ))
          )}
        </div>
      )}
      {kind === "presence" && (
        <span className="hint">
          Names and titles aren&apos;t read from Notion, so this filters on whether it&apos;s set.
        </span>
      )}
      {problem && <span className="field-error">{problem}</span>}
    </fieldset>
  );
}
