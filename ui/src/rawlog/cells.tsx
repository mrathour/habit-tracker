import { useState } from "react";

import type { RawLogColumn, RawLogRow } from "../bridge/types";
import { cellIssues, cellText, openInNotion, rowLabel } from "./cellData";
import { formatMinutes, plural } from "./format";
import { Popover } from "./Popover";

const EMPTY = (
  <span className="muted" aria-label="Empty">
    —
  </span>
);

/** One table cell's contents. Red cells carry their explanation for hover and screen readers. */
export function CellContent({
  row,
  column,
  timeZone,
  onFilterParent,
}: {
  row: RawLogRow;
  column: RawLogColumn;
  timeZone: string;
  onFilterParent: (pageId: string) => void;
}) {
  if (column.kind === "parent_task") {
    return (
      <LinkList
        urls={row.parent_urls}
        ids={row.parent_task_ids}
        firstLabel="Parent task"
        listLabel={`Pages linked to ${rowLabel(row)}`}
        onFilter={onFilterParent}
      />
    );
  }
  if (column.kind === "overlap") return <OverlapMarker row={row} />;
  if (column.kind === "issues") return <IssueSummary row={row} />;
  if (column.kind === "extra") {
    const cell = row.extras[column.key.slice("extra:".length)];
    if (cell?.links) {
      return (
        <LinkList
          urls={cell.links}
          ids={null}
          firstLabel="Linked page 1"
          listLabel={`${column.label} for ${rowLabel(row)}`}
          onFilter={null}
        />
      );
    }
  }
  const text = cellText(row, column, timeZone);
  if (column.kind === "task_name" && !text) return <span className="muted">Untitled</span>;
  return text === null ? EMPTY : <span className="cell-text">{text}</span>;
}

/** Screen-reader text for a red cell's explanation. */
export function IssueText({ row, column }: { row: RawLogRow; column: RawLogColumn }) {
  const issues = cellIssues(row, column);
  if (issues.length === 0) return null;
  return (
    <span className="visually-hidden">
      {` Issue: ${issues.map((issue) => issue.message).join(" ")}`}
    </span>
  );
}

function LinkList({
  urls,
  ids,
  firstLabel,
  listLabel,
  onFilter,
}: {
  urls: string[];
  ids: string[] | null;
  firstLabel: string;
  listLabel: string;
  onFilter: ((pageId: string) => void) | null;
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const first = urls[0];
  if (!first) return EMPTY;
  const more = urls.length - 1;
  return (
    <span className="link-cell">
      <button
        type="button"
        className="link-button"
        onClick={() => {
          openInNotion(first);
        }}
      >
        {firstLabel}
      </button>
      {(more > 0 || (onFilter && ids)) && (
        <button
          type="button"
          className="more-chip"
          aria-haspopup="dialog"
          aria-expanded={anchor !== null}
          aria-label={more > 0 ? `${String(more)} more linked pages` : "Linked page options"}
          onClick={(event) => {
            const target = event.currentTarget;
            setAnchor((current) => (current ? null : target));
          }}
        >
          {more > 0 ? `+${String(more)}` : "⋯"}
        </button>
      )}
      {anchor && (
        <Popover
          anchor={anchor}
          label={listLabel}
          onClose={() => {
            setAnchor(null);
          }}
        >
          <ul className="popover-list">
            {urls.map((url, index) => (
              <li key={url}>
                <span>{index === 0 ? firstLabel : `Linked page ${String(index + 1)}`}</span>
                <button
                  type="button"
                  className="link-button small"
                  onClick={() => {
                    openInNotion(url);
                  }}
                >
                  Open in Notion
                </button>
                {onFilter && ids?.[index] && (
                  <button
                    type="button"
                    className="link-button small"
                    onClick={() => {
                      onFilter(ids[index] ?? "");
                      setAnchor(null);
                    }}
                  >
                    Show its entries
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Popover>
      )}
    </span>
  );
}

function OverlapMarker({ row }: { row: RawLogRow }) {
  if (row.overlap_minutes <= 0) return EMPTY;
  const others = row.overlaps_with.map((other) => other.label).join(", ");
  const text = `Overlaps ${others} by ${formatMinutes(row.overlap_minutes)}.`;
  return (
    <span className="overlap-marker" data-tip={text}>
      <svg viewBox="0 0 16 16" aria-hidden="true" width="14" height="14">
        <rect x="1.5" y="3.5" width="8" height="6" rx="1.5" />
        <rect x="6.5" y="6.5" width="8" height="6" rx="1.5" />
      </svg>
      <span className="figure">{formatMinutes(row.overlap_minutes)}</span>
      <span className="visually-hidden"> {text}</span>
    </span>
  );
}

function IssueSummary({ row }: { row: RawLogRow }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  if (row.issues.length === 0) return EMPTY;
  return (
    <>
      <button
        type="button"
        className="issue-chip"
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
        onClick={(event) => {
          const target = event.currentTarget;
          setAnchor((current) => (current ? null : target));
        }}
      >
        {plural(row.issues.length, "issue")}
      </button>
      {anchor && (
        <Popover
          anchor={anchor}
          label={`Issues with ${rowLabel(row)}`}
          onClose={() => {
            setAnchor(null);
          }}
        >
          <ul className="popover-list issue-list">
            {row.issues.map((issue, index) => (
              <li key={index} className="issue">
                {issue.message}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="link-button small"
            onClick={() => {
              openInNotion(row.url);
            }}
          >
            Fix it in Notion
          </button>
        </Popover>
      )}
    </>
  );
}

export function OpenIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" width="14" height="14">
      <path d="M6 3H3.5A1.5 1.5 0 0 0 2 4.5v8A1.5 1.5 0 0 0 3.5 14h8a1.5 1.5 0 0 0 1.5-1.5V10" />
      <path d="M9 2h5v5M14 2 7.5 8.5" />
    </svg>
  );
}
