import { useEffect, useState } from "react";

import { callPython } from "../bridge/client";
import type { Preferences, Weekday } from "../bridge/types";
import { problemFrom, type Problem } from "../connection/problems";

type Load =
  | { status: "loading" }
  | { status: "ready"; preferences: Preferences }
  | { status: "error"; problem: Problem };

const WEEKDAYS: { value: Weekday; label: string }[] = [
  { value: "monday", label: "Monday" },
  { value: "tuesday", label: "Tuesday" },
  { value: "wednesday", label: "Wednesday" },
  { value: "thursday", label: "Thursday" },
  { value: "friday", label: "Friday" },
  { value: "saturday", label: "Saturday" },
  { value: "sunday", label: "Sunday" },
];

/** Settings → Dashboard: streak threshold, week start, midnight and overlap rules. */
export function DashboardSettings() {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [threshold, setThreshold] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    callPython("get_preferences")
      .then((preferences) => {
        setLoad({ status: "ready", preferences });
        setThreshold(String(preferences.streak_threshold_minutes));
      })
      .catch((error: unknown) => {
        setLoad({ status: "error", problem: problemFrom(error) });
      });
  }, [attempt]);

  const save = (changes: Partial<Preferences>, what: string) => {
    setSaved(null);
    setProblem(null);
    callPython("set_preferences", changes)
      .then((preferences) => {
        setLoad({ status: "ready", preferences });
        setThreshold(String(preferences.streak_threshold_minutes));
        setSaved(`${what} saved. The dashboard uses it from now on.`);
      })
      .catch((error: unknown) => {
        setProblem(problemFrom(error));
      });
  };

  return (
    <section className="panel" aria-labelledby="settings-dashboard">
      <h2 id="settings-dashboard">Dashboard</h2>
      {load.status === "loading" && (
        <p className="status" role="status">
          <span className="spinner" aria-hidden="true" /> Loading…
        </p>
      )}
      {load.status === "error" && (
        <div className="notice error" role="alert">
          <p>{load.problem.message}</p>
          <div className="actions">
            <button
              type="button"
              className="button"
              onClick={() => {
                setLoad({ status: "loading" });
                setAttempt((n) => n + 1);
              }}
            >
              Try again
            </button>
          </div>
        </div>
      )}
      {load.status === "ready" && (
        <div className="settings-grid">
          <form
            className="field"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              const value = Number(threshold);
              if (!Number.isInteger(value) || value < 0 || value > 1440) {
                setProblem({
                  code: "invalid_preference",
                  tone: "error",
                  title: "Check the threshold",
                  message: "Enter a whole number of minutes from 0 to 1440.",
                  errorId: null,
                  actions: [],
                });
                return;
              }
              save({ streak_threshold_minutes: value }, "Streak threshold");
            }}
          >
            <label htmlFor="streak-threshold">Streak day threshold (minutes)</label>
            <div className="input-row">
              <input
                id="streak-threshold"
                className="input"
                type="number"
                min={0}
                max={1440}
                step={1}
                value={threshold}
                onChange={(event) => {
                  setThreshold(event.target.value);
                }}
              />
              <button type="submit" className="button">
                Save
              </button>
            </div>
            <span className="small muted">
              0 counts any day with time logged. Otherwise a day needs at least this many minutes to
              keep a streak.
            </span>
          </form>

          <div className="field">
            <label htmlFor="week-start">Weeks start on</label>
            <select
              id="week-start"
              className="input select"
              value={load.preferences.week_start}
              onChange={(event) => {
                save({ week_start: event.target.value as Weekday }, "Week start");
              }}
            >
              {WEEKDAYS.map((day) => (
                <option key={day.value} value={day.value}>
                  {day.label}
                </option>
              ))}
            </select>
          </div>

          <fieldset className="choices">
            <legend className="legend">Sessions that cross midnight</legend>
            <label className="choice">
              <input
                type="radio"
                name="midnight-rule"
                checked={load.preferences.midnight_rule === "split"}
                onChange={() => {
                  save({ midnight_rule: "split" }, "Midnight rule");
                }}
              />
              <span>Split between the days they cover</span>
              <span className="hint">
                A session from 11 PM to 1 AM counts 1 hour on each day. A day never exceeds 24
                hours.
              </span>
            </label>
            <label className="choice">
              <input
                type="radio"
                name="midnight-rule"
                checked={load.preferences.midnight_rule === "start_date"}
                onChange={() => {
                  save({ midnight_rule: "start_date" }, "Midnight rule");
                }}
              />
              <span>Count the whole session on its start date</span>
              <span className="hint">
                A session longer than a day can then put more than 24 hours on one date.
              </span>
            </label>
          </fieldset>

          <fieldset className="choices">
            <legend className="legend">Overlapping sessions</legend>
            <label className="choice">
              <input
                type="radio"
                name="overlap-rule"
                checked={load.preferences.overlap_rule === "once"}
                onChange={() => {
                  save({ overlap_rule: "once" }, "Overlap rule");
                }}
              />
              <span>Count overlapping time once</span>
              <span className="hint">
                Totals show the time you actually spent. Overlapping time goes to the session that
                started first.
              </span>
            </label>
            <label className="choice">
              <input
                type="radio"
                name="overlap-rule"
                checked={load.preferences.overlap_rule === "sum"}
                onChange={() => {
                  save({ overlap_rule: "sum" }, "Overlap rule");
                }}
              />
              <span>Add every session&apos;s full time</span>
              <span className="hint">Overlapping time counts once for each session.</span>
            </label>
          </fieldset>
          <p className="small muted">
            Overlaps are applied first, then the midnight rule. A day&apos;s sessions, with any
            overlaps, are listed when you click it on the dashboard.
          </p>
        </div>
      )}
      {saved && (
        <p className="small status ok" role="status">
          {saved}
        </p>
      )}
      {problem && (
        <p className="field-error" role="alert">
          {problem.message}
        </p>
      )}
    </section>
  );
}
