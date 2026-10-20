import { useEffect, useState } from "react";

import { outcomeText, type SignInState } from "./useSignIn";

function remaining(deadline: number): string {
  const seconds = Math.max(0, Math.round((deadline - Date.now()) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function Countdown({ deadline }: { deadline: number }) {
  const [text, setText] = useState(() => remaining(deadline));
  useEffect(() => {
    const timer = window.setInterval(() => {
      setText(remaining(deadline));
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [deadline]);
  return <span className="countdown">{text} left</span>;
}

/** What's happening with "Connect to Notion", and what the person can do next. */
export function SignInStatus({
  state,
  onRetry,
  onCancel,
  onReopen,
  onUseToken,
}: {
  state: SignInState;
  onRetry: () => void;
  onCancel: () => void;
  onReopen: () => void;
  onUseToken?: () => void;
}) {
  if (state.phase === "starting") {
    return (
      <p className="waiting-line" role="status">
        <span className="spinner" aria-hidden="true" /> Opening Notion in your browser…
      </p>
    );
  }
  if (state.phase === "waiting") {
    return (
      <div className="notice ok waiting" role="status">
        <p className="waiting-line">
          <span className="spinner" aria-hidden="true" /> Finish connecting in your browser
        </p>
        <p className="small">
          Choose your workspace, share your work log, and click Allow access. This window updates by
          itself. <Countdown deadline={state.deadline} />
        </p>
        <div className="actions">
          <button type="button" className="button" onClick={onReopen}>
            Open Notion again
          </button>
          <button type="button" className="link-button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    );
  }
  if (state.phase === "finished") {
    const text = outcomeText(state.result);
    return (
      <div className={`notice ${text.tone}`} role="alert">
        <strong>{text.title}</strong>
        <p>{state.message ?? text.message}</p>
        <div className="actions">
          <button type="button" className="button" onClick={onRetry}>
            Connect again
          </button>
          {onUseToken && state.result === "service_unreachable" && (
            <button type="button" className="link-button" onClick={onUseToken}>
              Use a token instead
            </button>
          )}
        </div>
      </div>
    );
  }
  return null;
}
