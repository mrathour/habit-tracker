import { useEffect, useRef } from "react";

import { callPython } from "../bridge/client";
import type { PolicyChange } from "../bridge/types";
import type { PolicyLoad } from "./usePolicyNotice";

function quit() {
  void callPython("quit").catch(() => undefined);
}

function formatDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? date
    : parsed.toLocaleDateString(undefined, { dateStyle: "long" });
}

function Change({ change }: { change: PolicyChange }) {
  return (
    <li className="policy-change">
      <h3>
        Version {change.version} · <time dateTime={change.date}>{formatDate(change.date)}</time>
      </h3>
      <ul>
        {change.summary.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ul>
    </li>
  );
}

/**
 * Shown before anything else while the privacy policy notice is loading, waiting, or couldn't
 * be read (PLAN.md 13). Only "clear" lets the rest of the app start.
 */
export function PolicyGate({
  load,
  onAcknowledge,
  onRetry,
}: {
  load: Exclude<PolicyLoad, { status: "clear" }>;
  onAcknowledge: () => void;
  onRetry: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const showing = load.status === "notice";
  useEffect(() => {
    if (showing) heading.current?.focus();
  }, [showing]);

  if (load.status === "loading") {
    return (
      <p className="status" role="status">
        <span className="spinner" aria-hidden="true" /> Starting…
      </p>
    );
  }
  if (load.status === "unavailable") {
    return (
      <div className="notice warn" role="alert">
        <strong>Open this inside Habit Tracker</strong>
        <p>
          This page isn&apos;t running inside the Habit Tracker window, so it can&apos;t reach
          Python. Start the app with <code>uv run habit-tracker --dev</code>.
        </p>
      </div>
    );
  }
  if (load.status === "error") {
    return (
      <div className="notice error" role="alert">
        <strong>The app couldn&apos;t check for privacy policy changes</strong>
        <p>It waits until it can, so nothing changes without you knowing. {load.message}</p>
        {load.errorId && <p className="small muted">Error ID {load.errorId}</p>}
        <div className="actions">
          <button type="button" className="button" onClick={onRetry}>
            Try again
          </button>
          <button type="button" className="button" onClick={quit}>
            Close the app
          </button>
        </div>
      </div>
    );
  }

  const { notice, saving, error } = load;
  const openPolicy = () => {
    void callPython("open_external", notice.url).catch(() => undefined);
  };
  return (
    <section className="panel policy-notice" aria-labelledby="policy-title">
      <h1 id="policy-title" className="section-title" tabIndex={-1} ref={heading}>
        The privacy policy has changed
      </h1>
      <p className="lede">
        Habit Tracker&apos;s privacy policy has changed since you last used the app. Here is what is
        different. Nothing new happens until you continue.
      </p>
      <ol className="policy-changes">
        {notice.changes.map((change) => (
          <Change key={change.version} change={change} />
        ))}
      </ol>
      <p>
        <button type="button" className="link-button" onClick={openPolicy}>
          Read the full privacy policy
        </button>{" "}
        <span className="small muted">(opens in your browser)</span>
      </p>
      <p className="small muted">
        If you don&apos;t want to continue, close the app. It will show this again next time. To
        stop using Habit Tracker, uninstall it and choose to also delete its data and your Notion
        sign-in.
      </p>
      {error && (
        <div className="notice error" role="alert">
          <strong>Your answer couldn&apos;t be saved</strong>
          <p>{error}</p>
        </div>
      )}
      <div className="actions">
        <button
          type="button"
          className="button primary"
          onClick={onAcknowledge}
          disabled={saving}
          aria-busy={saving}
        >
          {saving ? "Saving…" : "Continue"}
        </button>
        <button type="button" className="button" onClick={quit} disabled={saving}>
          Close the app
        </button>
      </div>
    </section>
  );
}
