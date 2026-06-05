using System.ClientModel;
using System.Text.Json;
using Azure.AI.OpenAI;
using OpenAI.Chat;

namespace CostAgent.Agent;

/// <summary>
/// Real LLM client against Azure OpenAI using function calling. Keeps the
/// conversation state per instance (one per case): system + user +
/// (assistant tool_call -> tool result)*  -> final assistant message.
/// </summary>
public sealed class AzureOpenAiLlmClient : ILlmClient
{
    private const string SystemPrompt = """
        You are an Azure FinOps agent. Your job is to answer questions about
        cost, resources, savings and tags of a subscription using ONLY the
        available tools.

        Mandatory procedure:
        1. ALWAYS call `list_resources` first to discover what exists.
        2. For cost questions: call `get_unit_price` for every resource, then
           `estimate_monthly_cost` to obtain the total.
        3. To find the most expensive resource: call `get_unit_price` for every
           resource returned by `list_resources` and compare; do not guess.
        4. For savings questions: call `get_savings_recommendations` AFTER
           `list_resources` so the answer is grounded on real inventory.
        5. For tag questions: call `get_resource_tags` for every candidate
           resource.

        Rules:
        - Never invent prices, resources or recommendations.
        - Always answer in English. Use US dollars (USD, $) for any monetary
          figure.
        - The final answer must directly address the user's question in the
          first sentence (e.g. "The most expensive resource is X at $Y/month"),
          then optionally one short sentence of context. Do not list steps.
        """;

    private readonly ChatClient _chat;
    private readonly ChatCompletionOptions _options;
    private readonly List<ChatMessage> _messages = new();
    private string? _pendingToolCallId;

    public AzureOpenAiLlmClient(string endpoint, string apiKey, string deployment)
    {
        var client = new AzureOpenAIClient(new Uri(endpoint), new ApiKeyCredential(apiKey));
        _chat = client.GetChatClient(deployment);

        _options = new ChatCompletionOptions
        {
            Temperature = 0.0f,
            AllowParallelToolCalls = false,
        };
        foreach (var spec in Tools.Specs)
        {
            _options.Tools.Add(ChatTool.CreateFunctionTool(
                functionName: spec.Name,
                functionDescription: spec.Description,
                functionParameters: BinaryData.FromString(spec.JsonSchema)));
        }
        _messages.Add(new SystemChatMessage(SystemPrompt));
    }

    public LlmDecision Decide(string input, IReadOnlyList<ToolObservation> history)
    {
        // First turn: append the user message.
        if (history.Count == 0)
            _messages.Add(new UserChatMessage(input));

        // Subsequent turns: append the result of the last executed tool.
        if (_pendingToolCallId is not null && history.Count > 0)
        {
            var lastObs = history[^1];
            var payload = JsonSerializer.Serialize(lastObs.Output);
            _messages.Add(new ToolChatMessage(_pendingToolCallId, payload));
            _pendingToolCallId = null;
        }

        ChatCompletion response = _chat.CompleteChat(_messages, _options);

        var prompt = response.Usage?.InputTokenCount ?? 0;
        var completion = response.Usage?.OutputTokenCount ?? 0;

        // If the model chose to call a tool, propagate that decision.
        if (response.FinishReason == ChatFinishReason.ToolCalls && response.ToolCalls.Count > 0)
        {
            // Keep the assistant message with the tool_call for the next turn.
            _messages.Add(new AssistantChatMessage(response));

            var call = response.ToolCalls[0];
            _pendingToolCallId = call.Id;

            Dictionary<string, object?> args;
            try
            {
                args = JsonSerializer.Deserialize<Dictionary<string, object?>>(
                           call.FunctionArguments.ToString()) ?? new();
            }
            catch
            {
                args = new();
            }

            return new LlmDecision(
                ToolName: call.FunctionName,
                ToolArgs: args,
                FinalAnswer: null,
                PromptTokens: prompt,
                CompletionTokens: completion);
        }

        // Final answer.
        var text = response.Content.Count > 0 ? response.Content[0].Text : "(no answer)";
        return new LlmDecision(
            ToolName: null,
            ToolArgs: null,
            FinalAnswer: text,
            PromptTokens: prompt,
            CompletionTokens: completion);
    }
}
