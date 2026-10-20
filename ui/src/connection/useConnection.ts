import { useCallback, useEffect, useState } from "react";

import { BridgeCallError, BridgeUnavailableError, callPython } from "../bridge/client";
import type { ConnectionInfo } from "../bridge/types";
import { describeError } from "../errors/reporting";

export type ConnectionLoad =
  | { status: "loading" }
  | { status: "ready"; info: ConnectionInfo }
  | { status: "unavailable" }
  | { status: "error"; message: string; errorId: string | null };

/** The Notion connection as Python sees it. `setInfo` applies a newer copy from any call. */
export function useConnection() {
  const [load, setLoad] = useState<ConnectionLoad>({ status: "loading" });

  const reload = useCallback(() => {
    callPython("get_connection")
      .then((info) => {
        setLoad({ status: "ready", info });
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
    reload();
  }, [reload]);

  const setInfo = useCallback((info: ConnectionInfo) => {
    setLoad({ status: "ready", info });
  }, []);

  return { load, reload, setInfo };
}
