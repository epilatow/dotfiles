import { spawn } from "node:child_process";
import { homedir } from "node:os";

import type { Plugin } from "@opencode-ai/plugin";

const HELPER = `${homedir()}/.local/libexec/tmux-agent-session-namer/tmux-agent-session-namer`;

// opencode reports this placeholder at creation and holds it until a
// real title is generated -- which for a run without an explicit
// --title can be never -- so it maps to the empty name: the helper
// lands the bare opencodeNN slot name rather than stamping the tmux
// session with a timestamp.
const PLACEHOLDER_TITLE = /^New session - /;

export const TmuxNamer: Plugin = async () => {
  let lastName = "";
  return {
    event: async ({ event }) => {
      if (
        event.type !== "session.created" &&
        event.type !== "session.updated"
      ) {
        return;
      }
      const info = event.properties.info;
      // Subagent sessions ride the same server; only the pane's own
      // session names the tmux session around it.
      if (info.parentID) return;
      const name = PLACEHOLDER_TITLE.test(info.title) ? "" : info.title;
      // session.created names the fresh session outright, even before a
      // real title exists; session.updated fires for every message
      // part, so only a changed name is worth another run.
      if (event.type === "session.updated" && name === lastName) return;
      lastName = name;
      // Best effort: failing to name the tmux session never disturbs the
      // agent run that asked for it.
      spawn(HELPER, ["opencode", name], { stdio: "ignore" }).on(
        "error",
        () => {},
      );
    },
  };
};
