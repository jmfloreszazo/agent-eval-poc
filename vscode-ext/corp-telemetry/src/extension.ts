// VS Code extension entry point — registers the @corp chat participant.
//
// Two slash commands:
//   /case <id>   shells out to scenario-3/src/corp.py and streams stdout.
//                Emits one corp.case.run event with exit code + timings.
//   /ask  <text> answers free-form via request.model (Copilot's IDE model)
//                while counting input/output tokens with model.countTokens.
//                Emits one corp.agent.invocation per turn with cost.
//
// In both cases telemetry is emitted to Application Insights via the
// resolved connection string (setting -> env -> .env.scenario-3).

import * as cp from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

import { Pricing, resolvePricingPath } from "./pricing";
import {
    CorpTelemetry,
    newCorrelationId,
    resolveConnectionString,
} from "./telemetry";

const PARTICIPANT_ID = "corp";
const AGENT_NAME = "corp";
const COMMAND_CASE = "case";
const COMMAND_ASK = "ask";

interface Settings {
    actor: string;
    team: string;
    pythonPath: string;
    pricingYamlPath: string;
    appInsightsConnectionString: string;
}

function readSettings(): Settings {
    const cfg = vscode.workspace.getConfiguration("corp");
    return {
        actor:
            (cfg.get<string>("actor") || "").trim() ||
            (os.userInfo().username ?? "unknown"),
        team: cfg.get<string>("team") || "unknown",
        pythonPath: (cfg.get<string>("pythonPath") || "").trim(),
        pricingYamlPath:
            cfg.get<string>("pricingYamlPath") || "scenario-3/src/pricing.yaml",
        appInsightsConnectionString:
            cfg.get<string>("appInsightsConnectionString") || "",
    };
}

function resolvePython(
    workspaceFolder: string | undefined,
    setting: string,
): string | null {
    if (setting) {
        return setting;
    }
    if (!workspaceFolder) {
        return null;
    }
    const candidate =
        process.platform === "win32"
            ? path.join(workspaceFolder, ".venv", "Scripts", "python.exe")
            : path.join(workspaceFolder, ".venv", "bin", "python");
    return fs.existsSync(candidate) ? candidate : null;
}

function workspaceRoot(): string | undefined {
    const folders = vscode.workspace.workspaceFolders;
    return folders && folders.length > 0 ? folders[0].uri.fsPath : undefined;
}

function tailString(s: string, maxChars = 2000): string {
    return s.length <= maxChars ? s : s.slice(s.length - maxChars);
}

// ----- /case handler -------------------------------------------------------

async function handleCase(
    prompt: string,
    settings: Settings,
    telemetry: CorpTelemetry,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
): Promise<vscode.ChatResult> {
    const root = workspaceRoot();
    if (!root) {
        stream.markdown(
            "**ERROR** No workspace folder open. `/case` needs the repo on disk to run `scenario-3/src/corp.py`.",
        );
        return { errorDetails: { message: "No workspace folder" } };
    }

    const python = resolvePython(root, settings.pythonPath);
    if (!python) {
        stream.markdown(
            "**ERROR** Could not find a Python interpreter. Set `corp.pythonPath` or create `.venv` in the workspace root.",
        );
        return { errorDetails: { message: "Python not found" } };
    }

    const corpPy = path.join(root, "scenario-3", "src", "corp.py");
    if (!fs.existsSync(corpPy)) {
        stream.markdown(
            `**ERROR** \`scenario-3/src/corp.py\` not found at \`${corpPy}\`.`,
        );
        return { errorDetails: { message: "corp.py not found" } };
    }

    // Accept either a case id (e.g. "case-001") or "--all".
    const trimmed = prompt.trim();
    const args = ["-X", "utf8", corpPy];
    let caseId = "all";
    if (!trimmed || trimmed === "--all" || trimmed.toLowerCase() === "all") {
        args.push("--all");
    } else if (trimmed.startsWith("--case-file ")) {
        args.push("--case-file", trimmed.slice("--case-file ".length).trim());
        caseId = "case-file";
    } else {
        // Strip a leading "--case " if the user typed it
        const idOnly = trimmed.startsWith("--case ")
            ? trimmed.slice("--case ".length).trim()
            : trimmed.split(/\s+/)[0];
        args.push("--case", idOnly);
        caseId = idOnly;
    }

    const correlationId = newCorrelationId();
    stream.markdown(
        `Running \`${path.basename(python)} scenario-3/src/corp.py ${args
            .slice(2)
            .join(" ")}\`\n\n` +
            `_corp.actor_: \`${settings.actor}\` · _corp.team_: \`${settings.team}\` · _corr_id_: \`${correlationId}\`\n\n`,
    );

    const started = Date.now();
    const child = cp.spawn(python, args, {
        cwd: root,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });

    let stdout = "";
    let stderr = "";
    const cancelSub = token.onCancellationRequested(() => {
        try {
            child.kill();
        } catch {
            /* noop */
        }
    });

    child.stdout?.setEncoding("utf-8");
    child.stderr?.setEncoding("utf-8");
    child.stdout?.on("data", (chunk: string) => {
        stdout += chunk;
        // Stream as a fenced log so newlines render nicely.
        stream.markdown("```\n" + chunk + "\n```\n");
    });
    child.stderr?.on("data", (chunk: string) => {
        stderr += chunk;
        stream.markdown("```diff\n- " + chunk.replace(/\n/g, "\n- ") + "\n```\n");
    });

    const exitCode: number = await new Promise((resolve) => {
        child.on("close", (code) => resolve(code ?? -1));
        child.on("error", () => resolve(-1));
    });
    cancelSub.dispose();
    const durationMs = Date.now() - started;

    stream.markdown(
        `\n\n**corp.py** exited with code \`${exitCode}\` after ${durationMs} ms.`,
    );

    telemetry.emitCaseRun({
        actor: settings.actor,
        team: settings.team,
        correlationId,
        caseId,
        pythonExitCode: exitCode,
        durationMs,
        pyStdoutTail: tailString(stdout),
        pyStderrTail: tailString(stderr),
    });
    await telemetry.flush();

    if (exitCode !== 0) {
        return {
            errorDetails: { message: `corp.py exit code ${exitCode}` },
        };
    }
    return {};
}

// ----- /ask handler --------------------------------------------------------

async function handleAsk(
    prompt: string,
    settings: Settings,
    pricing: Pricing | null,
    telemetry: CorpTelemetry,
    request: vscode.ChatRequest,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
): Promise<vscode.ChatResult> {
    if (!request.model) {
        stream.markdown(
            "**ERROR** No language model available in this chat session.",
        );
        return { errorDetails: { message: "No model" } };
    }

    const correlationId = newCorrelationId();
    const model = request.model;
    const userPrompt = prompt.trim();
    if (!userPrompt) {
        stream.markdown(
            "Usage: `@corp /ask <your question>`. Every turn is telemetered to App Insights with cost.\n",
        );
        return {};
    }

    const started = Date.now();
    let inputTokens = 0;
    let outputTokens = 0;
    let collected = "";
    let errorMessage: string | undefined;

    try {
        inputTokens = await model.countTokens(userPrompt, token);
    } catch (err: unknown) {
        // Token counting may not be available for every model — keep going.
        inputTokens = Math.ceil(userPrompt.length / 4); // crude fallback
    }

    try {
        const messages: vscode.LanguageModelChatMessage[] = [
            vscode.LanguageModelChatMessage.User(userPrompt),
        ];
        const response = await model.sendRequest(messages, {}, token);
        for await (const fragment of response.text) {
            collected += fragment;
            stream.markdown(fragment);
            if (token.isCancellationRequested) {
                break;
            }
        }
        try {
            outputTokens = await model.countTokens(collected, token);
        } catch {
            outputTokens = Math.ceil(collected.length / 4);
        }
    } catch (err: unknown) {
        errorMessage = err instanceof Error ? err.message : String(err);
        stream.markdown(`\n\n**Model error:** ${errorMessage}\n`);
    }

    const latencyMs = Date.now() - started;
    const cost = pricing
        ? pricing.computeCost(model.id, inputTokens, outputTokens)
        : null;

    telemetry.emitInvocation({
        actor: settings.actor,
        team: settings.team,
        agent: AGENT_NAME,
        command: COMMAND_ASK,
        correlationId,
        modelId: model.id,
        modelFamily: (model as { family?: string }).family,
        modelVendor: (model as { vendor?: string }).vendor,
        modelKnown: cost !== null,
        inputTokens,
        outputTokens,
        costUsd: cost ? cost.totalUsd : null,
        pricingDate: cost?.pricingDate,
        latencyMs,
        error: errorMessage,
    });
    await telemetry.flush();

    const costSuffix = cost
        ? `cost ≈ **$${cost.totalUsd.toFixed(5)}** (in=${cost.inputUsd.toFixed(
              5,
          )} out=${cost.outputUsd.toFixed(5)}, priced ${cost.pricingDate})`
        : `model \`${model.id}\` not in pricing.yaml — cost not computed`;

    stream.markdown(
        `\n\n---\n_governance:_ ` +
            `model=\`${model.id}\` · ` +
            `in=${inputTokens}t · out=${outputTokens}t · ${latencyMs}ms · ${costSuffix}\n` +
            `_${telemetry.configuredHint}_ · _corr_id_: \`${correlationId}\`\n`,
    );

    return errorMessage ? { errorDetails: { message: errorMessage } } : {};
}

// ----- activate ------------------------------------------------------------

export function activate(context: vscode.ExtensionContext): void {
    const settings = readSettings();
    const root = workspaceRoot();
    const connectionString = resolveConnectionString(
        settings.appInsightsConnectionString,
        root,
    );
    const telemetry = new CorpTelemetry(connectionString);

    // Load pricing.yaml lazily; tolerate missing file (cost just won't be priced).
    let pricing: Pricing | null = null;
    const pricingPath = resolvePricingPath(root, settings.pricingYamlPath);
    if (pricingPath) {
        try {
            pricing = Pricing.fromFile(pricingPath);
        } catch (err) {
            // Pricing parse error is logged once on activation — never fatal.
            console.warn(
                `[corp] failed to load pricing.yaml at ${pricingPath}: ${
                    err instanceof Error ? err.message : String(err)
                }`,
            );
        }
    }

    const handler: vscode.ChatRequestHandler = async (
        request,
        _context,
        stream,
        token,
    ) => {
        // Re-read settings every turn so the user can change actor/team
        // without reloading the window.
        const live = readSettings();

        if (request.command === COMMAND_CASE) {
            return handleCase(request.prompt, live, telemetry, stream, token);
        }
        if (request.command === COMMAND_ASK || !request.command) {
            return handleAsk(
                request.prompt,
                live,
                pricing,
                telemetry,
                request,
                stream,
                token,
            );
        }
        stream.markdown(
            `Unknown command \`/${request.command}\`. Available: \`/case\`, \`/ask\`.`,
        );
        return {};
    };

    const participant = vscode.chat.createChatParticipant(PARTICIPANT_ID, handler);
    participant.iconPath = new vscode.ThemeIcon("shield");

    context.subscriptions.push(participant, {
        dispose: () => {
            telemetry.flush().catch(() => {
                /* noop */
            });
        },
    });
}

export function deactivate(): void {
    // The participant + telemetry are cleaned up via context.subscriptions.
}
