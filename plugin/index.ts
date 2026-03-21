/**
 * openclaw-lacp-fusion — gateway entry point
 *
 * Hook-only plugin. LACP hooks are Python scripts under hooks/handlers/.
 * This shim registers them as gateway lifecycle hooks via api.on().
 */
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

const pluginDir = new URL(".", import.meta.url).pathname;

function runHandler(script: string, eventJson: string): string | null {
  const scriptPath = join(pluginDir, "hooks", "handlers", script);
  try {
    const result = execFileSync("python3", [scriptPath], {
      input: eventJson,
      encoding: "utf-8",
      timeout: 10_000,
      env: { ...process.env, OPENCLAW_PLUGIN_DIR: pluginDir },
    });
    return result.trim() || null;
  } catch (err: any) {
    return null;
  }
}

const lacpPlugin = {
  name: "OpenClaw LACP Fusion",
  description:
    "LACP integration — hooks, policy gates, gated execution, memory scaffolding, and evidence verification",

  register(api: OpenClawPluginApi) {
    // session-start: inject git context and LACP memory
    api.on("session_start", async (event, ctx) => {
      runHandler("session-start.py", JSON.stringify({ event, ctx }));
    });

    // pretool-guard: block dangerous patterns before execution
    api.on("before_tool_call", async (event, ctx) => {
      runHandler("pretool-guard.py", JSON.stringify({ event, ctx }));
    });

    // stop-quality-gate: detect incomplete work before agent stops
    api.on("agent_end", async (event, ctx) => {
      runHandler("stop-quality-gate.py", JSON.stringify({ event, ctx }));
    });

    // write-validate: validate schema/format before file writes
    api.on("before_message_write", async (event, ctx) => {
      runHandler("write-validate.py", JSON.stringify({ event, ctx }));
    });

    api.logger.info(
      `[lacp] Plugin loaded (version=${process.env.npm_package_version ?? "2.2.0"}, hooks=4)`,
    );
  },
};

export default lacpPlugin;
