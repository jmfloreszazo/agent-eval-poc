using System.Diagnostics;

namespace CostAgent.Telemetry;

/// <summary>
/// Single instrumentation entry point. Uses OpenInference conventions (the
/// same ones Arize Phoenix understands) on top of plain OpenTelemetry, so the
/// trace works for self-hosted Phoenix or any OTLP backend (Tempo, Jaeger,
/// Aspire Dashboard, etc.).
/// </summary>
public static class AgentTelemetry
{
    public const string SourceName = "AzureCostAgent";

    public static readonly ActivitySource Source = new(SourceName, "1.0.0");

    public enum SpanKind { Agent, Llm, Tool }

    public static Activity? Start(string name, SpanKind kind)
    {
        var activity = Source.StartActivity(name, ActivityKind.Internal);
        // Key OpenInference attribute: span kind (AGENT / LLM / TOOL).
        activity?.SetTag("openinference.span.kind", kind.ToString().ToUpperInvariant());
        return activity;
    }

    public static void RecordInput(this Activity? a, object? value)
        => a?.SetTag("input.value", Serialize(value));

    public static void RecordOutput(this Activity? a, object? value)
        => a?.SetTag("output.value", Serialize(value));

    public static void RecordTokens(this Activity? a, int prompt, int completion)
    {
        a?.SetTag("llm.token_count.prompt", prompt);
        a?.SetTag("llm.token_count.completion", completion);
        a?.SetTag("llm.token_count.total", prompt + completion);
    }

    private static string Serialize(object? value)
        => value switch
        {
            null => string.Empty,
            string s => s,
            _ => System.Text.Json.JsonSerializer.Serialize(value)
        };
}
