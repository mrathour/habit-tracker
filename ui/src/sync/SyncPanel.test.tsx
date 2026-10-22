import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../App";
import { resetBridgeForTests } from "../bridge/client";
import type { PythonApi, SchemaIssue, SyncStatus } from "../bridge/types";
import { clearNoticesForTests } from "../errors/notices";
import {
  connectedWithDatabase,
  fail,
  failWith,
  flaggedPage,
  fullSyncDone,
  installFakeBridge,
  neverSynced,
  ok,
  pushBackendEvent,
  removeFakeBridge,
  synced,
} from "../test/fakeBridge";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
});

function startWith(status: SyncStatus, overrides: Partial<PythonApi> = {}) {
  const api = installFakeBridge({
    get_connection: () => ok(connectedWithDatabase),
    get_sync_status: () => ok(status),
    start_sync: () => ok(status),
    ...overrides,
  });
  render(<App />);
  return api;
}

const panel = async () => within(await screen.findByRole("region", { name: "Last sync" }));

function failed(code: string, message: string, issues: SchemaIssue[] = []): SyncStatus {
  return {
    ...synced,
    last_result: {
      ...fullSyncDone,
      ok: false,
      error: { id: "5eed0001", code: code as never, message, issues },
    },
  };
}

function first<T>(items: readonly T[]): T {
  const item = items[0];
  if (item === undefined) throw new Error("empty list");
  return item;
}

describe("syncing on launch", () => {
  it("starts one automatic sync once the work log is mapped", async () => {
    const api = startWith(neverSynced);
    await screen.findByRole("heading", { name: "Work Log (test)" });
    await waitFor(() => {
      expect(api.start_sync).toHaveBeenCalledWith("auto");
    });
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    await userEvent.click(screen.getByRole("button", { name: "Home" }));
    expect(api.start_sync).toHaveBeenCalledTimes(1);
  });

  it("doesn't sync before the columns are mapped", async () => {
    const api = installFakeBridge({
      get_connection: () => ok({ ...connectedWithDatabase, mapping_saved: false }),
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Map your columns" });
    expect(api.start_sync).not.toHaveBeenCalled();
    expect(api.get_sync_status).not.toHaveBeenCalled();
  });

  it("says when nothing has been synced yet", async () => {
    startWith(neverSynced);
    expect(await (await panel()).findByText(/Not synced yet/)).toBeInTheDocument();
    expect(screen.getByText("Not synced yet", { selector: ".sync-indicator" })).toBeInTheDocument();
  });
});

describe("while a sync runs", () => {
  it("shows a quick sync subtly", async () => {
    startWith({
      ...synced,
      running: {
        kind: "quick",
        phase: "fetching",
        pages_fetched: 0,
        added: 0,
        updated: 0,
        removed: 0,
      },
    });
    expect(await screen.findByText("Syncing…")).toBeInTheDocument();
    expect(
      within(await screen.findByRole("region", { name: "Last sync" })).getByText(
        "Checking for changes…",
      ),
    ).toBeInTheDocument();
  });

  it("shows a full sync's progress, then its summary when it ends", async () => {
    startWith({
      ...neverSynced,
      running: {
        kind: "full",
        phase: "fetching",
        pages_fetched: 120,
        added: 118,
        updated: 2,
        removed: 0,
      },
    });
    const region = await panel();
    expect(await region.findByText("Full sync: 120 entries read")).toBeInTheDocument();
    expect(region.getByText("118 added · 2 updated · 0 removed so far")).toBeInTheDocument();
    expect(screen.getAllByText("Full sync: 120 entries read")).toHaveLength(2); // top bar too

    act(() => {
      pushBackendEvent({ name: "sync:status", payload: synced });
    });
    expect(await region.findByText("7 added · 0 updated · 0 removed")).toBeInTheDocument();
    expect(region.getByText("Full sync")).toBeInTheDocument();
    expect(region.getByText("First sync of this work log.")).toBeInTheDocument();
    expect(screen.getByText(/^Synced /, { selector: ".sync-indicator" })).toBeInTheDocument();
  });
});

describe("after a sync", () => {
  it("shows counts and every flagged entry with its explanation", async () => {
    const api = startWith(synced, { get_flagged_entries: () => ok(flaggedPage) });
    const region = await panel();
    expect(
      await region.findByText("Logged 148 min, but Start → End is 123 min."),
    ).toBeInTheDocument();
    expect(region.getByText("Entries with issues (5)")).toBeInTheDocument();
    expect(region.getByText("Untitled")).toBeInTheDocument();
    expect(region.getByText("No start time")).toBeInTheDocument();
    expect(region.getByText("Start time is empty.")).toBeInTheDocument();
    expect(region.getByText("#9")).toBeInTheDocument();
    await userEvent.click(first(region.getAllByRole("button", { name: "Open in Notion" })));
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/pmismatch");
  });

  it("loads more flagged entries", async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({
      ...first(flaggedPage.entries),
      page_id: `p${String(i)}`,
    }));
    const api = startWith(
      { ...synced, flagged: 60 },
      { get_flagged_entries: () => ok({ entries: many, total: 60 }) },
    );
    const region = await panel();
    await userEvent.click(await region.findByRole("button", { name: "Show more" }));
    expect(api.get_flagged_entries).toHaveBeenLastCalledWith(50, 50);
  });

  it("lists nothing when no entry has issues", async () => {
    const api = startWith({ ...synced, flagged: 0 });
    const region = await panel();
    await region.findByText("7 added · 0 updated · 0 removed");
    expect(region.queryByText(/Entries with issues/)).not.toBeInTheDocument();
    expect(api.get_flagged_entries).not.toHaveBeenCalled();
  });

  it("explains that formula and rollup values refresh with each full sync", async () => {
    startWith(synced);
    expect(
      await (await panel()).findByText(/Formula and rollup values refresh with each full sync/),
    ).toBeInTheDocument();
  });

  it("reports skipped pages and schema warnings", async () => {
    startWith({
      ...synced,
      last_result: {
        ...fullSyncDone,
        skipped: 1,
        warnings: ["The column “MinuteSpent” used for Logged minutes no longer exists in Notion."],
      },
    });
    const region = await panel();
    expect(await region.findByText(/1 page from Notion couldn't be read/)).toBeInTheDocument();
    expect(region.getByText("Synced without some columns")).toBeInTheDocument();
    await userEvent.click(region.getByRole("button", { name: "Open column mapping" }));
    expect(await screen.findByRole("heading", { name: "Column mapping" })).toBeInTheDocument();
  });

  it("can sync again on demand", async () => {
    const api = startWith(synced);
    const region = await panel();
    await waitFor(() => {
      expect(api.start_sync).toHaveBeenCalledWith("auto");
    });
    await userEvent.click(await region.findByRole("button", { name: "Sync now" }));
    expect(api.start_sync).toHaveBeenLastCalledWith("quick");
  });
});

describe("when a sync fails", () => {
  it("says an offline sync was skipped and local data is kept", async () => {
    const api = startWith(failed("offline", "You're offline."));
    const region = await panel();
    expect(await region.findByText("Offline: sync skipped")).toBeInTheDocument();
    expect(region.getByText(/Your local data is still here/)).toBeInTheDocument();
    expect(
      screen.getByText("Offline: sync skipped", { selector: ".sync-indicator" }),
    ).toBeInTheDocument();
    await userEvent.click(region.getByRole("button", { name: "Try again" }));
    expect(api.start_sync).toHaveBeenLastCalledWith("auto");
  });

  it("offers to reconnect", async () => {
    const api = startWith(failed("reconnect", "Notion no longer accepts the access."));
    const region = await panel();
    await userEvent.click(await region.findByRole("button", { name: "Reconnect to Notion" }));
    expect(api.start_sign_in).toHaveBeenCalled();
  });

  it("sends a pasted-token user to paste a new one", async () => {
    startWith(failed("paste_new_token", "Notion no longer accepts the token."));
    const region = await panel();
    await userEvent.click(await region.findByRole("button", { name: "Paste a new token" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  });

  it("explains a renewal that the sign-in service couldn't do", async () => {
    startWith(failed("service_unreachable", "Couldn't renew Notion access."));
    const region = await panel();
    expect(await region.findByText("Couldn't renew Notion access")).toBeInTheDocument();
    expect(region.getByText(/Error ID 5eed0001/)).toBeInTheDocument();
    expect(region.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("opens the mapping when the columns changed in Notion", async () => {
    const status = failed("schema_blocked", "Syncing can't start.", [
      {
        code: "required_missing",
        field: "end",
        property_id: "x",
        message: "The column “End Time” used for End time no longer exists in Notion.",
      },
    ]);
    startWith(status);
    const region = await panel();
    expect(
      await region.findByText(/“End Time” used for End time no longer exists/),
    ).toBeInTheDocument();
    await userEvent.click(region.getByRole("button", { name: "Open column mapping" }));
    expect(await screen.findByRole("heading", { name: "Column mapping" })).toBeInTheDocument();
  });

  it("shows when a sync couldn't start", async () => {
    startWith(neverSynced, {
      start_sync: () => failWith("not_ready", "Map your columns before syncing."),
    });
    const region = await panel();
    expect(await region.findByText("The sync couldn't start")).toBeInTheDocument();
    expect(region.getByText("Map your columns before syncing.")).toBeInTheDocument();
  });

  it("retries reading the status", async () => {
    const api = startWith(neverSynced, { get_sync_status: () => fail("Database locked") });
    const region = await panel();
    expect(await region.findByText("The sync status couldn't be read")).toBeInTheDocument();
    api.get_sync_status.mockImplementation(() => ok(synced));
    await userEvent.click(region.getByRole("button", { name: "Try again" }));
    expect(await region.findByText("7 added · 0 updated · 0 removed")).toBeInTheDocument();
  });
});

describe("the mass-removal safeguard", () => {
  const pending: SyncStatus = {
    ...synced,
    pending_removal: { count: 40, total: 60, found_at: "2026-10-22T10:00:00.000Z" },
    last_result: { ...fullSyncDone, pending_removal: 40 },
  };

  it("asks before removing, with the likely causes", async () => {
    startWith(pending);
    const question = await screen.findByRole("alert", { name: "Entries waiting to be removed" });
    expect(question).toHaveTextContent("The last full sync didn't find 40 of your 60 entries");
    expect(question).toHaveTextContent("no longer shared with Habit Tracker");
    expect(question).toHaveTextContent("a different Notion workspace");
    expect(question).toHaveTextContent("The data source has filters");
    expect(question).toHaveTextContent("Everything else from that sync is already copied.");
  });

  it("removes them when asked", async () => {
    const api = startWith(pending);
    const question = await screen.findByRole("alert", { name: "Entries waiting to be removed" });
    await userEvent.click(within(question).getByRole("button", { name: "Remove them" }));
    expect(api.resolve_pending_removal).toHaveBeenCalledWith(true);
    await waitFor(() => {
      expect(
        screen.queryByRole("alert", { name: "Entries waiting to be removed" }),
      ).not.toBeInTheDocument();
    });
  });

  it("keeps them when asked", async () => {
    const api = startWith({
      ...pending,
      pending_removal: { count: 60, total: 60, found_at: "2026-10-22T10:00:00.000Z" },
    });
    const question = await screen.findByRole("alert", { name: "Entries waiting to be removed" });
    expect(question).toHaveTextContent("The last full sync found none of your 60 entries");
    await userEvent.click(within(question).getByRole("button", { name: "Keep them" }));
    expect(api.resolve_pending_removal).toHaveBeenCalledWith(false);
  });

  it("shows why an answer failed", async () => {
    startWith(pending, {
      resolve_pending_removal: () => failWith("notion_error", "Wait for the current sync."),
    });
    const question = await screen.findByRole("alert", { name: "Entries waiting to be removed" });
    await userEvent.click(within(question).getByRole("button", { name: "Remove them" }));
    expect(await within(question).findByText("Wait for the current sync.")).toBeInTheDocument();
  });
});

describe("sync settings", () => {
  it("shows the sync times and runs a full sync", async () => {
    const api = startWith(synced);
    await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const section = within(await screen.findByRole("region", { name: "Sync" }));
    expect(section.getByText(/refreshes formula and rollup values/)).toBeInTheDocument();
    expect(section.queryByText("Never")).not.toBeInTheDocument();
    await userEvent.click(section.getByRole("button", { name: "Run full sync" }));
    expect(api.start_sync).toHaveBeenLastCalledWith("full");
  });

  it("queues a full sync behind a running quick sync", async () => {
    startWith({
      ...synced,
      running: {
        kind: "quick",
        phase: "fetching",
        pages_fetched: 0,
        added: 0,
        updated: 0,
        removed: 0,
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const section = within(await screen.findByRole("region", { name: "Sync" }));
    expect(section.getByText("Runs after the current sync.")).toBeInTheDocument();
  });

  it("says when a full sync is already running", async () => {
    startWith({
      ...synced,
      running: {
        kind: "full",
        phase: "fetching",
        pages_fetched: 3,
        added: 0,
        updated: 0,
        removed: 0,
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const section = within(await screen.findByRole("region", { name: "Sync" }));
    expect(section.getByRole("button", { name: "Full sync running…" })).toBeDisabled();
  });

  it("says when nothing has been synced", async () => {
    startWith(neverSynced);
    await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const section = within(await screen.findByRole("region", { name: "Sync" }));
    expect(section.getAllByText("Never")).toHaveLength(2);
  });
});
