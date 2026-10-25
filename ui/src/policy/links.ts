import { callPython } from "../bridge/client";

/** The public pages, served by the token service (PLAN.md 12.2). */
export const PRIVACY_URL = "https://habit-tracker.mrathour.workers.dev/privacy";
export const TERMS_URL = "https://habit-tracker.mrathour.workers.dev/terms";

/** Open one of the public pages in the default browser. Only on the user's click. */
export function openPage(url: string): void {
  void callPython("open_external", url).catch(() => undefined);
}
