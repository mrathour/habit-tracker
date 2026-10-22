import {
  columnResizingFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  createColumnHelper,
  tableFeatures,
  useTable,
  type ColumnSizingState,
  type ColumnVisibilityState,
} from "@tanstack/react-table";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";

import type { RawLogColumn, RawLogPage, RawLogRow, SortSpec } from "../bridge/types";
import { cellProps, openInNotion, rowLabel } from "./cellData";
import { CellContent, IssueText, OpenIcon } from "./cells";
import { without } from "./filters";

/** Every row is one line high, so the table can draw only the rows in view. */
export const ROW_HEIGHT = 36;
const OVERSCAN = 8;
/** The viewport assumed before it has been measured (and in tests, where nothing is laid out). */
const FALLBACK_VIEWPORT = 640;
const RESIZE_STEP = 16;
export const OPEN_COLUMN = "open";

const DEFAULT_WIDTHS: Record<RawLogColumn["kind"], number> = {
  display_id: 76,
  task_name: 240,
  start: 176,
  end: 176,
  duration: 104,
  logged_minutes: 132,
  parent_task: 156,
  extra: 168,
  overlap: 116,
  issues: 112,
};

const features = tableFeatures({
  columnSizingFeature,
  columnResizingFeature,
  columnVisibilityFeature,
});
const helper = createColumnHelper<typeof features, RawLogRow>();
const NO_ROWS: RawLogRow[] = [];

function scrollIntoRow(container: HTMLElement | null, index: number) {
  if (!container) return;
  const header = container.querySelector("thead")?.getBoundingClientRect().height ?? ROW_HEIGHT;
  const top = index * ROW_HEIGHT;
  const viewport = container.clientHeight - header;
  if (top < container.scrollTop) container.scrollTop = top;
  else if (top + ROW_HEIGHT > container.scrollTop + viewport) {
    container.scrollTop = top + ROW_HEIGHT - viewport;
  }
}

/**
 * The raw log's table (PLAN.md 8). TanStack Table owns the column model (sizes, resizing and
 * visibility); rows come from Python a block at a time, and only the rows in view are drawn.
 *
 * A click selects a row; double-click, Enter or the row's button opens it in Notion.
 */
export function RawLogTable({
  page,
  rowAt,
  ensureRows,
  timeZone,
  sort,
  hidden,
  widths,
  onSort,
  onWidths,
  onFilterParent,
  rowsFailed,
  onRetry,
}: {
  page: RawLogPage;
  rowAt: (index: number) => RawLogRow | undefined;
  ensureRows: (first: number, last: number) => void;
  timeZone: string;
  sort: SortSpec;
  hidden: string[];
  widths: Record<string, number>;
  onSort: (column: string) => void;
  onWidths: (widths: Record<string, number>) => void;
  onFilterParent: (pageId: string) => void;
  rowsFailed: boolean;
  onRetry: () => void;
}) {
  const byKey = useMemo(
    () => new Map(page.columns.map((column) => [column.key, column])),
    [page.columns],
  );
  const columns = useMemo(
    () => [
      ...page.columns.map((column) =>
        helper.display({
          id: column.key,
          header: column.label,
          size: DEFAULT_WIDTHS[column.kind],
          minSize: 48,
          maxSize: 1200,
        }),
      ),
      helper.display({
        id: OPEN_COLUMN,
        header: "Open",
        size: 56,
        enableResizing: false,
        enableHiding: false,
      }),
    ],
    [page.columns],
  );
  const [sizing, setSizing] = useState<ColumnSizingState>(widths);
  const visibility = useMemo<ColumnVisibilityState>(
    () => Object.fromEntries(hidden.map((key) => [key, false])),
    [hidden],
  );
  const table = useTable({
    features,
    columns,
    data: NO_ROWS,
    state: { columnSizing: sizing, columnVisibility: visibility },
    onColumnSizingChange: setSizing,
    columnResizeMode: "onChange",
  });

  // Save the widths when a drag ends.
  const resizing = table.state.columnResizing.isResizingColumn;
  const wasResizing = useRef(resizing);
  useEffect(() => {
    if (wasResizing.current && !resizing) onWidths(sizing);
    wasResizing.current = resizing;
  }, [resizing, sizing, onWidths]);

  const resizeBy = (id: string, delta: number) => {
    const column = table.getColumn(id);
    if (!column) return;
    const next = {
      ...sizing,
      [id]: Math.min(1200, Math.max(48, column.getSize() + delta)),
    };
    setSizing(next);
    onWidths(next);
  };

  const resetSize = (id: string) => {
    const next = without(sizing, id);
    setSizing(next);
    onWidths(next);
  };

  // --- which rows are in view ---
  const container = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(FALLBACK_VIEWPORT);
  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return undefined;
    const measure = () => {
      setViewport(element.clientHeight || FALLBACK_VIEWPORT);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);
  const count = page.matched;
  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(count - 1, Math.ceil((scrollTop + viewport) / ROW_HEIGHT) + OVERSCAN);
  useEffect(() => {
    if (count > 0) ensureRows(first, last);
  }, [ensureRows, first, last, count]);

  // A new query starts at the top (the scroll event then updates scrollTop).
  const queryKey = `${String(page.matched)}|${JSON.stringify(page.sort)}`;
  useEffect(() => {
    if (container.current) container.current.scrollTop = 0;
  }, [queryKey]);

  // --- selection ---
  const [selected, setSelected] = useState<string | null>(null);
  const selectedIndex = useMemo(() => {
    if (selected === null) return -1;
    for (let index = first; index <= last; index += 1) {
      if (rowAt(index)?.page_id === selected) return index;
    }
    return -1;
  }, [selected, first, last, rowAt]);
  const [cursor, setCursor] = useState(-1);
  const active = selectedIndex >= 0 ? selectedIndex : cursor;

  const select = useCallback(
    (index: number) => {
      const bounded = Math.max(0, Math.min(count - 1, index));
      setCursor(bounded);
      setSelected(rowAt(bounded)?.page_id ?? null);
      scrollIntoRow(container.current, bounded);
    },
    [count, rowAt],
  );

  const onKeyDown = (event: KeyboardEvent<HTMLTableElement>) => {
    if (count === 0) return;
    const pageRows = Math.max(1, Math.floor(viewport / ROW_HEIGHT) - 1);
    const moves: Record<string, number> = {
      ArrowDown: active + 1,
      ArrowUp: Math.max(0, active - 1),
      PageDown: active + pageRows,
      PageUp: Math.max(0, active - pageRows),
      Home: 0,
      End: count - 1,
    };
    const target = moves[event.key];
    if (target !== undefined) {
      event.preventDefault();
      select(active < 0 && event.key === "ArrowDown" ? 0 : target);
      return;
    }
    if (event.key === "Enter" && active >= 0) {
      const row = rowAt(active);
      if (row) {
        event.preventDefault();
        openInNotion(row.url);
      }
    }
  };

  const fromControl = (event: MouseEvent) =>
    (event.target as HTMLElement).closest("button, a, input, select, [role='separator']") !== null;

  const visibleColumns = table.getVisibleLeafColumns();
  const rows: { index: number; row: RawLogRow | undefined }[] = [];
  for (let index = first; index <= last; index += 1) rows.push({ index, row: rowAt(index) });
  const sortColumn = byKey.get(sort.column) ? sort.column : "start";

  return (
    <div
      ref={container}
      className="rawlog-scroll"
      onScroll={(event) => {
        setScrollTop(event.currentTarget.scrollTop);
      }}
    >
      <table
        className="rawlog-table"
        role="grid"
        aria-label="Raw log"
        aria-rowcount={count + 1}
        aria-multiselectable="false"
        tabIndex={0}
        aria-activedescendant={active >= 0 ? `rawlog-row-${String(active)}` : undefined}
        onKeyDown={onKeyDown}
        style={{ width: table.getTotalSize() }}
      >
        <colgroup>
          {visibleColumns.map((column) => (
            <col key={column.id} style={{ width: column.getSize() }} />
          ))}
        </colgroup>
        <thead>
          <tr aria-rowindex={1}>
            {table.getHeaderGroups()[0]?.headers.map((header) => {
              const info = byKey.get(header.column.id);
              if (!info) {
                return (
                  <th key={header.id} scope="col">
                    <span className="visually-hidden">Open in Notion</span>
                  </th>
                );
              }
              const sorted = sortColumn === info.key ? sort.direction : null;
              return (
                <th
                  key={header.id}
                  scope="col"
                  aria-sort={
                    sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                  }
                >
                  <button
                    type="button"
                    className="sort-button"
                    title={info.type_label ? `${info.label} (${info.type_label})` : info.label}
                    onClick={() => {
                      onSort(info.key);
                    }}
                  >
                    <span className="sort-label">{info.label}</span>
                    <span className="sort-mark" aria-hidden="true">
                      {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : ""}
                    </span>
                  </button>
                  <div
                    role="separator"
                    aria-orientation="vertical"
                    aria-label={`Resize ${info.label}`}
                    aria-valuenow={header.column.getSize()}
                    aria-valuemin={48}
                    aria-valuemax={1200}
                    tabIndex={0}
                    className={`col-resizer${header.column.getIsResizing() ? " resizing" : ""}`}
                    onMouseDown={header.getResizeHandler()}
                    onTouchStart={header.getResizeHandler()}
                    onDoubleClick={() => {
                      resetSize(info.key);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                        event.preventDefault();
                        event.stopPropagation();
                        resizeBy(info.key, event.key === "ArrowLeft" ? -RESIZE_STEP : RESIZE_STEP);
                      }
                    }}
                  />
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {first > 0 && (
            <tr className="spacer" aria-hidden="true">
              <td colSpan={visibleColumns.length} style={{ height: first * ROW_HEIGHT }} />
            </tr>
          )}
          {rows.map(({ index, row }) =>
            row ? (
              <tr
                key={row.page_id}
                id={`rawlog-row-${String(index)}`}
                aria-rowindex={index + 2}
                aria-selected={index === active}
                className={index === active ? "selected" : undefined}
                onClick={() => {
                  setCursor(index);
                  setSelected(row.page_id);
                }}
                onDoubleClick={(event) => {
                  if (!fromControl(event)) openInNotion(row.url);
                }}
              >
                {visibleColumns.map((column) => {
                  const info = byKey.get(column.id);
                  if (!info) {
                    return (
                      <td key={column.id} className="open-cell">
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`Open ${rowLabel(row)} in Notion`}
                          title="Open in Notion"
                          onClick={() => {
                            openInNotion(row.url);
                          }}
                        >
                          <OpenIcon />
                        </button>
                      </td>
                    );
                  }
                  const props = cellProps(row, info, timeZone);
                  return (
                    <td key={column.id} {...props} data-kind={info.kind}>
                      <CellContent
                        row={row}
                        column={info}
                        timeZone={timeZone}
                        onFilterParent={onFilterParent}
                      />
                      <IssueText row={row} column={info} />
                    </td>
                  );
                })}
              </tr>
            ) : (
              <tr
                key={`loading-${String(index)}`}
                className="placeholder"
                aria-rowindex={index + 2}
              >
                <td colSpan={visibleColumns.length}>
                  {rowsFailed ? (
                    <span className="small">
                      These entries couldn&apos;t be loaded.{" "}
                      <button type="button" className="link-button" onClick={onRetry}>
                        Try again
                      </button>
                    </span>
                  ) : (
                    <span className="skeleton-line" aria-label="Loading" />
                  )}
                </td>
              </tr>
            ),
          )}
          {last < count - 1 && (
            <tr className="spacer" aria-hidden="true">
              <td
                colSpan={visibleColumns.length}
                style={{ height: (count - 1 - last) * ROW_HEIGHT }}
              />
            </tr>
          )}
        </tbody>
      </table>
      <CellTooltip root={container} />
    </div>
  );
}

/**
 * Shows a cell's explanation (`data-tip`) while the pointer is over it, or while a control inside
 * it has keyboard focus. Placed with fixed coordinates so the scrolling table never clips it.
 */
function CellTooltip({ root }: { root: React.RefObject<HTMLDivElement | null> }) {
  const [tip, setTip] = useState<{ text: string; top: number; left: number } | null>(null);
  useEffect(() => {
    const element = root.current;
    if (!element) return undefined;
    const show = (event: Event) => {
      const target = (event.target as HTMLElement).closest<HTMLElement>("[data-tip]");
      if (!target || !element.contains(target)) {
        setTip(null);
        return;
      }
      const box = target.getBoundingClientRect();
      setTip({
        text: target.dataset["tip"] ?? "",
        top: box.bottom + 6,
        left: Math.max(8, Math.min(box.left, window.innerWidth - 328)),
      });
    };
    const hide = () => {
      setTip(null);
    };
    element.addEventListener("mouseover", show);
    element.addEventListener("focusin", show);
    element.addEventListener("mouseleave", hide);
    element.addEventListener("focusout", hide);
    element.addEventListener("scroll", hide);
    return () => {
      element.removeEventListener("mouseover", show);
      element.removeEventListener("focusin", show);
      element.removeEventListener("mouseleave", hide);
      element.removeEventListener("focusout", hide);
      element.removeEventListener("scroll", hide);
    };
  }, [root]);
  if (!tip) return null;
  return (
    <div className="cell-tooltip" role="tooltip" style={{ top: tip.top, left: tip.left }}>
      {tip.text}
    </div>
  );
}
