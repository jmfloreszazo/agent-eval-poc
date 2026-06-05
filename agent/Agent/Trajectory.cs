using System.Text.Json;
using System.Text.Json.Serialization;

namespace CostAgent.Agent;

// ----------------------------------------------------------------------------
//  TRAJECTORY CONTRACT  (bridge .NET <-> Python)
//  Serialized as snake_case so the Python side consumes it without weird
//  mappings. This is the only boundary between both layers: the agent knows
//  nothing about DeepEval, and DeepEval knows nothing about .NET.
// ----------------------------------------------------------------------------

public record ToolCallRecord(
    string Name,
    Dictionary<string, object?> InputParameters,
    object? Output);

public record TokenUsage(int Prompt, int Completion, int Total);

public record CaseTrajectory(
    string Id,
    string Input,
    string ActualOutput,
    List<string> ExpectedTools,
    List<ToolCallRecord> ToolsCalled,
    TokenUsage Tokens,
    int TokenBudget,
    long LatencyMs,
    string? TraceId = null,
    string? SpanId = null);

public record TrajectoryFile(
    string SchemaVersion,
    string Agent,
    string Model,
    List<CaseTrajectory> Cases)
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };

    public void WriteTo(string path)
        => File.WriteAllText(path, JsonSerializer.Serialize(this, Options));

    /// <summary>
    /// Append a new case to an existing trajectory file (or create it if missing).
    /// Used by the interactive REPL so each user turn becomes a new case
    /// the evaluator can pick up on the next pass.
    /// </summary>
    public static void AppendCase(string path, string agent, string model, CaseTrajectory @case)
    {
        TrajectoryFile file;
        if (File.Exists(path))
        {
            file = JsonSerializer.Deserialize<TrajectoryFile>(File.ReadAllText(path), Options)
                   ?? new TrajectoryFile("1.0", agent, model, new());
            file.Cases.Add(@case);
        }
        else
        {
            file = new TrajectoryFile("1.0", agent, model, new() { @case });
        }
        file.WriteTo(path);
    }
}
