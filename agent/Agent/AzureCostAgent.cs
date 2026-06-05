using System.Diagnostics;
using CostAgent.Telemetry;

namespace CostAgent.Agent;

/// <summary>
/// Classic agent loop: reason -> act (tool) -> observe, until a final answer.
/// Each step opens its own OTel span. When done it returns the full trajectory,
/// which is what DeepEval will evaluate.
/// </summary>
public sealed class AzureCostAgent(Func<ILlmClient> llmFactory)
{
    private const int MaxSteps = 12;

    public CaseTrajectory Run(string id, string input, List<string> expectedTools, int tokenBudget)
    {
        var llm = llmFactory();
        var sw = Stopwatch.StartNew();
        using var agentSpan = AgentTelemetry.Start("agent.invoke", AgentTelemetry.SpanKind.Agent);
        agentSpan.RecordInput(input);

        var history = new List<ToolObservation>();
        var toolsCalled = new List<ToolCallRecord>();
        int promptTokens = 0, completionTokens = 0;
        string finalAnswer = "(no answer)";

        for (var i = 0; i < MaxSteps; i++)
        {
            using var llmSpan = AgentTelemetry.Start("llm.decide", AgentTelemetry.SpanKind.Llm);
            var decision = llm.Decide(input, history);
            promptTokens += decision.PromptTokens;
            completionTokens += decision.CompletionTokens;
            llmSpan.RecordTokens(decision.PromptTokens, decision.CompletionTokens);

            if (decision.IsFinal)
            {
                finalAnswer = decision.FinalAnswer!;
                llmSpan.RecordOutput(finalAnswer);
                break;
            }

            llmSpan.RecordOutput(new { tool = decision.ToolName, args = decision.ToolArgs });

            var name = decision.ToolName!;
            var args = decision.ToolArgs ?? new();

            using var toolSpan = AgentTelemetry.Start($"tool.{name}", AgentTelemetry.SpanKind.Tool);
            toolSpan?.SetTag("tool.name", name);
            toolSpan.RecordInput(args);

            object? output = Tools.Registry.TryGetValue(name, out var fn)
                ? fn(args)
                : new { error = $"unknown tool '{name}'" };

            toolSpan.RecordOutput(output);
            history.Add(new ToolObservation(name, output));
            toolsCalled.Add(new ToolCallRecord(name, args, output));
        }

        agentSpan.RecordOutput(finalAnswer);
        sw.Stop();

        var tokens = new TokenUsage(promptTokens, completionTokens, promptTokens + completionTokens);
        return new CaseTrajectory(id, input, finalAnswer, expectedTools, toolsCalled,
                                  tokens, tokenBudget, sw.ElapsedMilliseconds,
                                  TraceId: agentSpan?.TraceId.ToHexString(),
                                  SpanId: agentSpan?.SpanId.ToHexString());
    }
}
