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

type HandlerResult = {
  stdout: string | null;
  exitCode: number;
  blocked: boolean;
  error?: string;
};

function runHandler(script: string, eventJson: string, logger?: { warn: (msg: string) => void }): HandlerResult {
  const scriptPath = join(pluginDir, "hooks", "handlers", script);
  try {
    const result = execFileSync("python3", [scriptPath], {
      input: eventJson,
      encoding: "utf-8",
      timeout: 10_000,
      env: { ...process.env, OPENCLAW_PLUGIN_DIR: pluginDir },
    });
    return { stdout: result.trim() || null, exitCode: 0, blocked: false };
  } catch (err: any) {
    const exitCode = err.status ?? 1;
    const stderr = err.stderr?.toString().trim() ?? "";
    const stdout = err.stdout?.toString().trim() ?? "";
    if (exitCode !== 0 && logger) {
      logger.warn(`[lacp] ${script} exited ${exitCode}: ${stderr || stdout || "unknown error"}`);
    }
    return {
      stdout: stdout || null,
      exitCode,
      blocked: exitCode === 1,
      error: stderr || undefined,
    };
  }
}

let _logger: { info: (msg: string) => void; warn: (msg: string) => void } | undefined;

const lacpPlugin = {
  name: "OpenClaw LACP Fusion",
  description:
    "LACP integration — hooks, policy gates, gated execution, memory scaffolding, and evidence verification",

  register(api: OpenClawPluginApi) {
    _logger = api.logger;

    // session-start: inject git context and LACP memory
    api.on("session_start", async (event, ctx) => {
      const result = runHandler("session-start.py", JSON.stringify({ event, ctx }), api.logger);
      if (result.stdout) {
        try {
          const parsed = JSON.parse(result.stdout);
          if (parsed.systemMessage) {
            return parsed;
          }
        } catch { /* not JSON, ignore */ }
      }
    });

    // pretool-guard: block dangerous patterns before execution
    api.on("before_tool_call", async (event, ctx) => {
      const result = runHandler("pretool-guard.py", JSON.stringify({ event, ctx }), api.logger);
      if (result.blocked) {
        throw new Error(result.error || result.stdout || "Blocked by pretool-guard");
      }
    });

    // stop-quality-gate: detect incomplete work before agent stops
    api.on("agent_end", async (event, ctx) => {
      const result = runHandler("stop-quality-gate.py", JSON.stringify({ event, ctx }), api.logger);
      if (result.blocked) {
        try {
          const parsed = JSON.parse(result.stdout ?? "{}");
          if (parsed.decision === "block") {
            throw new Error(parsed.reason || "Quality gate blocked stop");
          }
        } catch (e) {
          if (e instanceof Error && e.message !== "Quality gate blocked stop") {
            throw new Error(result.error || "Quality gate blocked stop");
          }
          throw e;
        }
      }
    });

    // write-validate: validate schema/format before file writes
    api.on("before_message_write", async (event, ctx) => {
      const result = runHandler("write-validate.py", JSON.stringify({ event, ctx }), api.logger);
      if (result.exitCode === 2) {
        throw new Error(result.error || "Write validation failed");
      }
    });

    api.logger.info(
      `[lacp] Plugin loaded (version=${process.env.npm_package_version ?? "2.2.0"}, hooks=4)`,
    );
  },
};

export default lacpPlugin;
