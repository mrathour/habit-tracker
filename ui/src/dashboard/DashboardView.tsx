import { useMemo, useState, type ReactNode } from "react";

import type { DailyRange, Dashboard, DayTotal, SyncStatus, WeekTotal } from "../bridge/types";
import { DayDetailDialog } from "./DayDetailDialog";
import { EChart } from "./EChart";
import { formatDay, formatDuration, formatRange, plural } from "./format";
import { calendarOption, dailyOption, weeklyOption } from "./options";
import { useChartTheme, useDashboard, type DashboardView as View } from "./useDashboard";

const WEEKDAY_INDEX: Record<string, number> = {
  sunday: 0,
  monday: 1,
  tuesday: 2,
  wednesday: 3,
  thursday: 4,
  friday: 5,
  saturday: 6,
};

/**
 * Home's dashboard (PLAN.md 7): streaks, daily totals, weekly trend and the calendar. Every
 * chart has a table view, and clicking a day opens its sessions.
 */
export function DashboardSection({
  sync,
  onShowFlagged,
}: {
  sync: SyncStatus | null;
  /** Opens the raw log filtered to entries with issues (PLAN.md 7, 8). */
  onShowFlagged: () => void;
}) {
  // A finished sync (or a new result) refreshes the figures.
  const refreshKey = `${sync?.last_result?.finished_at ?? ""}|${String(sync?.entries ?? 0)}`;
  const { view, setView, load, retry } = useDashboard(refreshKey);
  const [day, setDay] = useState<string | null>(null);

  if (load.status === "loading") {
    return (
      <section className="dashboard" aria-label="Dashboard" aria-busy="true">
        <div className="stat-row">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="stat skeleton" />
          ))}
        </div>
        <div className="chart-card skeleton tall" />
      </section>
    );
  }
  if (load.status === "error") {
    return (
      <section className="dashboard" aria-label="Dashboard">
        <div className={`notice ${load.problem.tone}`} role="alert">
          <strong>The dashboard couldn&apos;t be loaded</strong>
          <p>{load.problem.message}</p>
          {load.problem.errorId && <p className="small muted">Error ID {load.problem.errorId}</p>}
          <div className="actions">
            <button type="button" className="button" onClick={retry}>
              Try again
            </button>
          </div>
        </div>
      </section>
    );
  }
  const data = load.data;
  if (data.entries === 0) {
    return (
      <section className="dashboard" aria-label="Dashboard">
        <div className="empty dashboard-empty">
          <h2>Your charts appear after the first sync</h2>
          <p>
            {sync?.running
              ? "Your entries are being copied now. The charts fill in when the sync finishes."
              : "Once your work log's entries are copied to this computer, your daily totals, weekly trend, streaks and calendar show here."}
          </p>
        </div>
      </section>
    );
  }
  return (
    <section className="dashboard" aria-label="Dashboard" aria-busy={load.refreshing}>
      {data.counted_sessions === 0 ? (
        <div className="notice warn" role="status">
          <strong>None of your entries can be charted yet</strong>
          <p>
            All {plural(data.entries, "entry", "entries")} are missing a start or end time, or end
            before they start. Fix them in Notion and they appear here after the next sync.
          </p>
          <div className="actions">
            <button type="button" className="button" onClick={onShowFlagged}>
              See the entries with issues
            </button>
          </div>
        </div>
      ) : (
        data.excluded > 0 && (
          <p className="small muted">
            {plural(data.excluded, "entry", "entries")} {data.excluded === 1 ? "is" : "are"} left
            out of the charts because of a missing time or an end before the start.{" "}
            <button type="button" className="link-button" onClick={onShowFlagged}>
              See {data.excluded === 1 ? "it" : "them"}
            </button>
          </p>
        )
      )}
      <StatRow data={data} onShowFlagged={onShowFlagged} />
      <DailyCard data={data} view={view} setView={setView} onDay={setDay} />
      <WeeklyCard weeks={data.weekly} view={view} setView={setView} />
      <CalendarCard data={data} view={view} setView={setView} onDay={setDay} />
      {day && (
        <DayDetailDialog
          day={day}
          onClose={() => {
            setDay(null);
          }}
        />
      )}
    </section>
  );
}

function StatRow({ data, onShowFlagged }: { data: Dashboard; onShowFlagged: () => void }) {
  const { current, longest, today_counts, threshold_minutes } = data.streaks;
  const threshold =
    threshold_minutes > 0 ? `${formatDuration(threshold_minutes)} or more a day` : "any time a day";
  return (
    <div className="stat-row">
      <div className="stat">
        <span className="stat-label">Current streak</span>
        <span className="stat-value figure">{plural(current?.days ?? 0, "day")}</span>
        <span className="small muted">
          {current
            ? today_counts
              ? `Since ${formatDay(current.start)}`
              : `Through yesterday. Log ${threshold_minutes > 0 ? formatDuration(threshold_minutes) : "some time"} today to keep it going.`
            : `Counts days with ${threshold}.`}
        </span>
      </div>
      <div className="stat">
        <span className="stat-label">Longest streak</span>
        <span className="stat-value figure">{plural(longest?.days ?? 0, "day")}</span>
        <span className="small muted">
          {longest ? formatRange(longest.start, longest.end) : "None yet"}
        </span>
      </div>
      <div className="stat">
        <span className="stat-label">In this range</span>
        <span className="stat-value figure">{formatDuration(data.daily.total_minutes)}</span>
        <span className="small muted">
          {plural(data.daily.active_days, "active day")} of {data.daily.days.length}
        </span>
      </div>
      <div className="stat">
        <span className="stat-label">Entries with issues</span>
        <span className="stat-value figure">{data.flagged.toLocaleString()}</span>
        {data.flagged > 0 ? (
          <button type="button" className="link-button small" onClick={onShowFlagged}>
            See them in the raw log
          </button>
        ) : (
          <span className="small muted">All entries look right</span>
        )}
      </div>
    </div>
  );
}

function ChartCard({
  title,
  id,
  controls,
  summary,
  empty,
  chart,
  table,
}: {
  title: string;
  id: string;
  controls: ReactNode;
  summary: ReactNode;
  empty: string | null;
  chart: ReactNode;
  table: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="chart-card" aria-labelledby={id}>
      <div className="chart-head">
        <h2 id={id}>{title}</h2>
        <div className="chart-controls">
          {controls}
          <button
            type="button"
            className="link-button small"
            aria-pressed={asTable}
            onClick={() => {
              setAsTable(!asTable);
            }}
          >
            {asTable ? "Show as chart" : "Show as table"}
          </button>
        </div>
      </div>
      <p className="small muted chart-summary">{summary}</p>
      {asTable ? (
        <div className="table-wrap">{table}</div>
      ) : (
        <div className="chart-body">
          {chart}
          {empty && <p className="chart-empty">{empty}</p>}
        </div>
      )}
    </section>
  );
}

function DayTable({
  days,
  onDay,
  caption,
}: {
  days: DayTotal[];
  onDay: (day: string) => void;
  caption: string;
}) {
  const shown = days.filter((d) => d.minutes > 0 || days.length <= 31);
  return (
    <table className="data-table">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Day</th>
          <th scope="col">Time</th>
          <th scope="col">Sessions</th>
        </tr>
      </thead>
      <tbody>
        {shown.length === 0 && (
          <tr>
            <td colSpan={3} className="muted">
              No time logged.
            </td>
          </tr>
        )}
        {[...shown].reverse().map((d) => (
          <tr key={d.date}>
            <th scope="row">
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  onDay(d.date);
                }}
              >
                {formatDay(d.date)}
              </button>
            </th>
            <td className="figure">{formatDuration(d.minutes)}</td>
            <td className="figure">{d.sessions}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function rangeKey(range: DailyRange): string {
  return "days" in range ? String(range.days) : "custom";
}

function DailyCard({
  data,
  view,
  setView,
  onDay,
}: {
  data: Dashboard;
  view: View;
  setView: (view: View) => void;
  onDay: (day: string) => void;
}) {
  const theme = useChartTheme();
  const days = data.daily.days;
  const option = useMemo(() => dailyOption(days, theme), [days, theme]);
  const [from, setFrom] = useState(data.daily.first);
  const [to, setTo] = useState(data.daily.last);
  const current = rangeKey(view.range);
  return (
    <ChartCard
      title="Daily totals"
      id="daily-title"
      controls={
        <>
          <div className="segmented" role="group" aria-label="Range">
            {([7, 30, 90] as const).map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={current === String(n)}
                onClick={() => {
                  setView({ ...view, range: { days: n } });
                }}
              >
                {n} days
              </button>
            ))}
            <button
              type="button"
              aria-pressed={current === "custom"}
              onClick={() => {
                setView({ ...view, range: { from, to } });
              }}
            >
              Custom
            </button>
          </div>
          {current === "custom" && (
            <form
              className="custom-range"
              onSubmit={(event) => {
                event.preventDefault();
                setView({ ...view, range: { from, to } });
              }}
            >
              <label>
                From{" "}
                <input
                  type="date"
                  className="input"
                  value={from}
                  max={data.today}
                  onChange={(event) => {
                    setFrom(event.target.value);
                  }}
                />
              </label>
              <label>
                To{" "}
                <input
                  type="date"
                  className="input"
                  value={to}
                  max={data.today}
                  onChange={(event) => {
                    setTo(event.target.value);
                  }}
                />
              </label>
              <button type="submit" className="button small">
                Show
              </button>
            </form>
          )}
        </>
      }
      summary={`${formatRange(data.daily.first, data.daily.last)} · ${formatDuration(data.daily.total_minutes)}. Click a day to see its sessions.`}
      empty={data.daily.total_minutes > 0 ? null : "No time logged in this range."}
      chart={
        <EChart
          option={option}
          label={`Daily totals from ${formatDay(data.daily.first)} to ${formatDay(data.daily.last)}`}
          height={260}
          onClick={(click) => {
            const clicked = days[click.dataIndex];
            if (clicked) onDay(clicked.date);
          }}
        />
      }
      table={<DayTable days={days} onDay={onDay} caption="Daily totals" />}
    />
  );
}

function WeeklyCard({
  weeks,
  view,
  setView,
}: {
  weeks: WeekTotal[];
  view: View;
  setView: (view: View) => void;
}) {
  const theme = useChartTheme();
  const option = useMemo(() => weeklyOption(weeks, theme), [weeks, theme]);
  const total = weeks.reduce((sum, w) => sum + w.minutes, 0);
  const first = weeks[0];
  const last = weeks[weeks.length - 1];
  return (
    <ChartCard
      title="Weekly trend"
      id="weekly-title"
      controls={
        <label className="inline-select">
          <span className="visually-hidden">Weeks shown</span>
          <select
            className="input select"
            value={view.weeks}
            onChange={(event) => {
              setView({ ...view, weeks: Number(event.target.value) as View["weeks"] });
            }}
          >
            <option value={12}>12 weeks</option>
            <option value={26}>26 weeks</option>
            <option value={52}>52 weeks</option>
          </select>
        </label>
      }
      summary={
        first && last
          ? `${formatRange(first.start, last.end)} · ${formatDuration(total)}. The line is the average of each week and the three before it.`
          : ""
      }
      empty={total > 0 ? null : "No time logged in these weeks."}
      chart={
        <EChart
          option={option}
          label={`Weekly totals for the last ${String(weeks.length)} weeks, with a 4-week average`}
          height={260}
        />
      }
      table={
        <table className="data-table">
          <caption className="visually-hidden">Weekly totals</caption>
          <thead>
            <tr>
              <th scope="col">Week</th>
              <th scope="col">Time</th>
              <th scope="col">4-week average</th>
            </tr>
          </thead>
          <tbody>
            {[...weeks].reverse().map((w) => (
              <tr key={w.start}>
                <th scope="row">
                  {formatRange(w.start, w.end)}
                  {w.partial ? " (so far)" : ""}
                </th>
                <td className="figure">{formatDuration(w.minutes)}</td>
                <td className="figure">
                  {w.rolling_average === null ? "—" : formatDuration(w.rolling_average)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  );
}

function CalendarCard({
  data,
  view,
  setView,
  onDay,
}: {
  data: Dashboard;
  view: View;
  setView: (view: View) => void;
  onDay: (day: string) => void;
}) {
  const theme = useChartTheme();
  const cal = data.calendar;
  const weekStart = WEEKDAY_INDEX[data.preferences.week_start] ?? 1;
  const option = useMemo(
    () => calendarOption(cal.days, cal.first, cal.last, cal.max_minutes, theme, weekStart),
    [cal, theme, weekStart],
  );
  const years = [...cal.years].sort((a, b) => b - a);
  const active = cal.days.filter((d) => d.minutes > 0).length;
  return (
    <ChartCard
      title="Calendar"
      id="calendar-title"
      controls={
        <label className="inline-select">
          <span className="visually-hidden">Year shown</span>
          <select
            className="input select"
            value={view.year ?? "last"}
            onChange={(event) => {
              const value = event.target.value;
              setView({ ...view, year: value === "last" ? null : Number(value) });
            }}
          >
            <option value="last">Last 12 months</option>
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </label>
      }
      summary={`${formatRange(cal.first, cal.last)} · ${formatDuration(cal.total_minutes)} on ${plural(active, "day")}. Darker days have more time.`}
      empty={cal.total_minutes > 0 ? null : "No time logged in this period."}
      chart={
        <EChart
          option={option}
          label={`Calendar of daily time from ${formatDay(cal.first)} to ${formatDay(cal.last)}`}
          height={150}
          onClick={(click) => {
            const value = click.value as [string, number] | undefined;
            if (value) onDay(value[0]);
          }}
        />
      }
      table={<DayTable days={cal.days} onDay={onDay} caption="Days with time logged" />}
    />
  );
}
