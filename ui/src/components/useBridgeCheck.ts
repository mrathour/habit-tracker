import { useCallback, useEffect, useRef, useState } from "react";

import { callPython } from "../bridge/client";
import { onBackendEvent } from "../bridge/events";
import { noticeFromCallError } from "../errors/reporting";

export interface ReceivedEvent {
  name: string;
  detail: string;
  receivedAt: Date;
}

export type BridgeCheckState =
  | { status: "idle" }
  | { status: "starting" }
  | { status: "running"; runId: string; step: number; steps: number }
  | { status: "done"; runId: string; steps: number; elapsedMs: number };

export const MAX_EVENT_LOG = 12;

/** Runs the Python bridge check and follows the progress events it pushes. */
export function useBridgeCheck(steps = 5) {
  const [state, setState] = useState<BridgeCheckState>({ status: "idle" });
  const [events, setEvents] = useState<readonly ReceivedEvent[]>([]);
  const runId = useRef<string | null>(null);
  const starting = useRef(false);

  useEffect(() => {
    const record = (name: string, detail: string) => {
      setEvents((previous) =>
        [{ name, detail, receivedAt: new Date() }, ...previous].slice(0, MAX_EVENT_LOG),
      );
    };
    // Events can arrive before run_bridge_check() returns its run ID, so while a run is
    // starting, its first event claims the ID. Events from any other run are ignored.
    const isCurrentRun = (id: string) => {
      if (runId.current === null && starting.current) runId.current = id;
      return id === runId.current;
    };
    const stopProgress = onBackendEvent("bridge-check:progress", (payload) => {
      if (!isCurrentRun(payload.run_id)) return;
      record(
        "bridge-check:progress",
        `step ${payload.step} of ${payload.steps} · ${payload.thread}`,
      );
      setState({
        status: "running",
        runId: payload.run_id,
        step: payload.step,
        steps: payload.steps,
      });
    });
    const stopDone = onBackendEvent("bridge-check:done", (payload) => {
      if (!isCurrentRun(payload.run_id)) return;
      record("bridge-check:done", `finished in ${payload.elapsed_ms} ms`);
      setState((previous) => ({
        status: "done",
        runId: payload.run_id,
        steps: previous.status === "running" ? previous.steps : steps,
        elapsedMs: payload.elapsed_ms,
      }));
    });
    return () => {
      stopProgress();
      stopDone();
    };
  }, [steps]);

  const start = useCallback(() => {
    runId.current = null;
    starting.current = true;
    setEvents([]);
    setState({ status: "starting" });
    callPython("run_bridge_check", steps)
      .then((started) => {
        runId.current = started.run_id;
        starting.current = false;
        setState((previous) =>
          previous.status === "starting"
            ? { status: "running", runId: started.run_id, step: 0, steps: started.steps }
            : previous,
        );
      })
      .catch((error: unknown) => {
        starting.current = false;
        setState({ status: "idle" });
        noticeFromCallError(error, "The bridge check couldn't start");
      });
  }, [steps]);

  return { state, events, start };
}
