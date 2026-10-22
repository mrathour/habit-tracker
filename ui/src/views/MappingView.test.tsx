import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../App";
import { resetBridgeForTests } from "../bridge/client";
import type { ConnectionInfo, MappingReview } from "../bridge/types";
import { clearNoticesForTests } from "../errors/notices";
import {
  connectedNoDatabase,
  connectedUnmapped,
  connectedWithDatabase,
  failWith,
  fullSyncDone,
  installFakeBridge,
  ok,
  removeFakeBridge,
  reviews,
  synced,
} from "../test/fakeBridge";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
});

function startWith(info: ConnectionInfo, review: MappingReview = reviews.workLog) {
  const api = installFakeBridge({
    get_connection: () => ok(info),
    get_mapping_review: () => ok(review),
  });
  render(<App />);
  return api;
}

function fieldRow(label: string): HTMLElement {
  const select = screen.getByLabelText(label);
  const row = select.closest("li");
  if (!row) throw new Error(`no row for ${label}`);
  return row;
}

function selectedText(label: string): string {
  const select = screen.getByLabelText(label);
  if (!(select instanceof HTMLSelectElement)) throw new Error(`${label} is not a select`);
  return select.selectedOptions[0]?.textContent ?? "";
}

const saveButton = () => screen.getByRole("button", { name: "Save mapping" });

/** The heading shows at once; wait until the review itself has loaded. */
async function reviewLoaded(heading = "Map your columns") {
  await screen.findByRole("heading", { name: heading });
  await screen.findByLabelText("Start time");
}

describe("first-time mapping of the Work Log", () => {
  it("opens after choosing the database and matches every field", async () => {
    startWith(connectedUnmapped);
    await reviewLoaded();
    expect(selectedText("Start time")).toBe("Start Time · Date");
    expect(selectedText("End time")).toBe("End Time · Date");
    expect(selectedText("Task name")).toBe("Name · Title");
    expect(selectedText("Parent task link")).toBe("Parent Task · Relation");
    expect(selectedText("Display ID")).toBe("ID · ID");
    expect(selectedText("Logged minutes")).toBe("MinuteSpent · Number");
    expect(within(fieldRow("Start time")).getByText("Matched automatically")).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("shows real sample values beside each field", async () => {
    startWith(connectedUnmapped);
    await reviewLoaded();
    const minutes = within(fieldRow("Logged minutes"));
    expect(minutes.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "37",
      "128",
      "2",
    ]);
    expect(within(fieldRow("Task name")).getByText("Writing EVA resume")).toBeInTheDocument();
    expect(within(fieldRow("Display ID")).getByText("8")).toBeInTheDocument();
    expect(within(fieldRow("Parent task link")).getAllByText("1 linked page")).toHaveLength(3);
    expect(within(fieldRow("Start time")).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("Samples from the latest 3 entries")).toBeInTheDocument();
  });

  it("saves and confirms on the home screen", async () => {
    const api = startWith(connectedUnmapped);
    await reviewLoaded();
    api.get_connection.mockImplementation(() => ok(connectedWithDatabase));
    await userEvent.click(saveButton());
    expect(await screen.findByText("Column mapping saved.")).toBeInTheDocument();
    expect(api.save_mapping).toHaveBeenCalledWith(
      {
        start: { property_id: "%3DjVp", part: "start" },
        end: { property_id: "Q%5Ckh", part: "start" },
        task_name: { property_id: "title" },
        parent_task: { property_id: "fmJa" },
        display_id: { property_id: "%7BmH%40" },
        logged_minutes: { property_id: "ZCx%3F" },
      },
      [],
    );
  });

  it("offers only compatible columns, and marks ones already used", async () => {
    startWith(connectedUnmapped);
    await reviewLoaded();
    const display = screen.getByLabelText("Display ID");
    const options = within(display).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Not used",
      "ID · ID",
      "MinuteSpent · Number (used for Logged minutes)",
    ]);
    expect(options[2]).toBeDisabled();
  });

  it("can set an optional field to Not used", async () => {
    const api = startWith(connectedUnmapped);
    await reviewLoaded();
    await userEvent.selectOptions(screen.getByLabelText("Display ID"), "Not used");
    expect(within(fieldRow("Display ID")).getByText("No column chosen")).toBeInTheDocument();
    api.get_connection.mockImplementation(() => ok(connectedWithDatabase));
    await userEvent.click(saveButton());
    await waitFor(() => {
      expect(api.save_mapping).toHaveBeenCalled();
    });
    expect(api.save_mapping.mock.calls[0]?.[0].display_id).toBeNull();
  });
});

describe("additional fields", () => {
  it("lists unmapped columns with samples, and explains the ones that can't be used", async () => {
    const api = startWith(connectedUnmapped);
    await reviewLoaded();
    const list = within(screen.getByRole("list", { name: "Additional fields" }));
    expect(list.getByText("Focused")).toBeInTheDocument();
    const button = list.getByRole("checkbox", { name: /Log it/ });
    expect(button).toBeDisabled();
    expect(list.getByText(/Buttons run actions in Notion and hold no value/)).toBeInTheDocument();
    expect(list.getByText(/doesn't share this kind of property/)).toBeInTheDocument();

    await userEvent.click(list.getByRole("checkbox", { name: /Mood/ }));
    api.get_connection.mockImplementation(() => ok(connectedWithDatabase));
    await userEvent.click(saveButton());
    await waitFor(() => {
      expect(api.save_mapping).toHaveBeenCalled();
    });
    expect(api.save_mapping.mock.calls[0]?.[1]).toEqual(["mood"]);
  });

  it("moves a column out of the list when a field uses it", async () => {
    startWith(connectedUnmapped);
    await reviewLoaded();
    const list = () => within(screen.getByRole("list", { name: "Additional fields" }));
    expect(list().queryByText("MinuteSpent")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Logged minutes"), "Not used");
    expect(list().getByText("MinuteSpent")).toBeInTheDocument();
  });
});

describe("a database with no end-time column", () => {
  it("explains exactly what is missing and blocks saving", async () => {
    startWith({ ...connectedUnmapped, database_title: "Work Log (no end)" }, reviews.noEnd);
    await reviewLoaded();
    const end = within(fieldRow("End time"));
    expect(end.getByText("Missing")).toBeInTheDocument();
    expect(end.getByText("Your database is missing a column for end time")).toBeInTheDocument();
    expect(
      end.getByText(
        "Your database needs a second Date column to use as the end time. In Notion, add a Date " +
          "column for when each session ends and turn on “Include time”. Or, if “Start Time” " +
          "holds each session as a date range (start → end), choose “End of the date range in " +
          "“Start Time”” for End time.",
      ),
    ).toBeInTheDocument();
    expect(selectedText("End time")).toBe("Choose a Date column…");
    expect(screen.getByRole("alert", { name: "Before you can save" })).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("can use the end of the start column's date range instead", async () => {
    startWith(connectedUnmapped, reviews.noEnd);
    await reviewLoaded();
    await userEvent.selectOptions(
      screen.getByLabelText("End time"),
      "End of the date range in “Start Time”",
    );
    expect(
      within(fieldRow("End time")).getByText(/None of the latest 3 entries has an end date/),
    ).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
  });
});

describe("a single date-range column", () => {
  it("uses its start and end, and flags dates without a time", async () => {
    startWith(connectedUnmapped, reviews.range);
    await reviewLoaded();
    expect(selectedText("Start time")).toBe("Session · Date");
    expect(selectedText("End time")).toBe("End of the date range in “Session”");
    const start = within(fieldRow("Start time"));
    expect(start.getByText("no time")).toBeInTheDocument();
    expect(
      start.getByText(/1 of the latest 2 entries have a date without a time/),
    ).toBeInTheDocument();
    expect(within(fieldRow("End time")).getAllByRole("listitem")).toHaveLength(1);
  });
});

describe("columns too close to call", () => {
  it("asks instead of guessing, then saves once chosen", async () => {
    const api = startWith(connectedUnmapped, reviews.ambiguous);
    await reviewLoaded();
    expect(within(fieldRow("Start time")).getByText("Please choose")).toBeInTheDocument();
    expect(selectedText("Start time")).toBe("Please choose…");
    expect(
      within(fieldRow("Start time")).getByText(/“Date” and “Date 2” fit equally well/),
    ).toBeInTheDocument();
    expect(selectedText("Parent task link")).toBe("Please choose…");
    expect(saveButton()).toBeDisabled();

    await userEvent.selectOptions(screen.getByLabelText("Start time"), "Date · Date");
    await userEvent.selectOptions(screen.getByLabelText("End time"), "Date 2 · Date");
    expect(saveButton()).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Parent task link"), "Not used");
    expect(within(fieldRow("Start time")).getByText("Your choice")).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
    api.get_connection.mockImplementation(() => ok(connectedWithDatabase));
    await userEvent.click(saveButton());
    await waitFor(() => {
      expect(api.save_mapping).toHaveBeenCalled();
    });
  });
});

describe("a database with no entries yet", () => {
  it("maps from the columns alone", async () => {
    startWith(connectedUnmapped, reviews.empty);
    await reviewLoaded();
    expect(screen.getByText("No entries yet", { selector: "strong" })).toBeInTheDocument();
    expect(within(fieldRow("Start time")).getByText("No entries yet")).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
  });
});

describe("loading and problems", () => {
  it("shows a loading state", async () => {
    installFakeBridge({
      get_connection: () => ok(connectedUnmapped),
      get_mapping_review: () => new Promise(() => undefined),
    });
    render(<App />);
    expect(await screen.findByLabelText("Loading columns")).toBeInTheDocument();
  });

  it("retries after an error", async () => {
    const api = installFakeBridge({
      get_connection: () => ok(connectedUnmapped),
      get_mapping_review: () => failWith("offline", "You're offline, or Notion can't be reached."),
    });
    render(<App />);
    expect(await screen.findByText("You're offline")).toBeInTheDocument();
    api.get_mapping_review.mockImplementation(() => ok(reviews.workLog));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("Start time")).toBeInTheDocument();
  });

  it("offers to reconnect when Notion refused the sign-in", async () => {
    const api = installFakeBridge({
      get_connection: () => ok(connectedUnmapped),
      get_mapping_review: () => failWith("reconnect", "Notion no longer accepts the access."),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Reconnect to Notion" }));
    expect(api.start_sign_in).toHaveBeenCalled();
  });

  it("sends a pasted-token user to paste a new one", async () => {
    installFakeBridge({
      get_connection: () => ok({ ...connectedUnmapped, auth_kind: "pat" }),
      get_mapping_review: () => failWith("paste_new_token", "Notion no longer accepts the token."),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Paste a new token" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  });

  it("goes back to the picker when the database can't be opened", async () => {
    installFakeBridge({
      get_connection: () => ok(connectedUnmapped),
      get_mapping_review: () =>
        failWith("source_unavailable", "Habit Tracker can't open “Work Log” any more."),
    });
    render(<App />);
    expect(await screen.findByText("Your work log can't be opened")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Choose the database again" }));
    expect(
      await screen.findByRole("heading", { name: "Choose your work log" }),
    ).toBeInTheDocument();
  });

  it("shows why saving failed", async () => {
    startWith(connectedUnmapped);
    await reviewLoaded();
    const api = window.pywebview?.api;
    if (!api) throw new Error("no bridge");
    (
      api.save_mapping as unknown as { mockImplementation: (f: () => unknown) => void }
    ).mockImplementation(() =>
      failWith("mapping_invalid", "The column chosen for End time no longer exists in Notion."),
    );
    await userEvent.click(saveButton());
    expect(await screen.findByText("The mapping can't be saved")).toBeInTheDocument();
    expect(screen.getByText(/no longer exists in Notion/)).toBeInTheDocument();
  });
});

describe("changing a saved mapping", () => {
  const saved: ConnectionInfo = { ...connectedWithDatabase, database_title: "Work Log" };

  it("reopens from Settings and can be cancelled", async () => {
    startWith(saved, { ...reviews.workLog, saved: true });
    await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
    await userEvent.click(screen.getByRole("button", { name: "Review column mapping" }));
    expect(await screen.findByRole("heading", { name: "Column mapping" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("heading", { name: "Work Log" })).toBeInTheDocument();
  });

  it("runs the full sync a changed mapping needs, and flags it until it succeeds", async () => {
    const flag = {
      since: "2026-10-22T10:00:00.000Z",
      reason: "The column mapping changed, so entries already copied need the new columns.",
    };
    const api = startWith(saved, { ...reviews.workLog, saved: true });
    await userEvent.click(await screen.findByRole("button", { name: "Review column mapping" }));
    await reviewLoaded("Column mapping");
    await userEvent.selectOptions(screen.getByLabelText("Display ID"), "Not used");
    expect(
      screen.getByText(/a full sync is needed, so entries already copied/),
    ).toBeInTheDocument();
    api.save_mapping.mockImplementation(() => ok({ changed: true, full_sync_required: flag }));
    api.get_connection.mockImplementation(() => ok({ ...saved, full_sync_required: flag }));
    // The full sync can't run (offline), so the flag stays and Home says so.
    const offline = {
      ...synced,
      full_sync_required: true,
      last_result: {
        ...fullSyncDone,
        ok: false,
        error: { id: "e1", code: "offline" as const, message: "Offline.", issues: [] },
      },
    };
    api.start_sync.mockImplementation(() => ok(offline));
    api.get_sync_status.mockImplementation(() => ok(offline));
    api.start_sync.mockClear();
    await userEvent.click(saveButton());
    const notice = await screen.findByRole("status", { name: "Full sync required" });
    expect(notice).toHaveTextContent("Mapping saved: a full sync is needed");
    expect(notice).toHaveTextContent(flag.reason);
    expect(api.start_sync).toHaveBeenCalledWith("auto");

    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("Full sync required")).toBeInTheDocument();
  });

  it("shows what changed in Notion since the mapping was saved", async () => {
    startWith(saved, reviews.changed);
    await userEvent.click(await screen.findByRole("button", { name: "Review column mapping" }));
    expect(await screen.findByText("Syncing can't start until this is fixed")).toBeInTheDocument();
    expect(
      screen.getAllByText(/The column “End Time” used for End time no longer exists in Notion/),
    ).not.toHaveLength(0);
    expect(screen.getByText(/The additional column “Mood” no longer exists/)).toBeInTheDocument();
    expect(within(fieldRow("End time")).getByText("Column removed in Notion")).toBeInTheDocument();
    expect(
      within(fieldRow("Start time")).getByText(
        "Renamed in Notion from “Start Time”. The mapping still works.",
      ),
    ).toBeInTheDocument();
    expect(selectedText("Start time")).toBe("Began at · Date");
    expect(saveButton()).toBeDisabled();
  });

  it("is offered from Settings before the first mapping too", async () => {
    startWith({
      ...connectedNoDatabase,
      database_id: "db",
      data_source_id: "ds",
      mapping_saved: false,
    });
    await reviewLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("Not mapped yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Map your columns" }));
    expect(await screen.findByRole("heading", { name: "Map your columns" })).toBeInTheDocument();
  });
});
