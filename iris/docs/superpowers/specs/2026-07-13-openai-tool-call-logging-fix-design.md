# OpenAI Tool-Call Logging Fix Design

## Problem

OpenAI-compatible chat completions commonly represent a tool request with an empty or absent textual `content` field and a non-empty `tool_calls` field. `OpenAIChatModel.chat()` currently logs every response with empty textual content as an error before converting it. The conversion path correctly accepts tool-call responses, so normal agent runs emit misleading error records and then complete successfully.

## Scope

Change only the classification of empty responses in the OpenAI chat adapter. A response is unexpectedly empty when its message is absent, or when its textual content is empty and it contains no tool calls. A message containing tool calls is valid regardless of whether textual content is `None` or an empty string.

The change must not alter conversion, retries, tool execution, or handling of `length`, refusals, `content_filter`, and absent messages.

## Implementation

Update the existing empty-message diagnostic guard in `src/iris/llm/external/openai_chat.py` to exempt messages with non-empty `tool_calls`. Valid tool-call responses continue through the existing `convert_to_iris_message()` function and become `PyrisAIMessage` instances.

Do not add replacement informational logging. The agent loop already logs each executed tool call, so another adapter-level record would be redundant.

## Tests

Add focused adapter tests using the project's existing mocked OpenAI client conventions:

1. A tool-call completion with `content=None` returns a `PyrisAIMessage` and does not log `Model returned an empty message` or its finish reason at error level.
2. A tool-call completion with `content=""` has the same behavior.
3. An empty completion with no tool calls still emits the existing empty-message and finish-reason error diagnostics.

Tests will verify both the returned message shape and captured error records. Python commands will run through Poetry.

## Acceptance Criteria

- Normal tool-call completions no longer emit empty-message error records.
- Tool calls are preserved and converted exactly as before.
- Unexpected empty responses retain existing diagnostics.
- Focused tests and the applicable Iris lint/format checks pass.
