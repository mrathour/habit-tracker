import { useState } from "react";

import type { RawLogColumn } from "../bridge/types";
import { Popover } from "./Popover";

/**
 * Show or hide columns (PLAN.md 8). The last visible column can't be hidden, and "Show all"
 * brings every column back. The choice is remembered across launches.
 */
export function ColumnPicker({
  columns,
  hidden,
  onChange,
}: {
  columns: RawLogColumn[];
  hidden: string[];
  onChange: (hidden: string[]) => void;
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const hiddenSet = new Set(hidden);
  const visible = columns.filter((column) => !hiddenSet.has(column.key));
  const hiddenHere = columns.length - visible.length;

  return (
    <>
      <button
        type="button"
        className="button small"
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
        onClick={(event) => {
          const target = event.currentTarget;
          setAnchor((current) => (current ? null : target));
        }}
      >
        Columns{hiddenHere > 0 ? ` (${String(hiddenHere)} hidden)` : ""}
      </button>
      {anchor && (
        <Popover
          anchor={anchor}
          label="Show or hide columns"
          className="column-picker"
          onClose={() => {
            setAnchor(null);
          }}
        >
          <fieldset className="choices-plain">
            <legend className="filter-label">Columns</legend>
            {columns.map((column) => {
              const shown = !hiddenSet.has(column.key);
              const last = shown && visible.length === 1;
              return (
                <label key={column.key} className="filter-toggle">
                  <input
                    type="checkbox"
                    checked={shown}
                    disabled={last}
                    onChange={(event) => {
                      const next = new Set(hidden);
                      if (event.target.checked) next.delete(column.key);
                      else next.add(column.key);
                      onChange([...next]);
                    }}
                  />
                  {column.label}
                  {column.type_label && <span className="muted small"> · {column.type_label}</span>}
                  {last && <span className="visually-hidden"> (at least one column stays)</span>}
                </label>
              );
            })}
          </fieldset>
          <button
            type="button"
            className="link-button small"
            disabled={hiddenHere === 0}
            onClick={() => {
              // Hidden keys for columns this mapping doesn't have stay, for when they return.
              const keys = new Set(columns.map((column) => column.key));
              onChange(hidden.filter((key) => !keys.has(key)));
            }}
          >
            Show all
          </button>
        </Popover>
      )}
    </>
  );
}
