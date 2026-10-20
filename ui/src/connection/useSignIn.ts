import { useCallback, useEffect, useRef, useState } from "react";

import { BridgeCallError, callPython } from "../bridge/client";
import { onBackendEvent } from "../bridge/events";
import type { ConnectionInfo, SignInResult } from "../bridge/types";

export type SignInState =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "waiting"; deadline: number }
  | { phase: "finished"; result: Exclude<SignInResult, "connected">; message: string | null };

/**
 * "Connect to Notion" through the browser. Python opens Notion's consent page; the outcome
 * arrives as a connect:done event, so cancelling in Notion is reported at once.
 */
export function useSignIn(onConnected: (info: ConnectionInfo) => void) {
  const [state, setState] = useState<SignInState>({ phase: "idle" });
  const connected = useRef(onConnected);
  useEffect(() => {
    connected.current = onConnected;
  }, [onConnected]);

  useEffect(() => {
    const stopWaiting = onBackendEvent("connect:waiting", ({ timeout_s }) => {
      setState({ phase: "waiting", deadline: Date.now() + timeout_s * 1000 });
    });
    const stopDone = onBackendEvent("connect:done", (payload) => {
      if (payload.result === "connected" && payload.connection) {
        setState({ phase: "idle" });
        connected.current(payload.connection);
        return;
      }
      if (payload.result === "connected") {
        setState({ phase: "finished", result: "error", message: null });
        return;
      }
      setState({ phase: "finished", result: payload.result, message: payload.message ?? null });
    });
    return () => {
      stopWaiting();
      stopDone();
    };
  }, []);

  const start = useCallback(() => {
    setState((previous) => (previous.phase === "waiting" ? previous : { phase: "starting" }));
    callPython("start_sign_in").catch((error: unknown) => {
      const code = error instanceof BridgeCallError ? error.report.code : null;
      const result =
        code === "service_unreachable" || code === "offline" ? "service_unreachable" : "error";
      const message = error instanceof BridgeCallError ? error.report.message : null;
      setState({ phase: "finished", result, message });
    });
  }, []);

  const cancel = useCallback(() => {
    void callPython("cancel_sign_in").catch(() => undefined);
  }, []);

  const reset = useCallback(() => {
    setState({ phase: "idle" });
  }, []);

  return { state, start, cancel, reset };
}

export function outcomeText(result: Exclude<SignInResult, "connected">): {
  title: string;
  message: string;
  tone: "warn" | "error";
} {
  switch (result) {
    case "cancelled":
      return {
        title: "Sign-in stopped",
        message: "Nothing changed. Connect again whenever you're ready.",
        tone: "warn",
      };
    case "access_denied":
      return {
        title: "Access wasn't allowed",
        message: "You didn't allow access in Notion, so nothing changed.",
        tone: "warn",
      };
    case "expired":
      return {
        title: "The sign-in expired",
        message: "It took too long to finish. Start again and complete it in the browser.",
        tone: "warn",
      };
    case "timeout":
      return {
        title: "No answer from the browser",
        message: "Nothing came back within 5 minutes. If you closed the tab, start again.",
        tone: "warn",
      };
    case "service_unreachable":
      return {
        title: "The sign-in service can't be reached",
        message:
          "Habit Tracker's sign-in service or Notion can't be reached right now. Try again in a moment, or connect with a token instead.",
        tone: "error",
      };
    case "notion_error":
      return {
        title: "Notion couldn't complete the sign-in",
        message: "Try again.",
        tone: "error",
      };
    default:
      return {
        title: "Connecting didn't finish",
        message: "Something went wrong. Try again.",
        tone: "error",
      };
  }
}
