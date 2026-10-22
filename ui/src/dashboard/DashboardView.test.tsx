import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { resetBridgeForTests } from "../bridge/client";
import type { Dashboard, PythonApi } from "../bridge/types";
import { clearNoticesForTests } from "../errors/notices";
import { charts } from "../test/chartRegistry";
import {
  connectedWithDatabase,
  dashboard,
  dayDetail,
  emptyDashboard,
  fail,
  failWith,
  fullSyncDone,
  installFakeBridge,
  neverSynced,
  ok,
  pushBackendEvent,
  removeFakeBridge,
  synced,
} from "../test/fakeBridge";

const scrollIntoView = vi.fn();

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
  scrollIntoView.mockClear();
  Element.prototype.scrollIntoView = scrollIntoView;
});

function first<T>(items: readonly T[]): T {
  const item = items[0];
  if (item === undefined) throw new Error("empty list");
  return item;
}

function startWith(data: Dashboard, overrides: Partial<PythonApi> = {}) {
  const api = installFakeBridge({
    get_connection: () => ok(connectedWithDatabase),
    get_sync_status: () => ok(synced),
    start_sync: () => ok(synced),
    get_dashboard: () => ok(data),
    ...overrides,
  });
  render(<App />);
  return api;
}

const board = async () => within(await screen.findByRole("region", { name: "Dashboard" }));

describe("dashboard states", () => {
  it("waits for the first sync", async () => {
    startWith(emptyDashboard, { get_sync_status: () => ok(neverSynced) });
    expect(
      await (await board()).findByText("Your charts appear after the first sync"),
    ).toBeInTheDocument();
  });

  it("says when the first sync is running", async () => {
    const running = {
      ...neverSynced,
      running: {
        kind: "full" as const,
        phase: "fetching" as const,
        pages_fetched: 3,
        added: 3,
        updated: 0,
        removed: 0,
      },
    };
    startWith(emptyDashboard, {
      get_sync_status: () => ok(running),
      start_sync: () => ok(running),
    });
    expect(
      await (await board()).findByText(/Your entries are being copied now/),
    ).toBeInTheDocument();
  });

  it("shows a loading state", async () => {
    startWith(dashboard, { get_dashboard: () => new Promise(() => undefined) });
    const region = await screen.findByRole("region", { name: "Dashboard" });
    expect(region).toHaveAttribute("aria-busy", "true");
  });

  it("retries after an error", async () => {
    const api = startWith(dashboard, { get_dashboard: () => fail("Database locked", "d00d0001") });
    const region = await board();
    expect(await region.findByText("The dashboard couldn't be loaded")).toBeInTheDocument();
    expect(region.getByText("Error ID d00d0001")).toBeInTheDocument();
    api.get_dashboard.mockImplementation(() => ok(dashboard));
    await userEvent.click(region.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Current streak")).toBeInTheDocument();
  });

  it("says when no entry can be charted", async () => {
    startWith({ ...emptyDashboard, entries: 4, excluded: 4, flagged: 4 });
    const region = await board();
    expect(await region.findByText("None of your entries can be charted yet")).toBeInTheDocument();
    await userEvent.click(region.getByRole("button", { name: "See the entries with issues" }));
  });
});

describe("the figures", () => {
  it("shows streaks, the range total and the flagged count", async () => {
    startWith(dashboard);
    const region = await board();
    expect(await region.findByText("Current streak")).toBeInTheDocument();
    expect(region.getAllByText("3 days")).toHaveLength(2);
    expect(region.getByText(/^Since /)).toBeInTheDocument();
    expect(
      region.getByText("2 entries are left out of the charts", { exact: false }),
    ).toBeInTheDocument();
    expect(region.getByText("Entries with issues")).toBeInTheDocument();
    await screen.findByText("Entries with issues (5)");
    await userEvent.click(first(region.getAllByRole("button", { name: "See them" })));
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("explains today's grace for the current streak", async () => {
    startWith({
      ...dashboard,
      streaks: { ...dashboard.streaks, today_counts: false, threshold_minutes: 30 },
    });
    expect(
      await (await board()).findByText(/Through yesterday. Log 30 min today to keep it going/),
    ).toBeInTheDocument();
  });

  it("draws the three charts", async () => {
    startWith(dashboard);
    await (await board()).findByText("Daily totals");
    expect(screen.getByRole("img", { name: /^Daily totals from/ })).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /^Weekly totals for the last 3 weeks/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /^Calendar of daily time/ })).toBeInTheDocument();
  });

  it("says when a range has no time logged", async () => {
    startWith({ ...dashboard, daily: { ...emptyDashboard.daily } });
    expect(await (await board()).findByText("No time logged in this range.")).toBeInTheDocument();
  });
});

describe("ranges", () => {
  it("changes the daily range", async () => {
    const api = startWith(dashboard);
    const region = await board();
    await userEvent.click(await region.findByRole("button", { name: "7 days" }));
    await waitFor(() => {
      expect(api.get_dashboard).toHaveBeenLastCalledWith(
        expect.objectContaining({ range: { days: 7 }, weeks: 26, year: null }),
      );
    });
  });

  it("shows a custom range", async () => {
    const api = startWith(dashboard);
    const region = await board();
    await userEvent.click(await region.findByRole("button", { name: "Custom" }));
    const from = region.getByLabelText("From");
    await userEvent.clear(from);
    await userEvent.type(from, "2026-01-01");
    await userEvent.click(region.getByRole("button", { name: "Show" }));
    await waitFor(() => {
      expect(api.get_dashboard).toHaveBeenLastCalledWith(
        expect.objectContaining({ range: { from: "2026-01-01", to: "2026-10-22" } }),
      );
    });
  });

  it("changes the weeks and the calendar year", async () => {
    const api = startWith(dashboard);
    const region = await board();
    await userEvent.selectOptions(await region.findByLabelText("Weeks shown"), "52 weeks");
    await waitFor(() => {
      expect(api.get_dashboard).toHaveBeenLastCalledWith(expect.objectContaining({ weeks: 52 }));
    });
    await userEvent.selectOptions(region.getByLabelText("Year shown"), "2025");
    await waitFor(() => {
      expect(api.get_dashboard).toHaveBeenLastCalledWith(expect.objectContaining({ year: 2025 }));
    });
  });

  it("sends this computer's time zone", async () => {
    const api = startWith(dashboard);
    await (await board()).findByText("Daily totals");
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(api.get_dashboard).toHaveBeenCalledWith(expect.objectContaining({ time_zone: zone }));
  });

  it("refreshes when a sync finishes", async () => {
    const api = startWith(dashboard);
    await (await board()).findByText("Daily totals");
    const calls = api.get_dashboard.mock.calls.length;
    act(() => {
      pushBackendEvent({
        name: "sync:status",
        payload: {
          ...synced,
          last_result: { ...fullSyncDone, finished_at: "2026-10-22T11:00:00.000Z" },
        },
      });
    });
    await waitFor(() => {
      expect(api.get_dashboard.mock.calls.length).toBeGreaterThan(calls);
    });
  });
});

describe("tables and the day detail", () => {
  it("shows a chart as a table, and a day's sessions", async () => {
    const api = startWith(dashboard);
    const region = await board();
    const daily = within(await region.findByRole("region", { name: "Daily totals" }));
    await userEvent.click(daily.getByRole("button", { name: "Show as table" }));
    const table = daily.getByRole("table", { name: "Daily totals" });
    const firstDay = first(within(table).getAllByRole("button"));
    await userEvent.click(firstDay);
    expect(api.get_day_detail).toHaveBeenCalledWith(
      Intl.DateTimeFormat().resolvedOptions().timeZone,
      "2026-10-22",
    );
    const dialog = within(await screen.findByRole("dialog"));
    expect(await dialog.findByText("counted from 3 sessions")).toBeInTheDocument();
    expect(dialog.getAllByText("2 h")).toHaveLength(2); // the day's total and p3's length
    expect(dialog.getByText("Write")).toBeInTheDocument();
    expect(dialog.getByText("Untitled")).toBeInTheDocument();
    expect(dialog.getByText(/2 sessions overlap another/)).toBeInTheDocument();
    expect(dialog.getByText(/Overlapping time is counted once/)).toBeInTheDocument();
    expect(dialog.getByText("Overlaps #2 Review by 30 min.")).toBeInTheDocument();
    expect(
      dialog.getByText(/Crosses midnight: split between the days it covers/),
    ).toBeInTheDocument();
    await userEvent.click(first(dialog.getAllByRole("button", { name: "Open in Notion" })));
    expect(api.open_external).toHaveBeenCalledWith("https://www.notion.so/p1");
    await userEvent.click(dialog.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens a day from the charts", async () => {
    const api = startWith(dashboard);
    await (await board()).findByText("Daily totals");
    const daily = [...charts.entries()].find(([label]) => label.startsWith("Daily totals"));
    act(() => {
      daily?.[1].onClick?.({ dataIndex: 29, value: 89 });
    });
    await screen.findByRole("dialog");
    expect(api.get_day_detail).toHaveBeenLastCalledWith(expect.any(String), "2026-10-22");
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }),
    );
    const calendar = [...charts.entries()].find(([label]) => label.startsWith("Calendar"));
    act(() => {
      calendar?.[1].onClick?.({ dataIndex: 0, value: ["2026-10-20", 62] });
    });
    await screen.findByRole("dialog");
    expect(api.get_day_detail).toHaveBeenLastCalledWith(expect.any(String), "2026-10-20");
  });

  it("explains the sum rule and the start-date rule", async () => {
    startWith(dashboard, {
      get_day_detail: () =>
        ok({
          ...dayDetail,
          preferences: {
            ...dayDetail.preferences,
            overlap_rule: "sum",
            midnight_rule: "start_date",
          },
        }),
    });
    const daily = within(await (await board()).findByRole("region", { name: "Daily totals" }));
    await userEvent.click(daily.getByRole("button", { name: "Show as table" }));
    await userEvent.click(first(within(daily.getByRole("table")).getAllByRole("button")));
    const dialog = within(await screen.findByRole("dialog"));
    expect(await dialog.findByText(/overlapping time counts more than once/)).toBeInTheDocument();
    expect(dialog.getByText(/counted on its start date/)).toBeInTheDocument();
  });

  it("handles an empty day and a failed load", async () => {
    const api = startWith(dashboard, {
      get_day_detail: () => failWith("invalid_request", "The day isn't a valid date."),
    });
    const daily = within(await (await board()).findByRole("region", { name: "Daily totals" }));
    await userEvent.click(daily.getByRole("button", { name: "Show as table" }));
    await userEvent.click(first(within(daily.getByRole("table")).getAllByRole("button")));
    const dialog = within(await screen.findByRole("dialog"));
    expect(await dialog.findByText("The day isn't a valid date.")).toBeInTheDocument();
    api.get_day_detail.mockImplementation(() => ok({ ...dayDetail, minutes: 0, sessions: [] }));
    await userEvent.click(dialog.getByRole("button", { name: "Try again" }));
    expect(await dialog.findByText("No time was logged on this day.")).toBeInTheDocument();
  });
});

describe("dashboard settings", () => {
  async function openSettings() {
    await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
    return within(await screen.findByRole("region", { name: "Dashboard" }));
  }

  it("saves each preference", async () => {
    const api = startWith(dashboard);
    const section = await openSettings();
    await userEvent.selectOptions(await section.findByLabelText("Weeks start on"), "Sunday");
    expect(api.set_preferences).toHaveBeenLastCalledWith({ week_start: "sunday" });
    await userEvent.click(section.getByLabelText(/Count the whole session on its start date/));
    expect(api.set_preferences).toHaveBeenLastCalledWith({ midnight_rule: "start_date" });
    await userEvent.click(section.getByLabelText(/Add every session's full time/));
    expect(api.set_preferences).toHaveBeenLastCalledWith({ overlap_rule: "sum" });
    const threshold = section.getByLabelText("Streak day threshold (minutes)");
    await userEvent.clear(threshold);
    await userEvent.type(threshold, "30");
    await userEvent.click(section.getByRole("button", { name: "Save" }));
    expect(api.set_preferences).toHaveBeenLastCalledWith({ streak_threshold_minutes: 30 });
    expect(await section.findByText(/Streak threshold saved/)).toBeInTheDocument();
  });

  it("refuses a bad threshold before sending it", async () => {
    const api = startWith(dashboard);
    const section = await openSettings();
    const threshold = await section.findByLabelText("Streak day threshold (minutes)");
    await userEvent.clear(threshold);
    await userEvent.type(threshold, "2000");
    await userEvent.click(section.getByRole("button", { name: "Save" }));
    expect(
      section.getByText("Enter a whole number of minutes from 0 to 1440."),
    ).toBeInTheDocument();
    expect(api.set_preferences).not.toHaveBeenCalled();
  });

  it("shows when saving fails", async () => {
    startWith(dashboard, {
      set_preferences: () => failWith("invalid_preference", "Choose a day of the week."),
    });
    const section = await openSettings();
    await userEvent.selectOptions(await section.findByLabelText("Weeks start on"), "Friday");
    expect(await section.findByText("Choose a day of the week.")).toBeInTheDocument();
  });

  it("retries loading the preferences", async () => {
    const api = startWith(dashboard, { get_preferences: () => fail("Locked") });
    const section = await openSettings();
    expect(await section.findByText("Locked")).toBeInTheDocument();
    api.get_preferences.mockImplementation(() => ok(dayDetail.preferences));
    await userEvent.click(section.getByRole("button", { name: "Try again" }));
    expect(await section.findByLabelText("Weeks start on")).toBeInTheDocument();
  });
});
