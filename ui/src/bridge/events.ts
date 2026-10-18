import type { BackendEvent, BackendEventName, BackendEvents } from "./types";

/** The DOM event Python dispatches on `window` (app/events.py DOM_EVENT_NAME). */
export const DOM_EVENT_NAME = "habit-tracker:event";

type Handler<K extends BackendEventName> = (payload: BackendEvents[K]) => void;

function isBackendEvent(value: unknown): value is BackendEvent {
  return (
    typeof value === "object" && value !== null && "name" in value && typeof value.name === "string"
  );
}

/** Listen for one backend event. Returns a function that stops listening. */
export function onBackendEvent<K extends BackendEventName>(
  name: K,
  handler: Handler<K>,
): () => void {
  const listener = (event: Event) => {
    const detail: unknown = (event as CustomEvent<unknown>).detail;
    if (isBackendEvent(detail) && detail.name === name) {
      handler(detail.payload as BackendEvents[K]);
    }
  };
  window.addEventListener(DOM_EVENT_NAME, listener);
  return () => {
    window.removeEventListener(DOM_EVENT_NAME, listener);
  };
}
