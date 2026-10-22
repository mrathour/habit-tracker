import { describe, expect, it } from "vitest";

import { rawLogColumns, rawLogPage } from "../test/rawLogFixtures";
import { activeChips, hasFilters, parentLabel, removeChip, requestFilters } from "./filters";
import { extraText, formatMinutes } from "./format";

describe("requestFilters", () => {
  it("drops empty parts", () => {
    expect(
      requestFilters({
        search: "  ",
        date_from: null,
        parents: [],
        issue_codes: [],
        overlaps: false,
        extra: { notes: { op: "contains", value: " " }, mood: { op: "any_of", values: [] } },
      }),
    ).toEqual({ filters: {}, problems: {} });
  });

  it("trims and keeps what is set", () => {
    expect(
      requestFilters({
        search: " docs ",
        duration_min: 0,
        extra: { bill: { op: "is", value: false } },
      }).filters,
    ).toEqual({ search: "docs", duration_min: 0, extra: { bill: { op: "is", value: false } } });
  });

  it("holds back contradictory ranges with a reason", () => {
    const { filters, problems } = requestFilters({
      date_from: "2026-10-22",
      date_to: "2026-10-01",
      duration_min: 10,
      duration_max: 5,
      extra: {
        score: { op: "range", min: 5, max: 1 },
        due: { op: "dates", from: "2026-10-22", to: "2026-10-01" },
      },
    });
    expect(filters).toEqual({});
    expect(problems).toEqual({
      date: "The date range ends before it starts.",
      duration: "The longest duration is shorter than the shortest.",
      "extra:score": "The highest value is below the lowest.",
      "extra:due": "The date range ends before it starts.",
    });
  });

  it("refuses negative durations", () => {
    expect(requestFilters({ duration_max: -1 }).problems).toEqual({
      duration: "Durations can't be negative.",
    });
  });

  it("prefers 'no parent' over chosen parents", () => {
    expect(requestFilters({ no_parent: true, parents: ["t1"] }).filters).toEqual({
      no_parent: true,
    });
  });

  it("knows when anything is filtered", () => {
    expect(hasFilters({})).toBe(false);
    expect(hasFilters({ search: " " })).toBe(false);
    expect(hasFilters({ overlaps: true })).toBe(true);
  });
});

describe("chips", () => {
  const filters = {
    search: "docs",
    date_from: "2026-10-01",
    parents: ["t1"],
    duration_max: 90,
    issues: "any" as const,
    issue_codes: ["missing_time" as const],
    overlaps: true,
    extra: { mood: { op: "any_of" as const, values: ["Focused", "Tired"] } },
  };

  it("describe every active filter", () => {
    expect(activeChips(filters, rawLogColumns, rawLogPage.parents).map((c) => c.label)).toEqual([
      "Task name contains “docs”",
      "Started from 1 Oct 2026",
      "Parent task: Page t1",
      "Duration up to 90 min",
      "Has issues",
      "Missing time",
      "Overlaps another session",
      "Mood is Focused or Tired",
    ]);
  });

  it("remove exactly their part", () => {
    expect(removeChip(filters, "extra:mood").extra).toEqual({});
    expect(removeChip(filters, "date")).not.toHaveProperty("date_from");
    expect(removeChip({ no_parent: true }, "parents")).toEqual({});
    expect(removeChip(filters, "overlaps")).not.toHaveProperty("overlaps");
  });
});

describe("formatting", () => {
  it("labels parent pages by ID and their newest entry", () => {
    expect(
      parentLabel({
        page_id: "3f2a91c0-1111-2222-3333-444455556666",
        url: "",
        entries: 3,
        latest_task_name: "Write docs",
      }),
    ).toBe("Page 3f2a91c0 · latest: Write docs");
  });

  it("writes minutes the way validation does", () => {
    expect(formatMinutes(123)).toBe("123 min");
    expect(formatMinutes(2.54)).toBe("2.5 min");
  });

  it("formats extra dates in local time", () => {
    const text = extraText(
      {
        text: "",
        start: { utc: "2026-10-25T04:00:00.000Z", date: "2026-10-25", has_time: true },
        end: { utc: null, date: "2026-10-26", has_time: false },
      },
      "Asia/Kolkata",
      { locale: "en-GB" },
    );
    expect(text).toBe("25 Oct 2026, 9:30 → 26 Oct 2026");
    expect(extraText(null, "UTC")).toBeNull();
    expect(extraText({ text: "Focused" }, "UTC")).toBe("Focused");
  });
});
