import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../App";
import { resetBridgeForTests } from "../bridge/client";
import type {
  ConnectionInfo,
  MappingReview,
  MappingSuggestion,
  PythonApi,
  SyncStatus,
} from "../bridge/types";
import { clearNoticesForTests } from "../errors/notices";
import {
  connectedWithDatabase,
  dashboard,
  dayDetail,
  failWith,
  installFakeBridge,
  ok,
  removeFakeBridge,
  reviews,
  synced,
} from "../test/fakeBridge";

// Parent Task as a relation to the Task Tracker (issue #12). The reviews come from Python
// (tests/support/ui_fixtures.py) with the author's real Work Log schema.

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
});

const saved: ConnectionInfo = { ...connectedWithDatabase, database_title: "Work Log" };

const suggestion: MappingSuggestion = {
  field: "parent_task",
  field_label: "Parent task link",
  property_id: "fmJaXg",
  column_name: "Parent Task",
  message:
    "Notion now shows the Relation column “Parent Task”, which fits Parent task link. Review the column mapping to use it.",
};

const withSuggestion: SyncStatus = { ...synced, mapping_suggestions: [suggestion] };

function start(info: ConnectionInfo, review: MappingReview, overrides: Partial<PythonApi> = {}) {
  const api = installFakeBridge({
    get_connection: () => ok(info),
    get_mapping_review: () => ok(review),
    get_dashboard: () => ok(dashboard),
    ...overrides,
  });
  render(<App />);
  return api;
}

function fieldRow(label: string): HTMLElement {
  const row = screen.getByLabelText(label).closest("li");
  if (!row) throw new Error(`no row for ${label}`);
  return row;
}

function selectedText(label: string): string {
  const select = screen.getByLabelText(label);
  if (!(select instanceof HTMLSelectElement)) throw new Error(`${label} is not a select`);
  return select.selectedOptions[0]?.textContent ?? "";
}

describe("a Task Tracker that isn't shared with Habit Tracker", () => {
  it("explains how to share it, and Check again picks the column up", async () => {
    const api = start({ ...connectedWithDatabase, mapping_saved: false }, reviews.hiddenParent);
    await screen.findByLabelText("Parent task link");
    const row = within(fieldRow("Parent task link"));
    expect(row.getByText("Share the linked database to use parent task link")).toBeInTheDocument();
    expect(
      row.getByText(/Notion is hiding the relation column “Parent Task” because the database/),
    ).toBeInTheDocument();
    expect(row.getByText(/choose ••• → Connections, and add Habit Tracker/)).toBeInTheDocument();
    expect(selectedText("Parent task link")).toBe("Not used");
    // Setup can still finish without it.
    expect(screen.getByRole("button", { name: "Save mapping" })).toBeEnabled();

    api.get_mapping_review.mockImplementation(() => ok(reviews.workLog));
    await userEvent.click(row.getByRole("button", { name: "Check again" }));
    await waitFor(() => {
      expect(selectedText("Parent task link")).toBe("Parent Task · Relation");
    });
    expect(api.get_mapping_review).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByText("Share the linked database to use parent task link"),
    ).not.toBeInTheDocument();
  });

  it("explains it in general when Notion sends no trace of the column", async () => {
    const general: MappingReview = {
      ...reviews.hiddenParent,
      hidden_columns: [],
      fields: reviews.hiddenParent.fields.map((f) =>
        f.key === "parent_task"
          ? {
              ...f,
              share_help:
                "Habit Tracker can't see a relation column in this database. Then click “Check again”.",
            }
          : f,
      ),
    };
    start({ ...connectedWithDatabase, mapping_saved: false }, general);
    await screen.findByLabelText("Parent task link");
    expect(
      within(fieldRow("Parent task link")).getByText(/can't see a relation column/),
    ).toBeInTheDocument();
  });
});

describe("a relation that appears after the mapping was saved", () => {
  it("is offered on Home, opens the mapping preselected, and needs a full sync", async () => {
    const api = start(saved, reviews.newParent, {
      get_sync_status: () => ok(withSuggestion),
      start_sync: () => ok(withSuggestion),
    });
    const notice = await screen.findByRole("status", { name: "New column for Parent task link" });
    expect(notice).toHaveTextContent(suggestion.message);

    await userEvent.click(within(notice).getByRole("button", { name: "Review column mapping" }));
    await screen.findByRole("heading", { name: "Column mapping" });
    await screen.findByLabelText("Parent task link");
    const row = within(fieldRow("Parent task link"));
    expect(row.getByText("New column")).toBeInTheDocument();
    expect(row.getByText(/“Parent Task” appeared in Notion after you saved/)).toBeInTheDocument();
    expect(selectedText("Parent task link")).toBe("Parent Task · Relation");
    expect(
      screen.getByText(/a full sync is needed, so entries already copied/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save mapping" }));
    await waitFor(() => {
      expect(api.save_mapping).toHaveBeenCalled();
    });
    const [fields] = api.save_mapping.mock.calls[0] ?? [];
    expect(fields?.parent_task).toEqual({ property_id: "fmJaXg" });
  });

  it("can be dismissed, and is shown in Settings too", async () => {
    const api = start(saved, reviews.newParent, {
      get_sync_status: () => ok(withSuggestion),
      start_sync: () => ok(withSuggestion),
    });
    await screen.findByRole("status", { name: "New column for Parent task link" });
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    const notice = await screen.findByRole("status", { name: "New column for Parent task link" });

    api.get_sync_status.mockImplementation(() => ok(synced));
    api.start_sync.mockImplementation(() => ok(synced));
    await userEvent.click(within(notice).getByRole("button", { name: "Dismiss" }));
    expect(api.dismiss_mapping_suggestion).toHaveBeenCalledWith("fmJaXg");
    await waitFor(() => {
      expect(
        screen.queryByRole("status", { name: "New column for Parent task link" }),
      ).not.toBeInTheDocument();
    });
    expect(api.save_mapping).not.toHaveBeenCalled();
  });

  it("says when dismissing fails, and keeps the offer", async () => {
    const api = start(saved, reviews.newParent, {
      get_sync_status: () => ok(withSuggestion),
      start_sync: () => ok(withSuggestion),
      dismiss_mapping_suggestion: () => failWith("invalid_request", "The database is locked."),
    });
    const notice = await screen.findByRole("status", { name: "New column for Parent task link" });
    await userEvent.click(within(notice).getByRole("button", { name: "Dismiss" }));
    expect(await within(notice).findByRole("alert")).toHaveTextContent(
      "Couldn't dismiss it: The database is locked.",
    );
    expect(api.dismiss_mapping_suggestion).toHaveBeenCalledTimes(1);
    expect(within(notice).getByRole("button", { name: "Dismiss" })).toBeEnabled();
  });
});

describe("the day detail", () => {
  it("opens each session's parent task and other linked pages in Notion", async () => {
    const api = start(saved, reviews.workLog, {
      get_sync_status: () => ok(synced),
      get_day_detail: () => ok(dayDetail),
    });
    const region = within(await screen.findByRole("region", { name: "Daily totals" }));
    await userEvent.click(region.getByRole("button", { name: "Show as table" }));
    const table = region.getByRole("table", { name: "Daily totals" });
    const [firstDay] = within(table).getAllByRole("button");
    if (!firstDay) throw new Error("no days");
    await userEvent.click(firstDay);
    const dialog = within(await screen.findByRole("dialog"));
    await dialog.findByText("counted from 3 sessions");

    expect(dialog.getAllByText("Parent task")).toHaveLength(2); // p3 links no task
    await userEvent.click(
      dialog.getByRole("button", { name: "Open the parent task of Write in Notion" }),
    );
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/task1");
    await userEvent.click(
      dialog.getByRole("button", { name: "Open linked page 2 of Untitled in Notion" }),
    );
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/task2");
  });
});
