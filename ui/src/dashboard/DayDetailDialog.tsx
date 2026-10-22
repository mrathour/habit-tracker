import { useEffect, useState } from "react";

import { callPython } from "../bridge/client";
import type { DayDetail, DetailSession } from "../bridge/types";
import { Dialog } from "../components/Dialog";
import { problemFrom, type Problem } from "../connection/problems";
import { noticeFromCallError } from "../errors/reporting";
import { browserTimeZone, formatDateTime, formatDay, formatDuration, formatTime } from "./format";

type Load =
  | { status: "loading" }
  | { status: "ready"; detail: DayDetail }
  | { status: "error"; problem: Problem };

function openInNotion(url: string) {
  callPython("open_external", url).catch((error: unknown) => {
    noticeFromCallError(error, "Notion couldn't be opened");
  });
}

function sessionTimes(session: DetailSession, timeZone: string): string {
  if (session.crosses_midnight) {
    return `${formatDateTime(session.start_utc, timeZone)} – ${formatDateTime(session.end_utc, timeZone)}`;
  }
  return `${formatTime(session.start_utc, timeZone)} – ${formatTime(session.end_utc, timeZone)}`;
}

/**
 * Every session counted on one day, so the chart's total can be checked against Notion entry by
 * entry: full length, minutes counted that day, midnight splits and overlaps.
 */
export function DayDetailDialog({ day, onClose }: { day: string; onClose: () => void }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    callPython("get_day_detail", browserTimeZone(), day)
      .then((detail) => {
        if (current) setLoad({ status: "ready", detail });
      })
      .catch((error: unknown) => {
        if (current) setLoad({ status: "error", problem: problemFrom(error) });
      });
    return () => {
      current = false;
    };
  }, [day, attempt]);

  return (
    <Dialog title={formatDay(day)} onClose={onClose}>
      {load.status === "loading" && (
        <p className="status" role="status">
          <span className="spinner" aria-hidden="true" /> Loading the day…
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
      {load.status === "ready" && <DetailBody detail={load.detail} />}
      <div className="actions">
        <button type="button" className="button" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}

function DetailBody({ detail }: { detail: DayDetail }) {
  const zone = detail.time_zone;
  const once = detail.preferences.overlap_rule === "once";
  const split = detail.preferences.midnight_rule === "split";
  if (detail.sessions.length === 0) {
    return <p className="muted">No time was logged on this day.</p>;
  }
  const overlapping = detail.sessions.filter((s) => s.overlap_minutes > 0).length;
  return (
    <div className="day-detail">
      <p className="day-total">
        <span className="figure">{formatDuration(detail.minutes)}</span>{" "}
        <span className="muted">
          counted from {detail.sessions.length}{" "}
          {detail.sessions.length === 1 ? "session" : "sessions"}
        </span>
      </p>
      {overlapping > 0 && (
        <p className="small warn-text">
          {overlapping} {overlapping === 1 ? "session overlaps" : "sessions overlap"} another.{" "}
          {once
            ? "Overlapping time is counted once, for the session that started first."
            : "Every session's full time is counted, so overlapping time counts more than once."}{" "}
          Fix the times in Notion if they&apos;re wrong.
        </p>
      )}
      <ul className="detail-list" aria-label="Sessions on this day">
        {detail.sessions.map((session) => (
          <li
            key={session.page_id}
            className={session.overlap_minutes > 0 ? "detail-session overlaps" : "detail-session"}
          >
            <div className="detail-head">
              {session.display_id && <span className="figure muted">#{session.display_id}</span>}
              <span className="detail-name">{session.task_name ?? "Untitled"}</span>
              <button
                type="button"
                className="link-button small"
                onClick={() => {
                  openInNotion(session.url);
                }}
              >
                Open in Notion
              </button>
            </div>
            <dl className="detail-facts">
              <dt>Time</dt>
              <dd>{sessionTimes(session, zone)}</dd>
              <dt>Length</dt>
              <dd className="figure">{formatDuration(session.minutes)}</dd>
              <dt>Counted this day</dt>
              <dd className="figure">{formatDuration(session.counted_minutes)}</dd>
            </dl>
            {session.crosses_midnight && (
              <p className="small muted">
                {split
                  ? "Crosses midnight: split between the days it covers."
                  : "Crosses midnight: counted on its start date."}
              </p>
            )}
            {session.overlap_minutes > 0 && (
              <p className="small warn-text">
                Overlaps {session.overlaps_with.map((o) => o.label).join(", ")} by{" "}
                {formatDuration(session.overlap_minutes)}.
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
