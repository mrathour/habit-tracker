import { useCallback, useMemo, useState } from "react";

import { callPython } from "../bridge/client";
import type { RawLogFilters, RawLogViewPrefs, SortSpec, SyncStatus } from "../bridge/types";
import { noticeFromCallError } from "../errors/reporting";
import { ColumnPicker } from "./ColumnPicker";
import { ExportControl } from "./ExportControl";
import { FilterBar } from "./FilterBar";
import { hasFilters, requestFilters } from "./filters";
import { plural } from "./format";
import { RawLogTable } from "./RawLogTable";
import { useRawLog } from "./useRawLog";

/** Columns sorted newest or longest first when first chosen; text sorts A to Z. */
const DESCENDING_FIRST = new Set(["start", "end", "duration", "overlap", "issues"]);

function saveView(changes: Partial<RawLogViewPrefs>) {
  callPython("set_raw_log_view", changes).catch((error: unknown) => {
    noticeFromCallError(error, "Your column settings couldn't be saved");
  });
}

/**
 * The raw log (PLAN.md 8): every entry in a table with filters, red issue cells with their
 * explanations, overlap markers and Notion links. Filters live in the app (they reset on each
 * launch); the sort, column widths and hidden columns are remembered.
 */
export function RawLogView({
  filters,
  onFiltersChange,
  sync,
}: {
  filters: RawLogFilters;
  onFiltersChange: (filters: RawLogFilters) => void;
  sync: SyncStatus | null;
}) {
  // A finished sync (or a new result) refreshes the rows.
  const refreshKey = `${sync?.last_result?.finished_at ?? ""}|${String(sync?.entries ?? 0)}`;
  const { filters: sent, problems } = useMemo(() => requestFilters(filters), [filters]);
  const [sort, setSort] = useState<SortSpec | null>(null);
  const [hidden, setHidden] = useState<string[] | null>(null);
  const data = useRawLog(sent, sort, refreshKey);
  const page = data.load.status === "ready" ? data.load.page : null;
  const shownSort = useMemo<SortSpec>(
    () => sort ?? page?.sort ?? { column: "start", direction: "desc" },
    [sort, page],
  );
  const shownHidden = useMemo(() => hidden ?? page?.view.hidden ?? [], [hidden, page]);

  const onSort = useCallback(
    (column: string) => {
      const next: SortSpec =
        shownSort.column === column
          ? { column, direction: shownSort.direction === "asc" ? "desc" : "asc" }
          : { column, direction: DESCENDING_FIRST.has(column) ? "desc" : "asc" };
      setSort(next);
      saveView({ sort: next });
    },
    [shownSort],
  );

  const onHidden = useCallback((next: string[]) => {
    setHidden(next);
    saveView({ hidden: next });
  }, []);

  const onWidths = useCallback((widths: Record<string, number>) => {
    saveView({ widths });
  }, []);

  const onFilterParent = useCallback(
    (pageId: string) => {
      onFiltersChange({ ...filters, no_parent: false, parents: [pageId] });
    },
    [filters, onFiltersChange],
  );

  const exportColumns = useMemo(() => {
    const hiddenSet = new Set(shownHidden);
    return (page?.columns ?? []).map((c) => c.key).filter((key) => !hiddenSet.has(key));
  }, [page, shownHidden]);

  const filtered = hasFilters(filters);
  const clear = () => {
    onFiltersChange({});
  };

  return (
    <section className="rawlog" aria-labelledby="rawlog-title">
      <div className="rawlog-head">
        <h1 id="rawlog-title" className="section-title">
          Raw log
        </h1>
        <p className="small muted" role="status" aria-live="polite">
          {page
            ? page.total_entries === 0
              ? "No entries yet"
              : filtered
                ? `Showing ${page.matched.toLocaleString()} of ${plural(page.total_entries, "entry", "entries")}`
                : plural(page.total_entries, "entry", "entries")
            : ""}
          {data.load.status === "ready" && data.load.refreshing && " · Updating…"}
          {sync?.running && " · Sync in progress"}
        </p>
        {page && page.total_entries > 0 && (
          <div className="rawlog-actions">
            <ColumnPicker columns={page.columns} hidden={shownHidden} onChange={onHidden} />
            <ExportControl
              request={data.exportRequest}
              columns={exportColumns}
              matched={data.load.status === "ready" && !data.load.refreshing ? page.matched : 0}
            />
          </div>
        )}
      </div>

      {page && page.total_entries > 0 && (
        <FilterBar
          filters={filters}
          onChange={onFiltersChange}
          columns={page.columns}
          parents={page.parents}
          problems={problems}
        />
      )}

      {data.load.status === "loading" && (
        <div className="rawlog-skeleton" aria-busy="true" aria-label="Loading the raw log">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton skeleton-row" />
          ))}
        </div>
      )}

      {data.load.status === "error" && (
        <div className={`notice ${data.load.problem.tone}`} role="alert">
          <strong>The raw log couldn&apos;t be loaded</strong>
          <p>{data.load.problem.message}</p>
          {data.load.problem.errorId && (
            <p className="small muted">Error ID {data.load.problem.errorId}</p>
          )}
          <div className="actions">
            <button type="button" className="button" onClick={data.retry}>
              Try again
            </button>
            {filtered && (
              <button type="button" className="button" onClick={clear}>
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}

      {page?.total_entries === 0 && (
        <div className="empty">
          <h2>No entries yet</h2>
          <p>
            {sync?.running
              ? "Your entries are being copied now. They appear here when the sync finishes."
              : "Once your work log's entries are copied to this computer, every one of them shows here, with any issues marked."}
          </p>
        </div>
      )}

      {page && page.total_entries > 0 && page.matched === 0 && (
        <div className="empty">
          <h2>No entries match these filters</h2>
          <p>Change or remove a filter to see more entries.</p>
          <div className="actions">
            <button type="button" className="button" onClick={clear}>
              Clear filters
            </button>
          </div>
        </div>
      )}

      {page && page.matched > 0 && (
        <div aria-busy={data.load.status === "ready" && data.load.refreshing}>
          <RawLogTable
            key={page.columns.map((c) => c.key).join("|")}
            page={page}
            rowAt={data.rowAt}
            ensureRows={data.ensureRows}
            timeZone={page.time_zone}
            sort={shownSort}
            hidden={shownHidden}
            widths={page.view.widths}
            onSort={onSort}
            onWidths={onWidths}
            onFilterParent={onFilterParent}
            rowsFailed={data.rowsFailed}
            onRetry={data.retry}
          />
          <p className="small muted rawlog-help">
            Click a row to select it; double-click it or press Enter to open it in Notion. Red cells
            have an issue: point at one to see why. Times are in {page.time_zone}.
          </p>
        </div>
      )}
    </section>
  );
}
