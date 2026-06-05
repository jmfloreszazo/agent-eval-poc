// Pricing — loads scenario-3/src/pricing.yaml and computes USD cost per turn.
//
// Mirrors the Python implementation at scenario-3/src/pricing.py so the
// IDE-side telemetry agrees with the batch pipeline. The YAML format is:
//
//   models:
//     openai/gpt-4o-mini:
//       prices:
//         - date: 2026-01-01
//           input_per_million_usd: 0.150
//           output_per_million_usd: 0.600
//
// Lookup picks the most recent `date` <= today.

import * as fs from "fs";
import * as path from "path";
import { parse as parseYaml } from "yaml";

export interface PriceEntry {
    date: string; // ISO YYYY-MM-DD
    input_per_million_usd: number;
    output_per_million_usd: number;
}

export interface ModelPricing {
    family?: string;
    encoder?: string;
    prices: PriceEntry[];
}

export interface PricingTable {
    models: Record<string, ModelPricing>;
}

export interface CostBreakdown {
    inputUsd: number;
    outputUsd: number;
    totalUsd: number;
    pricingDate: string; // the date entry that was applied
    modelKey: string;    // the key actually resolved in the table
    fallbackUsed: boolean;
}

export class Pricing {
    constructor(private readonly table: PricingTable) {}

    static fromFile(absPath: string): Pricing {
        const raw = fs.readFileSync(absPath, "utf-8");
        const parsed = parseYaml(raw) as PricingTable;
        if (!parsed || !parsed.models) {
            throw new Error(
                `pricing.yaml at ${absPath} did not contain a top-level 'models' key`,
            );
        }
        return new Pricing(parsed);
    }

    /**
     * Tries `modelId`, then `modelId` with the `openai/` prefix stripped,
     * then `modelId.split("/").pop()`. Returns the resolved key + entry
     * plus `fallbackUsed=true` when the original id wasn't a direct hit.
     */
    private resolveModel(modelId: string): { key: string; entry: ModelPricing; fallback: boolean } | null {
        const candidates: string[] = [modelId];
        if (modelId.includes("/")) {
            const tail = modelId.split("/").pop();
            if (tail) {
                candidates.push(tail);
            }
        }
        // Some IDE responses use plain "gpt-4o-mini"; some use "openai/gpt-4o-mini"
        if (!modelId.includes("/")) {
            candidates.push(`openai/${modelId}`);
        }
        for (let i = 0; i < candidates.length; i++) {
            const key = candidates[i];
            const entry = this.table.models[key];
            if (entry) {
                return { key, entry, fallback: i > 0 };
            }
        }
        return null;
    }

    private pickPrice(prices: PriceEntry[], onDate: Date): PriceEntry {
        if (!prices.length) {
            throw new Error("pricing entry has no prices[] array");
        }
        const target = onDate.toISOString().slice(0, 10);
        const sorted = [...prices].sort((a, b) => (a.date < b.date ? -1 : 1));
        let chosen = sorted[0];
        for (const p of sorted) {
            if (p.date <= target) {
                chosen = p;
            } else {
                break;
            }
        }
        return chosen;
    }

    /**
     * Compute the USD cost of a turn. Returns `null` when the model id is
     * unknown — caller should emit `corp.model_known=false` instead of
     * fabricating a cost.
     */
    computeCost(
        modelId: string,
        inputTokens: number,
        outputTokens: number,
        on: Date = new Date(),
    ): CostBreakdown | null {
        const resolved = this.resolveModel(modelId);
        if (!resolved) {
            return null;
        }
        const price = this.pickPrice(resolved.entry.prices, on);
        const inputUsd = (inputTokens / 1_000_000) * price.input_per_million_usd;
        const outputUsd = (outputTokens / 1_000_000) * price.output_per_million_usd;
        return {
            inputUsd,
            outputUsd,
            totalUsd: inputUsd + outputUsd,
            pricingDate: price.date,
            modelKey: resolved.key,
            fallbackUsed: resolved.fallback,
        };
    }
}

/**
 * Resolve `pricing.yaml` against the workspace folder. Returns `null` when
 * no workspace is open or the file doesn't exist (caller logs a warning).
 */
export function resolvePricingPath(
    workspaceFolder: string | undefined,
    settingValue: string,
): string | null {
    if (!workspaceFolder) {
        return null;
    }
    const abs = path.isAbsolute(settingValue)
        ? settingValue
        : path.join(workspaceFolder, settingValue);
    return fs.existsSync(abs) ? abs : null;
}
