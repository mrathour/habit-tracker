import type { ConnectionInfo } from "../bridge/types";
import { connectionLabel } from "../connection/labels";

export function WorkspaceBadge({ info, small = false }: { info: ConnectionInfo; small?: boolean }) {
  const label = connectionLabel(info);
  const icon = info.workspace_icon;
  return (
    <span className={small ? "workspace small" : "workspace"}>
      {icon?.type === "image" ? (
        <span className="workspace-icon">
          <img src={icon.value} alt="" />
        </span>
      ) : icon?.type === "emoji" ? (
        <span className="workspace-icon emoji" aria-hidden="true">
          {icon.value}
        </span>
      ) : (
        <span className="workspace-icon" aria-hidden="true">
          {label.trim().charAt(0).toUpperCase() || "N"}
        </span>
      )}
      <span className="workspace-name">{label}</span>
    </span>
  );
}
