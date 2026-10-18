import { BridgeCallError, callPython } from "../bridge/client";
import { onBackendEvent } from "../bridge/events";
import type { ClientErrorReport } from "../bridge/types";
import { pushNotice } from "./notices";

export const UNEXPECTED_TITLE = "Something went wrong";
export const UNEXPECTED_MESSAGE =
  "The app hit an unexpected problem. The details have been saved to the log.";

export function describeError(error: unknown): { message: string; stack: string | undefined } {
  if (error instanceof Error) {
    return { message: `${error.name}: ${error.message}`, stack: error.stack };
  }
  try {
    return { message: `Non-error value thrown: ${JSON.stringify(error)}`, stack: undefined };
  } catch {
    return { message: `Non-error value thrown: ${String(error)}`, stack: undefined };
  }
}

/**
 * Log a UI error to the Python log and return its error ID, or null if it couldn't be logged
 * (for example when the page isn't running inside the desktop app). Never throws.
 */
export async function reportClientError(report: ClientErrorReport): Promise<string | null> {
  try {
    const { id } = await callPython("log_client_error", report);
    return id;
  } catch (failure) {
    console.error("Couldn't send an error to the app's log", failure, report);
    return null;
  }
}

/** Report an unexpected UI error and show it as a banner. */
export async function handleUnexpectedError(
  error: unknown,
  source: ClientErrorReport["source"],
): Promise<void> {
  const { message, stack } = describeError(error);
  const errorId = await reportClientError({ source, message, stack });
  pushNotice({ title: UNEXPECTED_TITLE, message: UNEXPECTED_MESSAGE, errorId, detail: message });
}

/** Show a failed Python call as a banner. The error is already logged by Python. */
export function noticeFromCallError(error: unknown, title: string): void {
  if (error instanceof BridgeCallError) {
    pushNotice({
      title,
      message: error.report.message,
      errorId: error.report.id,
      detail: error.report.detail,
    });
    return;
  }
  void handleUnexpectedError(error, "promise");
}

/**
 * Catch errors that escape React (event handlers, timers, promises) and errors Python reports
 * from background threads, so none of them fail silently. Returns a cleanup function.
 */
export function installGlobalErrorHandlers(): () => void {
  const onError = (event: ErrorEvent) => {
    void handleUnexpectedError(event.error ?? event.message, "window");
  };
  const onRejection = (event: PromiseRejectionEvent) => {
    void handleUnexpectedError(event.reason, "promise");
  };
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  const stopBackend = onBackendEvent("app:error", (report) => {
    pushNotice({
      title: report.kind === "expected" ? "Something needs attention" : UNEXPECTED_TITLE,
      message: report.message,
      errorId: report.id,
      detail: report.detail,
    });
  });
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
    stopBackend();
  };
}
