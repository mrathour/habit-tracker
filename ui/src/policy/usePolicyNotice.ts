import { useCallback, useEffect, useState } from "react";

import { BridgeCallError, BridgeUnavailableError, callPython } from "../bridge/client";
import type { PolicyNotice } from "../bridge/types";
import { describeError } from "../errors/reporting";

export type PolicyLoad =
  | { status: "loading" }
  /** Nothing to show: the rest of the app may start. */
  | { status: "clear" }
  | { status: "notice"; notice: PolicyNotice; saving: boolean; error: string | null }
  | { status: "unavailable" }
  | { status: "error"; message: string; errorId: string | null };

/**
 * The privacy policy notice (PLAN.md 13). It is read from this build, never from the website,
 * and must be cleared before the app does anything else, including its launch sync. If it can't
 * be read, the app waits rather than carrying on as if there were no notice.
 */
export function usePolicyNotice() {
  const [load, setLoad] = useState<PolicyLoad>({ status: "loading" });

  const fetchNotice = useCallback(() => {
    callPython("get_policy_notice")
      .then((notice) => {
        setLoad(
          notice ? { status: "notice", notice, saving: false, error: null } : { status: "clear" },
        );
      })
      .catch((error: unknown) => {
        if (error instanceof BridgeUnavailableError) {
          setLoad({ status: "unavailable" });
        } else if (error instanceof BridgeCallError) {
          setLoad({ status: "error", message: error.report.message, errorId: error.report.id });
        } else {
          setLoad({ status: "error", message: describeError(error).message, errorId: null });
        }
      });
  }, []);

  useEffect(() => {
    fetchNotice();
  }, [fetchNotice]);

  const reload = useCallback(() => {
    setLoad({ status: "loading" });
    fetchNotice();
  }, [fetchNotice]);

  const acknowledge = useCallback(() => {
    if (load.status !== "notice" || load.saving) return;
    const { notice } = load;
    setLoad({ status: "notice", notice, saving: true, error: null });
    callPython("acknowledge_policy", notice.version)
      .then(() => {
        setLoad({ status: "clear" });
      })
      .catch((error: unknown) => {
        const message =
          error instanceof BridgeCallError
            ? `${error.report.message} (Error ID ${error.report.id})`
            : describeError(error).message;
        setLoad({ status: "notice", notice, saving: false, error: message });
      });
  }, [load]);

  return { load, reload, acknowledge };
}
