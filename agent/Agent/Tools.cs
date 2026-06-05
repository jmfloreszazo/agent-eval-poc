namespace CostAgent.Agent;

/// <summary>
/// Agent tools. Toy data, but real shape: each tool takes typed arguments
/// and returns a serializable result that ends up in the trajectory.
/// </summary>
public static class Tools
{
    public delegate object? ToolFunc(Dictionary<string, object?> args);

    public sealed record ToolSpec(string Name, string Description, string JsonSchema);

    public static readonly IReadOnlyDictionary<string, ToolFunc> Registry =
        new Dictionary<string, ToolFunc>
        {
            ["list_resources"] = ListResources,
            ["get_unit_price"] = GetUnitPrice,
            ["estimate_monthly_cost"] = EstimateMonthlyCost,
            ["get_savings_recommendations"] = GetSavingsRecommendations,
            ["get_resource_tags"] = GetResourceTags,
        };

    /// <summary>Schemas sent to the LLM via function calling.</summary>
    public static readonly IReadOnlyList<ToolSpec> Specs = new ToolSpec[]
    {
        new("list_resources",
            "List the identifiers of every resource in the subscription.",
            """{"type":"object","properties":{},"required":[]}"""),
        new("get_unit_price",
            "Return the monthly cost in USD for a specific resource.",
            """{"type":"object","properties":{"resource":{"type":"string","description":"Resource id, e.g. vm-app-01"}},"required":["resource"]}"""),
        new("estimate_monthly_cost",
            "Compute the total monthly cost of the subscription summing every resource.",
            """{"type":"object","properties":{},"required":[]}"""),
        new("get_savings_recommendations",
            "Return savings recommendations (reserved instances, right-sizing, tier change) for every resource.",
            """{"type":"object","properties":{},"required":[]}"""),
        new("get_resource_tags",
            "Return the tags (key=value) of a specific resource.",
            """{"type":"object","properties":{"resource":{"type":"string","description":"Resource id"}},"required":["resource"]}"""),
    };

    // Toy catalog of monthly prices per SKU (USD).
    private static readonly Dictionary<string, decimal> UnitPrices = new()
    {
        ["vm-app-01"] = 142.00m,    // Standard_D2s_v5
        ["sql-db-01"] = 198.50m,    // SQL DB S2
        ["storage-logs"] = 72.00m,  // Hot LRS
    };

    // Toy tags per resource (key=value).
    private static readonly Dictionary<string, Dictionary<string, string>> ResourceTags = new()
    {
        ["vm-app-01"]    = new() { ["env"] = "prod", ["owner"] = "team-payments" },
        ["sql-db-01"]    = new() { ["env"] = "prod", ["owner"] = "team-data" },
        ["storage-logs"] = new() { ["env"] = "dev",  ["owner"] = "team-platform" },
    };

    private static object ListResources(Dictionary<string, object?> args)
        => UnitPrices.Keys.ToArray();

    private static object GetUnitPrice(Dictionary<string, object?> args)
    {
        var resource = args.GetValueOrDefault("resource")?.ToString() ?? "";
        return UnitPrices.TryGetValue(resource, out var price)
            ? new { resource, monthly_usd = price }
            : new { resource, monthly_usd = 0m, note = "unknown sku" };
    }

    private static object EstimateMonthlyCost(Dictionary<string, object?> args)
    {
        var total = UnitPrices.Values.Sum();
        return new { currency = "USD", monthly_total = total, breakdown = UnitPrices };
    }

    private static object GetSavingsRecommendations(Dictionary<string, object?> args)
    {
        // Toy recommendations: reserved instances + right-sizing.
        return new object[]
        {
            new { resource = "vm-app-01",    type = "reserved_instance", monthly_savings_usd = 48.00m,
                  detail = "RI 1 year saves 34% vs PAYG." },
            new { resource = "sql-db-01",    type = "right_sizing",      monthly_savings_usd = 55.00m,
                  detail = "Downgrade S2 -> S1, p95 CPU 18%." },
            new { resource = "storage-logs", type = "tier_change",       monthly_savings_usd = 22.00m,
                  detail = "Move blobs >30d to Cool tier." },
        };
    }

    private static object GetResourceTags(Dictionary<string, object?> args)
    {
        var resource = args.GetValueOrDefault("resource")?.ToString() ?? "";
        return ResourceTags.TryGetValue(resource, out var tags)
            ? new { resource, tags }
            : new { resource, tags = new Dictionary<string, string>(), note = "no tags" };
    }
}
