import { BridgeCallError } from "../bridge/client";
import type { ErrorCode } from "../bridge/types";
import { describeError } from "../errors/reporting";

/** What the screen can offer to fix a problem. */
export type ProblemAction = "reconnect" | "paste_token" | "retry" | "use_token" | "choose_database";

export interface Problem {
  code: ErrorCode | "unknown";
  tone: "error" | "warn";
  title: string;
  message: string;
  errorId: string | null;
  actions: ProblemAction[];
}

const TITLES: Partial<
  Record<ErrorCode, { title: string; tone: Problem["tone"]; actions: ProblemAction[] }>
> = {
  offline: { title: "You're offline", tone: "warn", actions: ["retry"] },
  reconnect: { title: "Reconnect to Notion", tone: "error", actions: ["reconnect"] },
  paste_new_token: { title: "Paste a new token", tone: "error", actions: ["paste_token"] },
  service_unreachable: {
    title: "The sign-in service can't be reached",
    tone: "warn",
    actions: ["retry", "use_token"],
  },
  credential_store: {
    title: "Windows couldn't store Notion access",
    tone: "error",
    actions: ["retry"],
  },
  notion_error: { title: "Notion refused the request", tone: "error", actions: ["retry"] },
  not_connected: { title: "Not connected to Notion", tone: "warn", actions: ["reconnect"] },
  no_database: { title: "No work log chosen", tone: "warn", actions: ["choose_database"] },
  source_unavailable: {
    title: "Your work log can't be opened",
    tone: "error",
    actions: ["choose_database", "retry"],
  },
  mapping_invalid: { title: "The mapping can't be saved", tone: "error", actions: [] },
};

/** Turn any failed call into what the screen should say and offer. */
export function problemFrom(error: unknown): Problem {
  if (error instanceof BridgeCallError) {
    const code = error.report.code ?? null;
    const known = code ? TITLES[code] : undefined;
    return {
      code: code ?? "unknown",
      tone: known?.tone ?? "error",
      title: known?.title ?? "Something went wrong",
      message: error.report.message,
      errorId: error.report.id,
      actions: known?.actions ?? ["retry"],
    };
  }
  return {
    code: "unknown",
    tone: "error",
    title: "Something went wrong",
    message: describeError(error).message,
    errorId: null,
    actions: ["retry"],
  };
}
