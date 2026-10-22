import type { EChartsCoreOption } from "echarts/core";

import type { DayTotal, WeekTotal } from "../bridge/types";
import { formatDay, formatDuration, formatRange, formatShortDay, showHours } from "./format";

/** Colours from the app's CSS tokens, so charts follow light and dark mode. */
export interface ChartTheme {
  ink: string;
  muted: string;
  rule: string;
  surface: string;
  sunken: string;
  green: string;
  greenSoft: string;
  amber: string;
  fontDisplay: string;
  fontUi: string;
}

export function readTheme(element: Element = document.documentElement): ChartTheme {
  const style = getComputedStyle(element);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    ink: token("--ink", "#1a2320"),
    muted: token("--muted", "#5b6863"),
    rule: token("--rule", "#d5dcd8"),
    surface: token("--surface", "#ffffff"),
    sunken: token("--sunken", "#e9edeb"),
    green: token("--green", "#2f6f5e"),
    greenSoft: token("--green-soft", "#dcebe5"),
    amber: token("--amber", "#8a5a00"),
    fontDisplay: token("--font-display", "Bahnschrift, sans-serif"),
    fontUi: token("--font-ui", "Segoe UI, sans-serif"),
  };
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${String(c.charCodeAt(0))};`);
}

function valueAxis(theme: ChartTheme, hours: boolean) {
  return {
    type: "value",
    axisLabel: {
      color: theme.muted,
      fontFamily: theme.fontDisplay,
      formatter: (value: number) => (hours ? `${String(value / 60)} h` : `${String(value)} min`),
    },
    splitLine: { lineStyle: { color: theme.rule } },
    minInterval: hours ? 60 : 1,
  };
}

function base(theme: ChartTheme) {
  return {
    animationDuration: 300,
    textStyle: { fontFamily: theme.fontUi, color: theme.ink },
    grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: theme.surface,
      borderColor: theme.rule,
      textStyle: { color: theme.ink, fontFamily: theme.fontUi },
    },
  };
}

interface AxisParam {
  dataIndex: number;
}

function firstIndex(params: unknown): number {
  const list = (Array.isArray(params) ? params : [params]) as AxisParam[];
  return list[0]?.dataIndex ?? 0;
}

/** Daily totals: one bar per day. */
export function dailyOption(days: DayTotal[], theme: ChartTheme): EChartsCoreOption {
  const max = Math.max(0, ...days.map((d) => d.minutes));
  const hours = showHours(max);
  return {
    ...base(theme),
    aria: { enabled: true, decal: { show: false } },
    xAxis: {
      type: "category",
      data: days.map((d) => formatShortDay(d.date)),
      axisLabel: { color: theme.muted, fontFamily: theme.fontDisplay, hideOverlap: true },
      axisLine: { lineStyle: { color: theme.rule } },
      axisTick: { show: false },
    },
    yAxis: valueAxis(theme, hours),
    tooltip: {
      ...base(theme).tooltip,
      formatter: (params: unknown) => {
        const day = days[firstIndex(params)];
        if (!day) return "";
        const sessions = `${String(day.sessions)} ${day.sessions === 1 ? "session" : "sessions"}`;
        return `<strong>${escapeHtml(formatDay(day.date))}</strong><br/>${escapeHtml(
          formatDuration(day.minutes),
        )} · ${escapeHtml(sessions)}`;
      },
    },
    series: [
      {
        type: "bar",
        name: "Minutes",
        data: days.map((d) => Math.round(d.minutes * 100) / 100),
        itemStyle: { color: theme.green, borderRadius: [3, 3, 0, 0] },
        emphasis: { itemStyle: { color: theme.amber } },
        barMaxWidth: 28,
        cursor: "pointer",
      },
    ],
  };
}

/** Weekly totals with the 4-week rolling average as a line. */
export function weeklyOption(weeks: WeekTotal[], theme: ChartTheme): EChartsCoreOption {
  const max = Math.max(0, ...weeks.map((w) => Math.max(w.minutes, w.rolling_average ?? 0)));
  const hours = showHours(max);
  return {
    ...base(theme),
    aria: { enabled: true, decal: { show: false } },
    legend: {
      bottom: 0,
      textStyle: { color: theme.muted },
      data: ["Week total", "4-week average"],
    },
    grid: { left: 8, right: 8, top: 16, bottom: 32, containLabel: true },
    xAxis: {
      type: "category",
      data: weeks.map((w) => formatShortDay(w.start)),
      axisLabel: { color: theme.muted, fontFamily: theme.fontDisplay, hideOverlap: true },
      axisLine: { lineStyle: { color: theme.rule } },
      axisTick: { show: false },
    },
    yAxis: valueAxis(theme, hours),
    tooltip: {
      ...base(theme).tooltip,
      formatter: (params: unknown) => {
        const week = weeks[firstIndex(params)];
        if (!week) return "";
        const average =
          week.rolling_average === null
            ? ""
            : `<br/>4-week average: ${escapeHtml(formatDuration(week.rolling_average))}`;
        const partial = week.partial ? " (so far)" : "";
        return `<strong>${escapeHtml(formatRange(week.start, week.end))}</strong><br/>${escapeHtml(
          formatDuration(week.minutes),
        )}${partial}${average}`;
      },
    },
    series: [
      {
        type: "bar",
        name: "Week total",
        data: weeks.map((w) => ({
          value: Math.round(w.minutes * 100) / 100,
          itemStyle: w.partial
            ? { color: theme.greenSoft, borderColor: theme.green, borderWidth: 1 }
            : undefined,
        })),
        itemStyle: { color: theme.green, borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 28,
      },
      {
        type: "line",
        name: "4-week average",
        data: weeks.map((w) =>
          w.rolling_average === null ? null : Math.round(w.rolling_average * 100) / 100,
        ),
        smooth: false,
        symbol: "circle",
        symbolSize: 5,
        lineStyle: { color: theme.amber, width: 2 },
        itemStyle: { color: theme.amber },
        connectNulls: false,
      },
    ],
  };
}

/** The calendar heatmap: a GitHub-style year shaded by daily minutes. */
export function calendarOption(
  days: DayTotal[],
  first: string,
  last: string,
  maxMinutes: number,
  theme: ChartTheme,
  weekStart: number,
): EChartsCoreOption {
  const byDate = new Map(days.map((d) => [d.date, d]));
  return {
    animation: false,
    aria: { enabled: true, decal: { show: false } },
    textStyle: { fontFamily: theme.fontUi, color: theme.ink },
    tooltip: {
      backgroundColor: theme.surface,
      borderColor: theme.rule,
      textStyle: { color: theme.ink, fontFamily: theme.fontUi },
      formatter: (params: unknown) => {
        const value = (params as { value?: [string, number] }).value;
        const day = value ? byDate.get(value[0]) : undefined;
        if (!day) return "";
        const sessions = `${String(day.sessions)} ${day.sessions === 1 ? "session" : "sessions"}`;
        return `<strong>${escapeHtml(formatDay(day.date))}</strong><br/>${escapeHtml(
          formatDuration(day.minutes),
        )} · ${escapeHtml(sessions)}`;
      },
    },
    visualMap: {
      show: false,
      min: 0,
      max: Math.max(maxMinutes, 1),
      inRange: { color: [theme.greenSoft, theme.green] },
      outOfRange: { color: theme.sunken },
    },
    calendar: {
      range: [first, last],
      top: 24,
      left: 32,
      right: 8,
      bottom: 8,
      cellSize: ["auto", 13],
      firstDay: weekStart,
      itemStyle: { color: theme.sunken, borderColor: theme.surface, borderWidth: 2 },
      splitLine: { show: false },
      dayLabel: { color: theme.muted, fontSize: 10, nameMap: "en" },
      monthLabel: { color: theme.muted, fontSize: 11 },
      yearLabel: { show: false },
    },
    series: [
      {
        type: "heatmap",
        coordinateSystem: "calendar",
        // Days with no time aren't in the data, so they keep the plain cell colour: "nothing
        // logged" never looks like "a little".
        data: days.filter((d) => d.minutes > 0).map((d) => [d.date, Math.round(d.minutes)]),
        cursor: "pointer",
      },
    ],
  };
}
