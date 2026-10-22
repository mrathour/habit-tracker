import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetBridgeForTests } from "../bridge/client";
import type { PythonApi, RawLogFilters, RawLogPage, SyncStatus } from "../bridge/types";
import { clearNoticesForTests } from "../errors/notices";
import { fail, failWith, installFakeBridge, ok, removeFakeBridge } from "../test/fakeBridge";
import { emptyRawLog, rawLogPage, rawLogRows } from "../test/rawLogFixtures";
import { RawLogView } from "./RawLogView";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
  filterChanges.mockClear();
});

/** Every filter change the view asks for. */
const filterChanges = vi.fn<(filters: RawLogFilters) => void>();

function lastFilters(): RawLogFilters | undefined {
  return filterChanges.mock.lastCall?.[0];
}

function Harness({ initial, sync }: { initial: RawLogFilters; sync: SyncStatus | null }) {
  const [filters, setFilters] = useState(initial);
  return (
    <RawLogView
      filters={filters}
      onFiltersChange={(next) => {
        filterChanges(next);
        setFilters(next);
      }}
      sync={sync}
    />
  );
}

function must<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error("missing");
  return value;
}

function start(
  overrides: Partial<PythonApi> = {},
  { filters = {}, sync = null }: { filters?: RawLogFilters; sync?: SyncStatus | null } = {},
) {
  const api = installFakeBridge(overrides);
  render(<Harness initial={filters} sync={sync} />);
  return api;
}

const grid = async () => within(await screen.findByRole("grid", { name: "Raw log" }));

function rowFor(name: RegExp | string) {
  const cell = screen.getByText(name);
  const row = cell.closest("tr");
  if (!row) throw new Error("no row");
  return row;
}

function lastRequest(api: ReturnType<typeof installFakeBridge>) {
  const calls = api.get_raw_log.mock.calls;
  const call = calls[calls.length - 1];
  if (!call) throw new Error("get_raw_log wasn't called");
  return call[0];
}

describe("states", () => {
  it("shows a loading state, then every row", async () => {
    let resolve: (page: RawLogPage) => void = () => undefined;
    const api = start({
      get_raw_log: () =>
        new Promise((done) => {
          resolve = (page) => {
            done({ ok: true, data: page });
          };
        }),
    });
    expect(screen.getByLabelText("Loading the raw log")).toBeInTheDocument();
    await waitFor(() => {
      expect(api.get_raw_log).toHaveBeenCalled();
    });
    act(() => {
      resolve(rawLogPage);
    });
    const table = await grid();
    expect(table.getAllByRole("row")).toHaveLength(rawLogRows.length + 1);
    expect(screen.getByRole("status")).toHaveTextContent("5 entries");
    expect(table.getByText("Write docs")).toBeInTheDocument();
    expect(table.getByText("Réunion équipe")).toBeInTheDocument();
    // A blank task name shows as Untitled.
    expect(table.getByText("Untitled")).toBeInTheDocument();
  });

  it("explains an empty log, and that a sync is copying entries", async () => {
    start({ get_raw_log: () => ok(emptyRawLog) });
    expect(await screen.findByText("No entries yet", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText(/after the first sync|copied to this computer/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export CSV" })).not.toBeInTheDocument();
  });

  it("says when the sync is copying entries now", async () => {
    const running = {
      running: { kind: "full", phase: "fetching", pages_fetched: 3 },
      last_result: null,
      entries: 0,
    } as unknown as SyncStatus;
    start({ get_raw_log: () => ok(emptyRawLog) }, { sync: running });
    expect(await screen.findByText(/being copied now/)).toBeInTheDocument();
  });

  it("offers to clear filters when nothing matches", async () => {
    start(
      { get_raw_log: () => ok({ ...rawLogPage, matched: 0, rows: [] }) },
      { filters: { search: "nothing" } },
    );
    expect(await screen.findByText("No entries match these filters")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Showing 0 of 5 entries");
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeDisabled();
    await userEvent.click(must(screen.getAllByRole("button", { name: "Clear filters" })[0]));
    expect(lastFilters()).toEqual({});
  });

  it("shows an error with Try again", async () => {
    const api = start({ get_raw_log: () => fail("boom") });
    expect(await screen.findByText("The raw log couldn't be loaded")).toBeInTheDocument();
    expect(screen.getByText(/Error ID/)).toBeInTheDocument();
    api.get_raw_log.mockImplementation(() => ok(rawLogPage));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await grid()).toBeTruthy();
  });

  it("refreshes when a sync finishes", async () => {
    const api = installFakeBridge();
    const { rerender } = render(<RawLogView filters={{}} onFiltersChange={vi.fn()} sync={null} />);
    await grid();
    const before = api.get_raw_log.mock.calls.length;
    const finished = {
      running: null,
      last_result: { finished_at: "2026-10-22T11:00:00.000Z" },
      entries: 6,
    } as unknown as SyncStatus;
    rerender(<RawLogView filters={{}} onFiltersChange={vi.fn()} sync={finished} />);
    await waitFor(() => {
      expect(api.get_raw_log.mock.calls.length).toBeGreaterThan(before);
    });
  });
});

describe("issues and overlaps", () => {
  it("turns flagged cells red and explains them", async () => {
    start();
    await grid();
    const mismatch = rowFor("Réunion équipe");
    const logged = must(within(mismatch).getByText("200 min").closest("td"));
    expect(logged).toHaveClass("cell-issue");
    expect(logged).toHaveAttribute("data-tip", "Logged 200 min, but Start → End is 120 min.");
    expect(within(logged).getByText(/Issue: Logged 200 min/)).toHaveClass("visually-hidden");
    // Invalid range colours both Start and End.
    const backwards = rowFor("Backwards");
    const issueCells = backwards.querySelectorAll("td.cell-issue");
    expect([...issueCells].map((td) => td.getAttribute("data-kind"))).toEqual(["start", "end"]);
    // Missing time colours End only.
    const noEnd = rowFor("No end");
    expect(
      [...noEnd.querySelectorAll("td.cell-issue")].map((td) => td.getAttribute("data-kind")),
    ).toEqual(["end"]);
  });

  it("shows the explanation on hover", async () => {
    start();
    await grid();
    const logged = within(rowFor("Réunion équipe")).getByText("200 min");
    fireEvent.mouseOver(logged);
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Logged 200 min, but Start → End is 120 min.",
    );
  });

  it("lists every issue from the Issues cell", async () => {
    start();
    await grid();
    await userEvent.click(within(rowFor("No end")).getByRole("button", { name: "1 issue" }));
    const panel = screen.getByRole("dialog", { name: "Issues with #3 No end" });
    expect(panel).toHaveTextContent("End time is empty.");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("marks overlapping sessions without turning them red", async () => {
    start();
    await grid();
    const row = rowFor("Write docs");
    const marker = must(within(row).getByText("30 min").closest(".overlap-marker"));
    expect(marker).toHaveAttribute("data-tip", "Overlaps #2 Untitled by 30 min.");
    expect(marker.closest("td")).not.toHaveClass("cell-issue");
  });
});

describe("links and selection", () => {
  it("selects a row on click and opens it only on purpose", async () => {
    const api = start();
    await grid();
    const row = rowFor("Write docs");
    await userEvent.click(within(row).getByText("Write docs"));
    expect(row).toHaveAttribute("aria-selected", "true");
    expect(api.open_external).not.toHaveBeenCalled();
    await userEvent.dblClick(within(row).getByText("Write docs"));
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/p1");
  });

  it("opens a row with its button", async () => {
    const api = start();
    await grid();
    await userEvent.click(
      screen.getByRole("button", { name: "Open #10 Réunion équipe in Notion" }),
    );
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/p3");
  });

  it("moves the selection with the keyboard and opens with Enter", async () => {
    const api = start();
    const table = await grid();
    const element = screen.getByRole("grid", { name: "Raw log" });
    element.focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    const selected = table
      .getAllByRole("row")
      .find((r) => r.getAttribute("aria-selected") === "true");
    expect(selected).toHaveTextContent("Réunion équipe");
    expect(element).toHaveAttribute("aria-activedescendant", "rawlog-row-1");
    await userEvent.keyboard("{End}{Enter}");
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/p5");
  });

  it("opens parent tasks and lists every linked page", async () => {
    const api = start();
    await grid();
    const row = rowFor("Write docs").previousElementSibling as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Parent task" }));
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/t2");
    await userEvent.click(within(row).getByRole("button", { name: "1 more linked pages" }));
    const panel = screen.getByRole("dialog", { name: /Pages linked to/ });
    expect(within(panel).getByText("Linked page 2")).toBeInTheDocument();
    await userEvent.click(
      must(within(panel).getAllByRole("button", { name: "Open in Notion" })[1]),
    );
    expect(api.open_external).toHaveBeenLastCalledWith("https://www.notion.so/t1");
    await userEvent.click(
      must(within(panel).getAllByRole("button", { name: "Show its entries" })[1]),
    );
    expect(lastFilters()).toEqual({ no_parent: false, parents: ["t1"] });
  });

  it("shows relation extra fields as links", async () => {
    const api = start();
    await grid();
    const row = rowFor("Write docs");
    await userEvent.click(within(row).getByRole("button", { name: "Linked page 1" }));
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/r1");
  });
});

describe("sorting and columns", () => {
  it("sorts by a column and remembers it", async () => {
    const api = start();
    await grid();
    const header = screen.getByRole("columnheader", { name: /Task name/ });
    expect(screen.getByRole("columnheader", { name: /Start/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    await userEvent.click(within(header).getByRole("button"));
    expect(api.set_raw_log_view).toHaveBeenCalledWith({
      sort: { column: "task_name", direction: "asc" },
    });
    await waitFor(() => {
      expect(lastRequest(api).sort).toEqual({ column: "task_name", direction: "asc" });
    });
    await userEvent.click(within(header).getByRole("button"));
    expect(api.set_raw_log_view).toHaveBeenLastCalledWith({
      sort: { column: "task_name", direction: "desc" },
    });
  });

  it("asks for the remembered sort on first load", async () => {
    const api = start();
    await grid();
    expect(api.get_raw_log.mock.calls[0]?.[0]).not.toHaveProperty("sort");
  });

  it("hides columns, keeps one, and remembers the choice", async () => {
    const api = start();
    await grid();
    await userEvent.click(screen.getByRole("button", { name: "Columns" }));
    const picker = screen.getByRole("dialog", { name: "Show or hide columns" });
    await userEvent.click(within(picker).getByRole("checkbox", { name: /^Mood/ }));
    expect(api.set_raw_log_view).toHaveBeenCalledWith({ hidden: ["extra:mood"] });
    expect(screen.queryByRole("columnheader", { name: /Mood/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Columns (1 hidden)" })).toBeInTheDocument();
  });

  it("never hides the last column", async () => {
    const keys = rawLogPage.columns.map((c) => c.key);
    start({
      get_raw_log: () => ok({ ...rawLogPage, view: { ...rawLogPage.view, hidden: keys.slice(1) } }),
    });
    await grid();
    await userEvent.click(screen.getByRole("button", { name: /Columns/ }));
    expect(screen.getByRole("checkbox", { name: /^ID/ })).toBeDisabled();
  });

  it("resizes a column from the keyboard and remembers it", async () => {
    const api = start();
    await grid();
    const handle = screen.getByRole("separator", { name: "Resize Task name" });
    expect(handle).toHaveAttribute("aria-valuenow", "240");
    handle.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(api.set_raw_log_view).toHaveBeenCalledWith({ widths: { task_name: 256 } });
    expect(handle).toHaveAttribute("aria-valuenow", "256");
  });

  it("uses remembered widths", async () => {
    start({
      get_raw_log: () =>
        ok({ ...rawLogPage, view: { ...rawLogPage.view, widths: { task_name: 400 } } }),
    });
    await grid();
    expect(screen.getByRole("separator", { name: "Resize Task name" })).toHaveAttribute(
      "aria-valuenow",
      "400",
    );
  });
});

describe("loading rows as the table scrolls", () => {
  it("asks for the next block when it comes into view", async () => {
    const api = start({
      get_raw_log: (request) =>
        ok({
          ...rawLogPage,
          matched: 250,
          total_entries: 250,
          offset: request.offset,
          rows: request.offset === 0 ? rawLogRows : [],
        }),
    });
    await grid();
    const scroller = must(document.querySelector(".rawlog-scroll"));
    scroller.scrollTop = 120 * 36;
    fireEvent.scroll(scroller);
    await waitFor(() => {
      expect(api.get_raw_log).toHaveBeenCalledWith(expect.objectContaining({ offset: 100 }));
    });
    expect(screen.getAllByLabelText("Loading").length).toBeGreaterThan(0);
  });

  it("offers to try again when a block fails", async () => {
    start({
      get_raw_log: (request) =>
        request.offset === 0
          ? ok({ ...rawLogPage, matched: 250, total_entries: 250 })
          : fail("boom"),
    });
    await grid();
    const scroller = must(document.querySelector(".rawlog-scroll"));
    scroller.scrollTop = 120 * 36;
    fireEvent.scroll(scroller);
    expect((await screen.findAllByText(/couldn't be loaded/)).length).toBeGreaterThan(0);
  });
});

describe("filters", () => {
  it("searches task names after typing pauses", async () => {
    const api = start();
    await grid();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search task names" }), "docs");
    await waitFor(() => {
      expect(lastRequest(api).filters).toEqual({ search: "docs" });
    });
    expect(screen.getByRole("list", { name: "Active filters" })).toHaveTextContent(
      "Task name contains “docs”",
    );
  });

  it("filters on issues, issue types and overlaps", async () => {
    const api = start();
    await grid();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Issues" }), "any");
    await userEvent.click(screen.getByRole("checkbox", { name: "Overlaps another session" }));
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Invalid range" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Missing time" }));
    await waitFor(() => {
      expect(lastRequest(api).filters).toEqual({
        issues: "any",
        overlaps: true,
        issue_codes: ["invalid_range", "missing_time"],
      });
    });
    expect(screen.getByRole("list", { name: "Active filters" })).toHaveTextContent(
      "Invalid range or Missing time",
    );
  });

  it("filters by date, parent task and duration", async () => {
    const api = start();
    await grid();
    fireEvent.change(screen.getByLabelText("Started on or after"), {
      target: { value: "2026-10-20" },
    });
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Page t1/ }));
    await userEvent.type(screen.getByLabelText("Shortest duration in minutes"), "30");
    await waitFor(() => {
      expect(lastRequest(api).filters).toEqual({
        date_from: "2026-10-20",
        parents: ["t1"],
        duration_min: 30,
      });
    });
    await userEvent.click(screen.getByRole("checkbox", { name: "No parent task" }));
    await waitFor(() => {
      expect(lastRequest(api).filters).toMatchObject({ no_parent: true });
    });
  });

  it("holds back a contradictory range with a reason", async () => {
    const api = start();
    await grid();
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await userEvent.type(screen.getByLabelText("Shortest duration in minutes"), "90");
    await userEvent.type(screen.getByLabelText("Longest duration in minutes"), "30");
    expect(
      await screen.findByText("The longest duration is shorter than the shortest."),
    ).toBeInTheDocument();
    expect(lastRequest(api).filters).not.toHaveProperty("duration_max");
  });

  it("offers a filter for each extra field by its type", async () => {
    const api = start();
    await grid();
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Mood filter" }), "match");
    await userEvent.click(screen.getByRole("checkbox", { name: "Focused" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Billable filter" }), "yes");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Related filter" }),
      "not_empty",
    );
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Score filter" }), "match");
    await userEvent.type(screen.getByLabelText("Score: lowest"), "2");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Notes filter" }), "match");
    await userEvent.type(screen.getByRole("searchbox", { name: "Notes contains" }), "メモ");
    await waitFor(() => {
      expect(lastRequest(api).filters).toEqual({
        extra: {
          mood: { op: "any_of", values: ["Focused"] },
          bill: { op: "is", value: true },
          rel: { op: "not_empty" },
          score: { op: "range", min: 2, max: null },
          notes: { op: "contains", value: "メモ" },
        },
      });
    });
    // Related is a relation: only empty or not.
    const related = screen.getByRole("combobox", { name: "Related filter" });
    expect(within(related).queryByRole("option", { name: "Contains" })).not.toBeInTheDocument();
  });

  it("removes one filter or all of them", async () => {
    start({}, { filters: { search: "docs", issues: "any", overlaps: true } });
    await grid();
    const chips = screen.getByRole("list", { name: "Active filters" });
    await userEvent.click(within(chips).getByRole("button", { name: "Remove filter: Has issues" }));
    expect(lastFilters()).toEqual({ search: "docs", overlaps: true });
    await userEvent.click(within(chips).getByRole("button", { name: "Clear all" }));
    expect(lastFilters()).toEqual({});
    expect(screen.getByRole("searchbox", { name: "Search task names" })).toHaveValue("");
  });
});

describe("CSV export", () => {
  it("exports the visible columns and shows where the file went", async () => {
    const api = start({}, { filters: { issues: "any" } });
    await grid();
    await userEvent.click(screen.getByRole("button", { name: "Columns" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /^Notes/ }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(api.export_raw_log).toHaveBeenCalledWith(
      { time_zone: expect.any(String) as string, filters: { issues: "any" } },
      rawLogPage.columns.map((c) => c.key).filter((key) => key !== "extra:notes"),
    );
    expect(await screen.findByText("Exported 5 entries")).toBeInTheDocument();
    expect(screen.getByText("C:\\Users\\me\\log.csv")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show in folder" }));
    expect(api.show_exported_file).toHaveBeenCalled();
  });

  it("exports in the sort order chosen", async () => {
    const api = start();
    await grid();
    await userEvent.click(
      within(screen.getByRole("columnheader", { name: /Duration/ })).getByRole("button"),
    );
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(api.export_raw_log.mock.calls[0]?.[0]).toMatchObject({
      sort: { column: "duration", direction: "desc" },
    });
  });

  it("does nothing visible when the dialog is cancelled", async () => {
    start({ export_raw_log: () => ok({ status: "cancelled", path: null, rows: 0 }) });
    await grid();
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Export CSV" })).toBeEnabled();
    });
    expect(screen.queryByText(/Exported/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains a file that couldn't be written, with Try again", async () => {
    const api = start({
      export_raw_log: () =>
        failWith(
          "export_failed",
          "“log.csv” couldn't be saved. It may be open in another program, such as Excel.",
        ),
    });
    await grid();
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(await screen.findByText("The CSV file wasn't saved")).toBeInTheDocument();
    expect(screen.getByText(/open in another program, such as Excel/)).toBeInTheDocument();
    api.export_raw_log.mockImplementation(() =>
      ok({ status: "saved", path: "C:\\out.csv", rows: 5 }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Exported 5 entries")).toBeInTheDocument();
  });

  it("says when nothing matched by the time it ran", async () => {
    start({ export_raw_log: () => ok({ status: "empty", path: null, rows: 0 }) });
    await grid();
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(await screen.findByText(/nothing to export/)).toBeInTheDocument();
  });
});
