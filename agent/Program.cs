using CostAgent.Agent;
using CostAgent.Telemetry;
using DotNetEnv;
using OpenTelemetry;
using OpenTelemetry.Exporter;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

// Load .env from the repo root (one level above the binary cwd, or cwd if
// invoked from the root). Variables: AZURE_OPENAI_ENDPOINT,
// AZURE_OPENAI_API_KEY, AZURE_DEPLOYMENT_NAME, USE_REAL_LLM (YES/NO).
foreach (var candidate in new[] { ".env", "../.env", "../../.env", "../../../.env", "../../../../.env" })
{
    if (File.Exists(candidate)) { Env.Load(candidate); break; }
}

var otlpEndpoint = Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
                   ?? "http://localhost:6006/v1/traces";

using var tracerProvider = Sdk.CreateTracerProviderBuilder()
    .SetResourceBuilder(ResourceBuilder.CreateDefault()
        .AddService("azure-cost-agent")
        .AddAttributes(new[]
        {
            // Phoenix uses this attribute to route spans to a project.
            new KeyValuePair<string, object>("openinference.project.name", "azure-cost-agent"),
        }))
    .AddSource(AgentTelemetry.SourceName)
    .AddOtlpExporter(o =>
    {
        o.Endpoint = new Uri(otlpEndpoint);
        o.Protocol = OtlpExportProtocol.HttpProtobuf;
    })
    .Build();

var outPath = args.FirstOrDefault(a => !a.StartsWith("--")) ?? "trajectory.json";
var interactive = args.Contains("--interactive") || args.Contains("-i");

// -------- LLM client selection --------
var useReal = (Environment.GetEnvironmentVariable("USE_REAL_LLM") ?? "").ToUpperInvariant()
                is "YES" or "TRUE" or "1";
var endpoint = Environment.GetEnvironmentVariable("AZURE_OPENAI_ENDPOINT");
var apiKey = Environment.GetEnvironmentVariable("AZURE_OPENAI_API_KEY");
var deployment = Environment.GetEnvironmentVariable("AZURE_DEPLOYMENT_NAME") ?? "gpt-4o-mini";

Func<ILlmClient> llmFactory;
string modelName;
if (useReal && !string.IsNullOrWhiteSpace(endpoint) && !string.IsNullOrWhiteSpace(apiKey))
{
    Console.WriteLine($"[LLM] Real: Azure OpenAI deployment '{deployment}' @ {endpoint}");
    llmFactory = () => new AzureOpenAiLlmClient(endpoint!, apiKey!, deployment);
    modelName = $"azure-openai:{deployment}";
}
else
{
    Console.WriteLine("[LLM] Deterministic mock (set USE_REAL_LLM=YES to use Azure OpenAI)");
    llmFactory = () => new MockLlmClient();
    modelName = "mock-deterministic";
}

var agent = new AzureCostAgent(llmFactory);

if (interactive)
{
    Console.WriteLine();
    Console.WriteLine("======================================================================");
    Console.WriteLine(" Interactive mode. Each prompt = one new trace in Phoenix and one new");
    Console.WriteLine(" case appended to the trajectory file. Type 'exit' (or Ctrl-C) to quit.");
    Console.WriteLine($" Trajectory file: {Path.GetFullPath(outPath)}");
    Console.WriteLine($" Phoenix UI:      http://127.0.0.1:6006");
    Console.WriteLine("======================================================================");

    var turn = 0;
    while (true)
    {
        Console.WriteLine();
        Console.Write("you> ");
        var input = Console.ReadLine();
        if (input is null) break;
        input = input.Trim();
        if (input.Length == 0) continue;
        if (input.Equals("exit", StringComparison.OrdinalIgnoreCase)
            || input.Equals("quit", StringComparison.OrdinalIgnoreCase)) break;

        turn++;
        var caseId = $"live-{DateTime.UtcNow:yyyyMMdd-HHmmss}-{turn:D3}";

        CaseTrajectory result;
        try
        {
            result = agent.Run(
                id: caseId,
                input: input,
                expectedTools: new List<string>(),  // unknown for free-form prompts
                tokenBudget: 8000);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[error] {ex.Message}");
            continue;
        }

        Console.WriteLine();
        Console.WriteLine($"agent> {result.ActualOutput}");
        Console.WriteLine($"       (tools={result.ToolsCalled.Count} tokens={result.Tokens.Total} {result.LatencyMs} ms  trace={result.TraceId})");

        TrajectoryFile.AppendCase(outPath, "azure-cost-agent", modelName, result);
    }

    Console.WriteLine("Bye.");
    return;
}

var cases = new List<CaseTrajectory>
{
    agent.Run(
        id: "cost-001",
        input: "How much does this subscription cost per month?",
        expectedTools: ["list_resources", "get_unit_price", "estimate_monthly_cost"],
        tokenBudget: 6000),

    agent.Run(
        id: "cost-002",
        input: "Which is the most expensive resource?",
        expectedTools: ["list_resources", "get_unit_price"],
        tokenBudget: 4000),

    agent.Run(
        id: "cost-003",
        input: "Give me savings recommendations for this subscription.",
        expectedTools: ["list_resources", "get_savings_recommendations"],
        tokenBudget: 4000),

    agent.Run(
        id: "cost-004",
        input: "Which resources have the tag env=prod?",
        expectedTools: ["list_resources", "get_resource_tags"],
        tokenBudget: 6000),
};

var file = new TrajectoryFile(
    SchemaVersion: "1.0",
    Agent: "azure-cost-agent",
    Model: modelName,
    Cases: cases);

file.WriteTo(outPath);

Console.WriteLine();
Console.WriteLine($"Trajectory written to: {Path.GetFullPath(outPath)}");
foreach (var c in cases)
    Console.WriteLine($"  [{c.Id}] tools={c.ToolsCalled.Count} tokens={c.Tokens.Total} ({c.LatencyMs} ms)");
