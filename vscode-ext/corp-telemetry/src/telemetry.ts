// Telemetry — thin wrapper around the Application Insights v3 TelemetryClient.
//
// Emits two kinds of events that mirror the Python side (scenario-3/src/telemetry.py):
//
//   - corp.case.run         (parent — one per /case invocation)
//   - corp.agent.invocation (child  — one per IDE chat turn handled by @corp)
//
// Plus two custom metrics: corp.tokens.input and corp.tokens.output.
//
// The connection string is resolved (in order):
//   1. setting corp.appInsightsConnectionString
//   2. env var APPLICATIONINSIGHTS_CONNECTION_STRING
//   3. .env.scenario-3 in the workspace root
//
// When no connection string is found, the client becomes a no-op so the
// extension still works (the user sees a one-line WARN in the chat).

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { TelemetryClient } from "applicationinsights";

export interface InvocationProps {
    actor: string;
    team: string;
    agent: string;          // "corp" | "fraud-analyst" | "legal-counsel"
    command: string;        // "case" | "ask"
    caseId?: string;
    correlationId: string;
    modelId: string;
    modelFamily?: string;
    modelVendor?: string;
    modelKnown: boolean;    // false when pricing lookup failed
    inputTokens: number;
    outputTokens: number;
    costUsd: number | null;
    pricingDate?: string;
    latencyMs: number;
    verdict?: string;
    error?: string;
}

export interface CaseRunProps {
    actor: string;
    team: string;
    correlationId: string;
    caseId: string;
    pythonExitCode: number;
    durationMs: number;
    pyStdoutTail: string;   // last ~2KB of stdout for triage
    pyStderrTail: string;
}

export class CorpTelemetry {
    private client: TelemetryClient | null = null;
    private readonly connectionString: string | null;

    constructor(connectionString: string | null) {
        this.connectionString = connectionString;
        if (connectionString) {
            try {
                this.client = new TelemetryClient(connectionString);
                // Stamp every event so KQL can pivot on cloud_RoleName.
                this.client.context.tags[this.client.context.keys.cloudRole] =
                    "vscode-corp-telemetry";
                this.client.context.tags[this.client.context.keys.cloudRoleInstance] =
                    os.hostname();
            } catch (err) {
                // Connection string was malformed — fall back to no-op.
                this.client = null;
            }
        }
    }

    get isEnabled(): boolean {
        return this.client !== null;
    }

    get configuredHint(): string {
        return this.connectionString
            ? "telemetry: on (Application Insights)"
            : "telemetry: OFF — set corp.appInsightsConnectionString or APPLICATIONINSIGHTS_CONNECTION_STRING";
    }

    emitInvocation(props: InvocationProps): void {
        if (!this.client) {
            return;
        }
        const properties: Record<string, string> = {
            "corp.actor": props.actor,
            "corp.team": props.team,
            "corp.agent_name": props.agent,
            "corp.command": props.command,
            "corp.corr_id": props.correlationId,
            "corp.orchestrator": "vscode-corp",
            "corp.stage": "ide",
            "gen_ai.request.model": props.modelId,
            "gen_ai.system": props.modelVendor ?? "unknown",
            "gen_ai.usage.source": "vscode.lm.countTokens",
            "corp.model_known": String(props.modelKnown),
        };
        if (props.modelFamily) {
            properties["gen_ai.request.model.family"] = props.modelFamily;
        }
        if (props.caseId) {
            properties["corp.case_id"] = props.caseId;
        }
        if (props.verdict) {
            properties["corp.verdict"] = props.verdict;
        }
        if (props.pricingDate) {
            properties["corp.pricing.date"] = props.pricingDate;
        }
        if (props.error) {
            properties["corp.error"] = props.error;
        }

        const measurements: Record<string, number> = {
            "gen_ai.usage.input_tokens": props.inputTokens,
            "gen_ai.usage.output_tokens": props.outputTokens,
            "gen_ai.usage.total_tokens": props.inputTokens + props.outputTokens,
            "corp.latency_ms": props.latencyMs,
        };
        if (props.costUsd !== null) {
            measurements["corp.cost_usd"] = props.costUsd;
        }

        this.client.trackEvent({
            name: "corp.agent.invocation",
            properties,
            measurements,
        });

        // Also push the token counts as metrics so they aggregate cleanly in
        // App Insights and Workbooks.
        this.client.trackMetric({
            name: "corp.tokens.input",
            value: props.inputTokens,
            properties,
        });
        this.client.trackMetric({
            name: "corp.tokens.output",
            value: props.outputTokens,
            properties,
        });
    }

    emitCaseRun(props: CaseRunProps): void {
        if (!this.client) {
            return;
        }
        this.client.trackEvent({
            name: "corp.case.run",
            properties: {
                "corp.actor": props.actor,
                "corp.team": props.team,
                "corp.corr_id": props.correlationId,
                "corp.case_id": props.caseId,
                "corp.orchestrator": "vscode-corp",
                "corp.stage": "ide-shell",
                "corp.py.exit_code": String(props.pythonExitCode),
                "corp.py.stdout_tail": props.pyStdoutTail,
                "corp.py.stderr_tail": props.pyStderrTail,
            },
            measurements: {
                "corp.duration_ms": props.durationMs,
                "corp.py.exit_code": props.pythonExitCode,
            },
        });
    }

    async flush(): Promise<void> {
        if (!this.client) {
            return;
        }
        // v3 still exposes flush(); ignore the optional callback.
        await new Promise<void>((resolve) => {
            try {
                this.client!.flush();
                // Give the exporter ~500ms to drain.
                setTimeout(resolve, 500);
            } catch {
                resolve();
            }
        });
    }
}

// ----- Connection-string discovery ----------------------------------------

export function resolveConnectionString(
    settingValue: string,
    workspaceFolder: string | undefined,
): string | null {
    const trimmed = settingValue?.trim();
    if (trimmed) {
        return trimmed;
    }
    const fromEnv = process.env.APPLICATIONINSIGHTS_CONNECTION_STRING;
    if (fromEnv && fromEnv.trim()) {
        return fromEnv.trim();
    }
    if (!workspaceFolder) {
        return null;
    }
    // Try .env.scenario-3 then .env.scenario-2 (App Insights is shared).
    for (const fname of [".env.scenario-3", ".env.scenario-2"]) {
        const p = path.join(workspaceFolder, fname);
        if (!fs.existsSync(p)) {
            continue;
        }
        const value = readEnvKey(p, "APPLICATIONINSIGHTS_CONNECTION_STRING");
        if (value) {
            return value;
        }
    }
    return null;
}

function readEnvKey(absPath: string, key: string): string | null {
    let content: string;
    try {
        content = fs.readFileSync(absPath, "utf-8");
    } catch {
        return null;
    }
    for (const rawLine of content.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith("#")) {
            continue;
        }
        const eq = line.indexOf("=");
        if (eq === -1) {
            continue;
        }
        const k = line.slice(0, eq).trim();
        if (k !== key) {
            continue;
        }
        let v = line.slice(eq + 1).trim();
        // Strip surrounding quotes if any.
        if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
            v = v.slice(1, -1);
        }
        return v || null;
    }
    return null;
}

export function newCorrelationId(): string {
    // Short random id without requiring `crypto.randomUUID` typing
    // headaches on older lib targets; good enough for correlation.
    const hex = "0123456789abcdef";
    let s = "";
    for (let i = 0; i < 16; i++) {
        s += hex[Math.floor(Math.random() * 16)];
    }
    return `corp-${Date.now().toString(36)}-${s}`;
}
