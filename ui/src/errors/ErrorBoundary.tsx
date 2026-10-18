import { Component, type ErrorInfo, type ReactNode } from "react";

import { callPython } from "../bridge/client";
import { describeError, reportClientError, UNEXPECTED_MESSAGE } from "./reporting";

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
  hasError: boolean;
  errorId: string | null;
  reported: boolean;
}

/**
 * Catches errors thrown while rendering and shows a readable page instead of a blank window.
 * The error is sent to the Python log, and its ID is shown so it can be found there.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null, hasError: false, errorId: null, reported: false };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error, hasError: true, errorId: null, reported: false };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    const { message, stack } = describeError(error);
    void reportClientError({
      source: "render",
      message,
      stack,
      componentStack: info.componentStack ?? undefined,
    }).then((errorId) => {
      this.setState({ errorId, reported: true });
    });
  }

  override render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    const { message } = describeError(this.state.error);
    return (
      <main className="fatal" role="alert">
        <div className="fatal-card">
          <h1>Something went wrong</h1>
          <p>{UNEXPECTED_MESSAGE}</p>
          <label className="muted" htmlFor="fatal-detail">
            Details
          </label>
          <textarea id="fatal-detail" className="detail" readOnly value={message} />
          <p className="muted">
            {this.state.reported
              ? this.state.errorId
                ? `Error ID ${this.state.errorId}.`
                : "The error couldn't be written to the log."
              : "Saving the details to the log…"}
          </p>
          <div className="actions">
            <button
              type="button"
              className="button primary"
              onClick={() => {
                window.location.reload();
              }}
            >
              Reload
            </button>
            <button
              type="button"
              className="button"
              onClick={() => {
                void callPython("open_log_folder").catch(() => undefined);
              }}
            >
              Open log folder
            </button>
          </div>
        </div>
      </main>
    );
  }
}
