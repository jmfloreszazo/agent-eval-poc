namespace CostAgent.Agent;

public record ToolObservation(string ToolName, object? Output);

/// <summary>A single decision from the agent "brain" within the loop.</summary>
public record LlmDecision(
    string? ToolName,
    Dictionary<string, object?>? ToolArgs,
    string? FinalAnswer,
    int PromptTokens,
    int CompletionTokens)
{
    public bool IsFinal => FinalAnswer is not null;
}

public interface ILlmClient
{
    LlmDecision Decide(string input, IReadOnlyList<ToolObservation> history);
}

/// <summary>
/// Deterministic mock: no network, no API key, no cost. Lets the eval suite
/// run in CI for free and reproducibly (key for FinOps). For production swap
/// it for an Azure OpenAI / Microsoft.Extensions.AI client implementing the
/// same interface; the rest of the agent stays the same.
/// </summary>
public sealed class MockLlmClient : ILlmClient
{
    public LlmDecision Decide(string input, IReadOnlyList<ToolObservation> history)
    {
        var step = history.Count;
        var lower = input.ToLowerInvariant();
        var wantsSavings = lower.Contains("saving") || lower.Contains("recommend");
        var wantsTags    = lower.Contains("tag") || lower.Contains("prod");
        var wantsTotal   = lower.Contains("cost") || lower.Contains("month") || lower.Contains("bill");

        // Plan C (savings): list -> savings -> answer
        if (wantsSavings)
        {
            return step switch
            {
                0 => Tool("list_resources", new()),
                1 => Tool("get_savings_recommendations", new()),
                _ => Final("Total estimated savings $125.00/month: RI vm-app-01 $48.00, "
                         + "right-sizing sql-db-01 $55.00, cool tier storage-logs $22.00."),
            };
        }

        // Plan D (tags=prod): list -> tags(each) -> answer
        if (wantsTags)
        {
            return step switch
            {
                0 => Tool("list_resources", new()),
                1 => Tool("get_resource_tags", new() { ["resource"] = "vm-app-01" }),
                2 => Tool("get_resource_tags", new() { ["resource"] = "sql-db-01" }),
                3 => Tool("get_resource_tags", new() { ["resource"] = "storage-logs" }),
                _ => Final("Resources tagged env=prod: vm-app-01 and sql-db-01."),
            };
        }

        // Plan A (total cost): list -> price(each) -> estimate -> answer
        if (wantsTotal)
        {
            return step switch
            {
                0 => Tool("list_resources", new()),
                1 => Tool("get_unit_price", new() { ["resource"] = "vm-app-01" }),
                2 => Tool("get_unit_price", new() { ["resource"] = "sql-db-01" }),
                3 => Tool("get_unit_price", new() { ["resource"] = "storage-logs" }),
                4 => Tool("estimate_monthly_cost", new()),
                _ => Final("Estimated monthly subscription cost is $412.50 USD: "
                         + "vm-app-01 $142.00, sql-db-01 $198.50, storage-logs $72.00."),
            };
        }

        // Plan B (most expensive resource): list -> price -> answer
        return step switch
        {
            0 => Tool("list_resources", new()),
            1 => Tool("get_unit_price", new() { ["resource"] = "sql-db-01" }),
            _ => Final("The most expensive resource is sql-db-01 at $198.50 USD/month."),
        };
    }

    private static LlmDecision Tool(string name, Dictionary<string, object?> args)
        => new(name, args, null, PromptTokens: 80, CompletionTokens: 20);

    private static LlmDecision Final(string answer)
        => new(null, null, answer, PromptTokens: 110, CompletionTokens: 45);
}
