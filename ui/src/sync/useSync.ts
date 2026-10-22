import { useCallback, useEffect, useState } from "react";

import { callPython } from "../bridge/client";
import { onBackendEvent } from "../bridge/events";
import type { SyncRequest, SyncStatus } from "../bridge/types";
import { problemFrom, type Problem } from "../connection/problems";

export type SyncLoad =
  | { status: "idle" }
  | { status: "ready"; sync: SyncStatus }
  | { status: "error"; problem: Problem };

/**
 * The sync status as Python sees it. Python pushes the whole status as `sync:status` events
 * while a sync runs and when it ends, so the screen never pieces it together itself.
 */
export function useSync(enabled: boolean) {
  const [load, setLoad] = useState<SyncLoad>({ status: "idle" });
  const [startProblem, setStartProblem] = useState<Problem | null>(null);

  const refresh = useCallback(() => {
    callPython("get_sync_status")
      .then((sync) => {
        setLoad({ status: "ready", sync });
      })
      .catch((error: unknown) => {
        setLoad({ status: "error", problem: problemFrom(error) });
      });
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    const stop = onBackendEvent("sync:status", (sync) => {
      setLoad({ status: "ready", sync });
    });
    refresh();
    return stop;
  }, [enabled, refresh]);

  const start = useCallback((kind: SyncRequest) => {
    setStartProblem(null);
    callPython("start_sync", kind)
      .then((sync) => {
        setLoad({ status: "ready", sync });
      })
      .catch((error: unknown) => {
        setStartProblem(problemFrom(error));
      });
  }, []);

  const resolveRemoval = useCallback(async (remove: boolean) => {
    const sync = await callPython("resolve_pending_removal", remove);
    setLoad({ status: "ready", sync });
  }, []);

  // Not syncable (not connected, no work log or no mapping): nothing to show.
  return {
    load: enabled ? load : ({ status: "idle" } as const),
    start,
    startProblem,
    refresh,
    resolveRemoval,
  };
}

export type SyncState = ReturnType<typeof useSync>;
