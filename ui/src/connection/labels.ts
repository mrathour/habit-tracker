import type { ConnectionInfo, LogoutResult } from "../bridge/types";

/** What to call the connection: the workspace name, or for a personal token, its owner. */
export function connectionLabel(info: ConnectionInfo): string {
  if (info.workspace_name) return info.workspace_name;
  if (info.auth_kind === "pat") {
    return info.account_name
      ? `${info.account_name}'s personal access token`
      : "Your personal access token";
  }
  return "Your Notion workspace";
}

export function authKindLabel(kind: ConnectionInfo["auth_kind"]): string {
  switch (kind) {
    case "oauth":
      return "Connected with Notion sign-in";
    case "internal":
      return "Connected with an internal integration token";
    case "pat":
      return "Connected with a personal access token";
    default:
      return "Not connected";
  }
}

/** What to tell the person after disconnecting. */
export function disconnectSummary(result: LogoutResult): { tone: "ok" | "warn"; text: string } {
  const data = result.cleared_local_data
    ? "The copied entries were deleted."
    : "The copied entries are kept on this computer.";
  if (result.kind === "oauth") {
    return result.revoked
      ? { tone: "ok", text: `Disconnected, and Notion cancelled Habit Tracker's access. ${data}` }
      : {
          tone: "warn",
          text: `Disconnected on this computer, but Notion's access couldn't be cancelled (${result.revoke_error ?? "unknown error"}). Remove Habit Tracker in Notion under Settings, then Connections. ${data}`,
        };
  }
  if (result.kind === "internal") {
    return {
      tone: "warn",
      text: `Disconnected. The token still works until you delete the internal connection in Notion's developer portal. ${data}`,
    };
  }
  if (result.kind === "pat") {
    return {
      tone: "warn",
      text: `Disconnected. The token still works until it expires or you revoke it under Personal access tokens in Notion's developer portal. ${data}`,
    };
  }
  return { tone: "ok", text: `Disconnected. ${data}` };
}
