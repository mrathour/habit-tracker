import { useCallback, useEffect, useState } from "react";

import { callPython } from "../bridge/client";
import type { DailyRange, Dashboard, DashboardRequest } from "../bridge/types";
import { problemFrom, type Problem } from "../connection/problems";
import { readTheme, type ChartTheme } from "./options";
import { browserTimeZone } from "./format";

export type DashboardLoad =
  | { status: "loading" }
  | { status: "ready"; data: Dashboard; refreshing: boolean }
  | { status: "error"; problem: Problem };

export interface DashboardView {
  range: DailyRange;
  weeks: DashboardRequest["weeks"];
  year: number | null;
}

const INITIAL_VIEW: DashboardView = { range: { days: 30 }, weeks: 26, year: null };

/**
 * The dashboard's figures for the chosen ranges, in this computer's time zone. Fetched again
 * whenever a range changes or `refreshKey` does (a sync finished, preferences changed).
 */
export function useDashboard(refreshKey: string) {
  const [view, setView] = useState<DashboardView>(INITIAL_VIEW);
  const [attempt, setAttempt] = useState(0);
  // The latest answer, tagged with the request it answers: an older answer stays on screen
  // (marked as refreshing) until the new one arrives, so the charts never flash empty.
  const [result, setResult] = useState<
    { key: string; data: Dashboard } | { key: string; problem: Problem } | null
  >(null);
  const key = JSON.stringify([view, refreshKey, attempt]);

  useEffect(() => {
    let current = true;
    callPython("get_dashboard", {
      time_zone: browserTimeZone(),
      range: view.range,
      weeks: view.weeks,
      year: view.year,
    })
      .then((data) => {
        if (current) setResult({ key, data });
      })
      .catch((error: unknown) => {
        if (current) setResult({ key, problem: problemFrom(error) });
      });
    return () => {
      current = false;
    };
  }, [key, view]);

  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);

  let load: DashboardLoad;
  if (result === null) load = { status: "loading" };
  else if ("data" in result)
    load = { status: "ready", data: result.data, refreshing: result.key !== key };
  else
    load =
      result.key === key ? { status: "error", problem: result.problem } : { status: "loading" };

  return { view, setView, load, retry };
}

/** Chart colours from the CSS tokens, re-read when Windows switches light and dark. */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(() => readTheme());
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      setTheme(readTheme());
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);
  return theme;
}
