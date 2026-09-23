import { spawn } from "node:child_process";
import { homedir } from "node:os";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const HELPER = `${homedir()}/.local/libexec/tmux-agent-session-namer/tmux-agent-session-namer`;

export default function (pi: ExtensionAPI) {
  // An unset session name passes the empty string: the helper lands the
  // bare piNN slot name, which a later /name upgrade replaces.
  const rename = (name: string) => {
    if (!process.env.TMUX) return;
    // Best effort: failing to name the tmux session never disturbs the
    // agent run that asked for it.
    spawn(HELPER, ["pi", name], { stdio: "ignore" }).on("error", () => {});
  };
  pi.on("session_start", (_event, ctx) =>
    rename(ctx.sessionManager.getSessionName() ?? ""),
  );
  pi.on("session_info_changed", (event) => rename(event.name ?? ""));
}
