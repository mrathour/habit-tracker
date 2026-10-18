import { useEffect, useState } from "react";

import { BridgeCallError, BridgeUnavailableError, callPython } from "../bridge/client";
import type { AppInfo, ErrorReport } from "../bridge/types";
import { describeError } from "../errors/reporting";

export type AppInfoState =
  | { status: "loading" }
  | { status: "ready"; info: AppInfo }
  | { status: "unavailable" }
  | { status: "error"; message: string; errorId: string | null };

export function useAppInfo(): AppInfoState {
  const [state, setState] = useState<AppInfoState>({ status: "loading" });
  useEffect(() => {
    let active = true;
    callPython("get_app_info")
      .then((info) => {
        if (active) setState({ status: "ready", info });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof BridgeUnavailableError) {
          setState({ status: "unavailable" });
        } else if (error instanceof BridgeCallError) {
          const report: ErrorReport = error.report;
          setState({ status: "error", message: report.message, errorId: report.id });
        } else {
          setState({ status: "error", message: describeError(error).message, errorId: null });
        }
      });
    return () => {
      active = false;
    };
  }, []);
  return state;
}
