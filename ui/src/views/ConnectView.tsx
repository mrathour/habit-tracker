import { useState } from "react";

import type { ConnectionInfo } from "../bridge/types";
import { TimeStrip } from "../components/TimeStrip";
import { SignInStatus } from "../connection/SignInStatus";
import { TokenForm } from "../connection/TokenForm";
import { useSignIn } from "../connection/useSignIn";

/** First run: connect to Notion with the browser, or with a pasted token. */
export function ConnectView({ onConnected }: { onConnected: (info: ConnectionInfo) => void }) {
  const signIn = useSignIn(onConnected);
  const [useToken, setUseToken] = useState(false);
  const busy = signIn.state.phase === "starting" || signIn.state.phase === "waiting";

  return (
    <section className="connect" aria-labelledby="connect-title">
      <div className="connect-copy">
        <h1 id="connect-title">See where your working hours go</h1>
        <p className="lede">
          Habit Tracker reads the work sessions you log in Notion and turns them into daily totals,
          weekly trends and streaks.
        </p>
        <ul className="promise">
          <li>It only reads from Notion. It never changes your workspace.</li>
          <li>Your entries stay on this computer, so charts work offline.</li>
        </ul>

        {useToken ? (
          <>
            <h2>Connect with a token</h2>
            <TokenForm
              onConnected={onConnected}
              onCancel={() => {
                setUseToken(false);
              }}
            />
          </>
        ) : (
          <>
            {signIn.state.phase === "idle" && (
              <div className="actions">
                <button type="button" className="button primary large" onClick={signIn.start}>
                  Connect to Notion
                </button>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => {
                    setUseToken(true);
                  }}
                >
                  Use a token instead
                </button>
              </div>
            )}
            <SignInStatus
              state={signIn.state}
              onRetry={signIn.start}
              onCancel={signIn.cancel}
              onReopen={signIn.start}
              onUseToken={() => {
                signIn.reset();
                setUseToken(true);
              }}
            />
            {busy && (
              <p className="small muted">
                Notion opens in your default browser. Share the database you log your work in.
              </p>
            )}
          </>
        )}
      </div>
      <TimeStrip />
    </section>
  );
}
