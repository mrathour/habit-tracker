import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { resetBridgeForTests } from "./bridge/client";
import { clearNoticesForTests } from "./errors/notices";
import {
  appInfo,
  connectedNoDatabase,
  connectedWithDatabase,
  disconnected,
  fail,
  failWith,
  installFakeBridge,
  ok,
  pushBackendEvent,
  removeFakeBridge,
  twoDatabases,
} from "./test/fakeBridge";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
});

async function openSettings() {
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
}

describe("starting up", () => {
  it("reports ready to Python", async () => {
    const api = installFakeBridge();
    render(<App />);
    await screen.findByRole("heading", { name: "See where your working hours go" });
    await waitFor(() => {
      expect(api.ui_ready).toHaveBeenCalled();
    });
  });

  it("explains when it isn't running inside the app", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<App />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(screen.getByText("Open this inside Habit Tracker")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows when the connection can't be read, and retries", async () => {
    const api = installFakeBridge({ get_connection: () => fail("Database locked", "1d1d1d1d") });
    render(<App />);
    expect(await screen.findByText("The Notion connection couldn't be read")).toBeInTheDocument();
    expect(screen.getByText("Error ID 1d1d1d1d")).toBeInTheDocument();
    api.get_connection.mockImplementation(() => ok(disconnected));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("button", { name: "Connect to Notion" });
  });
});

describe("connecting with Notion sign-in", () => {
  it("waits for the browser, then moves on to choosing the work log", async () => {
    const api = installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Connect to Notion" }));
    expect(api.start_sign_in).toHaveBeenCalled();
    act(() => {
      pushBackendEvent({ name: "connect:waiting", payload: { timeout_s: 300 } });
    });
    expect(await screen.findByText("Finish connecting in your browser")).toBeInTheDocument();
    expect(screen.getByText(/5:00 left|4:59 left/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open Notion again" }));
    expect(api.start_sign_in).toHaveBeenCalledTimes(2);

    act(() => {
      pushBackendEvent({
        name: "connect:done",
        payload: { result: "connected", connection: connectedNoDatabase },
      });
    });
    expect(
      await screen.findByRole("heading", { name: "Choose your work log" }),
    ).toBeInTheDocument();
    expect(api.list_data_sources).toHaveBeenCalledWith(null);
    expect(screen.getAllByText("Mayank's Notion").length).toBeGreaterThan(0);
  });

  it("cancels from the app", async () => {
    const api = installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Connect to Notion" }));
    act(() => {
      pushBackendEvent({ name: "connect:waiting", payload: { timeout_s: 300 } });
    });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(api.cancel_sign_in).toHaveBeenCalled();
    act(() => {
      pushBackendEvent({ name: "connect:done", payload: { result: "cancelled" } });
    });
    expect(await screen.findByText("Sign-in stopped")).toBeInTheDocument();
  });

  it.each([
    ["access_denied", "Access wasn't allowed"],
    ["expired", "The sign-in expired"],
    ["timeout", "No answer from the browser"],
    ["notion_error", "Notion couldn't complete the sign-in"],
    ["error", "Connecting didn't finish"],
  ] as const)("explains the %s outcome and offers to try again", async (result, title) => {
    const api = installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Connect to Notion" }));
    act(() => {
      pushBackendEvent({ name: "connect:done", payload: { result } });
    });
    expect(await screen.findByText(title)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect again" }));
    expect(api.start_sign_in).toHaveBeenCalledTimes(2);
  });

  it("offers a token when the sign-in service can't be reached", async () => {
    installFakeBridge({
      start_sign_in: () => failWith("service_unreachable", "Couldn't start signing in."),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Connect to Notion" }));
    expect(await screen.findByText("The sign-in service can't be reached")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use a token instead" }));
    expect(screen.getByRole("heading", { name: "Connect with a token" })).toBeInTheDocument();
  });
});

describe("connecting with a pasted token", () => {
  it("checks the token, then moves on", async () => {
    const api = installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Use a token instead" }));
    await userEvent.click(screen.getByLabelText(/Personal access token/));
    const field = screen.getByLabelText("Token");
    expect(field).toHaveAttribute("type", "password");
    await userEvent.type(field, "ntn_pasted_token_value");
    await userEvent.click(screen.getByRole("button", { name: "Check and connect" }));
    expect(api.connect_with_token).toHaveBeenCalledWith("pat", "ntn_pasted_token_value");
    expect(
      await screen.findByRole("heading", { name: "Choose your work log" }),
    ).toBeInTheDocument();
  });

  it("shows Notion's rejection on the field and keeps nothing", async () => {
    installFakeBridge({
      connect_with_token: () => failWith("invalid_token", "Notion didn't accept that token."),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Use a token instead" }));
    await userEvent.type(screen.getByLabelText("Token"), "ntn_wrong");
    await userEvent.click(screen.getByRole("button", { name: "Check and connect" }));
    expect(await screen.findByText("Notion didn't accept that token.")).toBeInTheDocument();
    expect(screen.getByLabelText("Token")).toHaveAttribute("aria-invalid", "true");
  });

  it("reports being offline", async () => {
    installFakeBridge({ connect_with_token: () => failWith("offline", "You're offline.") });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Use a token instead" }));
    await userEvent.type(screen.getByLabelText("Token"), "ntn_x");
    await userEvent.click(screen.getByRole("button", { name: "Check and connect" }));
    expect(await screen.findByText("You're offline")).toBeInTheDocument();
  });

  it("can show the token while typing and go back", async () => {
    installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Use a token instead" }));
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByLabelText("Token")).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Connect to Notion" })).toBeInTheDocument();
  });

  it("opens Notion's developer portal from the instructions", async () => {
    const api = installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Use a token instead" }));
    await userEvent.click(screen.getByRole("button", { name: "Notion's developer portal" }));
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/developers");
  });
});

describe("choosing the work log", () => {
  it("chooses a database and shows it on the home screen", async () => {
    const api = installFakeBridge({ get_connection: () => ok(connectedNoDatabase) });
    render(<App />);
    const list = await screen.findByRole("list", { name: "Databases" });
    await userEvent.click(within(list).getByLabelText(/Work Log \(test\)/));
    await userEvent.click(screen.getByRole("button", { name: "Use this database" }));
    expect(api.choose_data_source).toHaveBeenCalledWith("db-1", "ds-1", false);
    expect(await screen.findByRole("heading", { name: "Work Log (test)" })).toBeInTheDocument();
  });

  it("lets you pick among a database's data sources", async () => {
    const api = installFakeBridge({ get_connection: () => ok(connectedNoDatabase) });
    render(<App />);
    const list = await screen.findByRole("list", { name: "Databases" });
    await userEvent.click(within(list).getByLabelText(/Reading/));
    const sources = screen.getByRole("list", { name: "Data sources in Reading" });
    await userEvent.click(within(sources).getByLabelText("Articles"));
    await userEvent.click(screen.getByRole("button", { name: "Use this database" }));
    expect(api.choose_data_source).toHaveBeenCalledWith("db-2", "ds-2b", false);
  });

  it("explains how to share when nothing is shared", async () => {
    const api = installFakeBridge({
      get_connection: () => ok(connectedNoDatabase),
      list_data_sources: () =>
        ok({ groups: [], next_cursor: null, sharing_help_url: twoDatabases.sharing_help_url }),
    });
    render(<App />);
    expect(
      await screen.findByText("No databases are shared with Habit Tracker yet"),
    ).toBeInTheDocument();
    expect(screen.getByText("Habit Tracker", { selector: "strong" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(api.list_data_sources).toHaveBeenCalledTimes(2);
    await userEvent.click(screen.getByRole("button", { name: "Connect again and choose pages" }));
    expect(api.start_sign_in).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "How sharing works" }));
    expect(api.open_external).toHaveBeenCalled();
  });

  it("gives personal-token advice when nothing is visible", async () => {
    installFakeBridge({
      get_connection: () => ok({ ...connectedNoDatabase, auth_kind: "pat" }),
      list_data_sources: () =>
        ok({ groups: [], next_cursor: null, sharing_help_url: twoDatabases.sharing_help_url }),
    });
    render(<App />);
    expect(await screen.findByText(/sees every database you can open/)).toBeInTheDocument();
  });

  it("loads more databases", async () => {
    const api = installFakeBridge({
      get_connection: () => ok(connectedNoDatabase),
      list_data_sources: vi.fn((cursor: string | null) =>
        ok(
          cursor === null
            ? { ...twoDatabases, groups: twoDatabases.groups.slice(0, 1), next_cursor: "1" }
            : { ...twoDatabases, groups: twoDatabases.groups.slice(1), next_cursor: null },
        ),
      ),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Show more databases" }));
    expect(api.list_data_sources).toHaveBeenLastCalledWith("1");
    expect(await screen.findByLabelText(/Reading/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more databases" })).not.toBeInTheDocument();
  });

  it("asks to reconnect when Notion refused the token", async () => {
    const api = installFakeBridge({
      get_connection: () => ok(connectedNoDatabase),
      list_data_sources: () =>
        failWith("reconnect", "Notion no longer accepts Habit Tracker's access."),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Reconnect to Notion" }));
    expect(api.start_sign_in).toHaveBeenCalled();
  });

  it("sends a pasted-token user to paste a new one", async () => {
    installFakeBridge({
      get_connection: () => ok({ ...connectedNoDatabase, auth_kind: "pat" }),
      list_data_sources: () => failWith("paste_new_token", "Notion no longer accepts the token."),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Paste a new token" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  });

  it("confirms before switching away from a database with entries", async () => {
    const api = installFakeBridge({
      get_connection: () => ok(connectedWithDatabase),
      choose_data_source: vi.fn((_db: string, _ds: string, confirm: boolean) =>
        confirm
          ? ok({
              ...connectedWithDatabase,
              database_id: "db-2",
              data_source_id: "ds-2a",
              database_title: "Reading",
            })
          : failWith(
              "confirm_replace",
              "Switching removes the 12 entries copied from Work Log (test).",
            ),
      ),
    });
    render(<App />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Choose a different database" }),
    );
    await userEvent.click(await screen.findByLabelText(/Reading/));
    await userEvent.click(screen.getByRole("button", { name: "Use this database" }));
    const dialog = await screen.findByRole("dialog", { name: "Switch to a different database?" });
    expect(within(dialog).getByText(/removes the 12 entries/)).toBeInTheDocument();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Switch and remove entries" }),
    );
    expect(api.choose_data_source).toHaveBeenLastCalledWith("db-2", "ds-2a", true);
    expect(await screen.findByRole("heading", { name: "Reading" })).toBeInTheDocument();
  });

  it("can keep the current database from the confirmation", async () => {
    installFakeBridge({
      get_connection: () => ok(connectedWithDatabase),
      choose_data_source: () => failWith("confirm_replace", "Switching removes the 3 entries."),
    });
    render(<App />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Choose a different database" }),
    );
    await userEvent.click(await screen.findByLabelText(/Reading/));
    await userEvent.click(screen.getByRole("button", { name: "Use this database" }));
    await userEvent.click(await screen.findByRole("button", { name: "Keep the current database" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("heading", { name: "Work Log (test)" })).toBeInTheDocument();
  });
});

describe("settings and disconnecting", () => {
  it("shows the connection and disconnects, keeping local data", async () => {
    const api = installFakeBridge({ get_connection: () => ok(connectedWithDatabase) });
    render(<App />);
    await openSettings();
    expect(screen.getByText("Connected with Notion sign-in")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    const dialog = screen.getByRole("dialog", { name: "Disconnect from Notion?" });
    expect(within(dialog).getByLabelText(/Keep them/)).toBeChecked();
    api.get_connection.mockImplementation(() => ok(disconnected));
    await userEvent.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    expect(api.logout).toHaveBeenCalledWith(false);
    expect(await screen.findByText(/Notion cancelled Habit Tracker's access/)).toBeInTheDocument();
    expect(screen.getByText(/copied entries are kept/)).toBeInTheDocument();
  });

  it("can delete local data when disconnecting", async () => {
    const api = installFakeBridge({ get_connection: () => ok(connectedWithDatabase) });
    render(<App />);
    await openSettings();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await userEvent.click(screen.getByLabelText(/Delete them/));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect" }),
    );
    expect(api.logout).toHaveBeenCalledWith(true);
    expect(await screen.findByText(/copied entries were deleted/)).toBeInTheDocument();
  });

  it("says when Notion's access couldn't be revoked", async () => {
    installFakeBridge({
      get_connection: () => ok(connectedWithDatabase),
      logout: () =>
        ok({
          kind: "oauth",
          revoked: false,
          revoke_error: "service down",
          cleared_local_data: false,
        }),
    });
    render(<App />);
    await openSettings();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect" }),
    );
    expect(await screen.findByText(/couldn't be cancelled \(service down\)/)).toBeInTheDocument();
  });

  it("explains how to revoke a pasted token", async () => {
    installFakeBridge({
      get_connection: () =>
        ok({
          ...connectedWithDatabase,
          auth_kind: "pat",
          workspace_name: null,
          account_name: "Mayank",
        }),
      logout: () =>
        ok({ kind: "pat", revoked: null, revoke_error: null, cleared_local_data: false }),
    });
    render(<App />);
    await openSettings();
    expect(screen.getAllByText("Mayank's personal access token").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect" }),
    );
    expect(await screen.findByText(/revoke it under Personal access tokens/)).toBeInTheDocument();
  });

  it("closes the dialog with Escape", async () => {
    installFakeBridge({ get_connection: () => ok(connectedWithDatabase) });
    render(<App />);
    await openSettings();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("warns that a token replaces the current connection", async () => {
    installFakeBridge({ get_connection: () => ok(connectedWithDatabase) });
    render(<App />);
    await openSettings();
    expect(
      screen.getByText(/replaces the current connection to Mayank's Notion/),
    ).toBeInTheDocument();
  });

  it("hides diagnostics unless Python enables them", async () => {
    installFakeBridge({
      get_app_info: () => ok({ ...appInfo, mode: "normal", diagnostics: false }),
    });
    render(<App />);
    await openSettings();
    expect(await screen.findByText("About this copy")).toBeInTheDocument();
    expect(screen.queryByText("Diagnostics")).not.toBeInTheDocument();
  });

  it("opens the log folder", async () => {
    const api = installFakeBridge();
    render(<App />);
    await openSettings();
    await userEvent.click(await screen.findByRole("button", { name: "Open log folder" }));
    expect(api.open_log_folder).toHaveBeenCalled();
  });
});

describe("diagnostics (dev mode)", () => {
  it("follows the bridge check's progress events", async () => {
    const api = installFakeBridge();
    render(<App />);
    await openSettings();
    const start = await screen.findByRole("button", { name: "Run bridge check" });
    await userEvent.click(start);
    expect(api.run_bridge_check).toHaveBeenCalledWith(5);
    act(() => {
      for (let step = 1; step <= 5; step++) {
        pushBackendEvent({
          name: "bridge-check:progress",
          payload: { run_id: "run-1", step, steps: 5, thread: "bridge-check-run-1" },
        });
      }
      pushBackendEvent({
        name: "bridge-check:done",
        payload: { run_id: "run-1", elapsed_ms: 2000 },
      });
    });
    expect(await screen.findByText("Received all 5 steps in 2000 ms")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("ignores events from another run", async () => {
    installFakeBridge();
    render(<App />);
    await openSettings();
    await userEvent.click(await screen.findByRole("button", { name: "Run bridge check" }));
    act(() => {
      pushBackendEvent({
        name: "bridge-check:progress",
        payload: { run_id: "someone-else", step: 1, steps: 5, thread: "t" },
      });
    });
    expect(screen.getByText(/No events yet/)).toBeInTheDocument();
  });

  it("shows Python call failures as banners", async () => {
    installFakeBridge({ raise_test_error: () => fail("Something went wrong.", "beef0001") });
    render(<App />);
    await openSettings();
    await userEvent.click(await screen.findByRole("button", { name: "Error in a Python call" }));
    expect(await screen.findByText("A Python call failed")).toBeInTheDocument();
    expect(screen.getByText("Error ID beef0001")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("A Python call failed")).not.toBeInTheDocument();
  });
});
