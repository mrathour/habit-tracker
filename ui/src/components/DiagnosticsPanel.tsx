import { useState } from "react";

import { callPython } from "../bridge/client";
import { noticeFromCallError } from "../errors/reporting";

function RenderBomb(): never {
  throw new Error("Test error thrown while rendering");
}

/**
 * Buttons that fail on purpose, to check that every kind of error is shown and logged.
 * Shown in dev mode, or in normal mode with --diagnostics.
 */
export function DiagnosticsPanel() {
  const [explode, setExplode] = useState(false);

  return (
    <section className="card" aria-labelledby="diagnostics-title">
      <h2 id="diagnostics-title">Diagnostics</h2>
      <p className="muted">
        Each button causes a test error. The app should show a readable message and write the
        details to the log, never crash or go blank.
      </p>
      <div className="actions">
        <button
          type="button"
          className="button"
          onClick={() => {
            setExplode(true);
          }}
        >
          Error while rendering
        </button>
        <button
          type="button"
          className="button"
          onClick={() => {
            window.setTimeout(() => {
              throw new Error("Test error thrown from a timer");
            }, 0);
          }}
        >
          Error in UI code
        </button>
        <button
          type="button"
          className="button"
          onClick={() => {
            void Promise.reject(new Error("Test promise rejection"));
          }}
        >
          Rejected promise
        </button>
        <button
          type="button"
          className="button"
          onClick={() => {
            callPython("raise_test_error", "call").catch((error: unknown) => {
              noticeFromCallError(error, "A Python call failed");
            });
          }}
        >
          Error in a Python call
        </button>
        <button
          type="button"
          className="button"
          onClick={() => {
            callPython("raise_test_error", "thread").catch((error: unknown) => {
              noticeFromCallError(error, "A Python call failed");
            });
          }}
        >
          Error in a Python thread
        </button>
      </div>
      {explode && <RenderBomb />}
    </section>
  );
}
