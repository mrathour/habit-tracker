import { describe, expect, it } from "vitest";

import type { DayTotal, WeekTotal } from "../bridge/types";
import { formatDuration, showHours } from "./format";
import { calendarOption, type ChartTheme, dailyOption, weeklyOption } from "./options";

const theme: ChartTheme = {
  ink: "#111",
  muted: "#666",
  rule: "#ddd",
  surface: "#fff",
  sunken: "#eee",
  green: "#2f6f5e",
  greenSoft: "#dcebe5",
  amber: "#8a5a00",
  fontDisplay: "Bahnschrift",
  fontUi: "Segoe UI",
};

type Option = Record<string, unknown> & {
  series: { data: unknown[]; type: string }[];
  tooltip: { formatter: (params: unknown) => string };
};

const days: DayTotal[] = [
  { date: "2026-10-20", minutes: 90, sessions: 2 },
  { date: "2026-10-21", minutes: 0, sessions: 0 },
  { date: "2026-10-22", minutes: 30.456, sessions: 1 },
];

describe("durations", () => {
  it("reads as minutes, then hours and minutes", () => {
    expect(formatDuration(0.4)).toBe("0 min");
    expect(formatDuration(45)).toBe("45 min");
    expect(formatDuration(90)).toBe("1 h 30 min");
    expect(formatDuration(120)).toBe("2 h");
    expect(formatDuration(1439.6)).toBe("24 h");
  });

  it("switches the axis to hours past two hours", () => {
    expect(showHours(120)).toBe(false);
    expect(showHours(121)).toBe(true);
  });
});

describe("daily chart", () => {
  it("has one bar per day, rounded", () => {
    const option = dailyOption(days, theme) as Option;
    expect(option.series[0]?.data).toEqual([90, 0, 30.46]);
  });

  it("explains a day in its tooltip", () => {
    const option = dailyOption(days, theme) as Option;
    const text = option.tooltip.formatter([{ dataIndex: 0 }]);
    expect(text).toContain("1 h 30 min");
    expect(text).toContain("2 sessions");
  });

  it("labels the axis in hours for long days", () => {
    const option = dailyOption([{ date: "2026-10-20", minutes: 300, sessions: 1 }], theme) as {
      yAxis: { axisLabel: { formatter: (value: number) => string } };
    };
    expect(option.yAxis.axisLabel.formatter(180)).toBe("3 h");
  });
});

describe("weekly chart", () => {
  const weeks: WeekTotal[] = [
    { start: "2026-10-05", end: "2026-10-11", minutes: 90, rolling_average: null, partial: false },
    { start: "2026-10-12", end: "2026-10-18", minutes: 120, rolling_average: 105, partial: false },
    { start: "2026-10-19", end: "2026-10-25", minutes: 30, rolling_average: 80, partial: true },
  ];

  it("draws totals and the rolling average, with gaps before the data", () => {
    const option = weeklyOption(weeks, theme) as Option;
    expect(option.series.map((s) => s.type)).toEqual(["bar", "line"]);
    expect(option.series[1]?.data).toEqual([null, 105, 80]);
  });

  it("marks the current week as so far", () => {
    const option = weeklyOption(weeks, theme) as Option;
    expect(option.tooltip.formatter([{ dataIndex: 2 }])).toContain("(so far)");
    expect(option.tooltip.formatter([{ dataIndex: 1 }])).toContain("4-week average: 1 h 45 min");
  });
});

describe("calendar", () => {
  it("shades only days with time, and starts weeks on the chosen day", () => {
    const option = calendarOption(days, "2025-10-23", "2026-10-22", 90, theme, 0) as Option & {
      calendar: { range: string[]; firstDay: number };
    };
    expect(option.series[0]?.data).toEqual([
      ["2026-10-20", 90],
      ["2026-10-22", 30],
    ]);
    expect(option.calendar.range).toEqual(["2025-10-23", "2026-10-22"]);
    expect(option.calendar.firstDay).toBe(0);
  });

  it("escapes text in tooltips", () => {
    const option = calendarOption(days, "2026-10-20", "2026-10-22", 90, theme, 1) as Option;
    const text = option.tooltip.formatter({ value: ["2026-10-20", 90] });
    expect(text).toContain("1 h 30 min");
    expect(text).not.toContain("<script");
  });
});
