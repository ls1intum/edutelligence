---
title: Tools
---

# Tools

Tools are functions that the LLM agent can call during a conversation to retrieve information or perform actions. They are the primary mechanism by which Iris agents access student data, course content, and exercise context.

## How Tools Work

Each tool follows the **factory pattern**: a `create_tool_*` function takes context parameters (DTOs, callbacks, etc.) and returns a **closure** — a zero-argument or minimal-argument function that the agent can invoke. The closure's docstring serves as the tool description that the LLM sees.

```python
# Pattern: Factory function returns a closure
def create_tool_repository_files(
    repository: Optional[Dict[str, str]], callback: StatusCallback
) -> Callable[[], str]:

    def repository_files() -> str:
        """
        List files in the student's code submission repository.
        ...
        """
        callback.in_progress("Checking repository content ...")
        if not repository:
            return "No repository content available."
        return "\n".join(f"- {name}" for name in repository.keys())

    return repository_files
```

The agent sees only the inner function's **name** and **docstring**. The outer factory function handles dependency injection (repository data, callbacks, retrieval pipelines, etc.).

## Tool Catalog

### Exercise & Submission Tools

| Tool                                | File                                   | Description                                                 |
| ----------------------------------- | -------------------------------------- | ----------------------------------------------------------- |
| `repository_files`                  | `repository_files.py`                  | List all files in the student's submission repository       |
| `file_lookup`                       | `file_lookup.py`                       | Read the contents of a specific file from the repository    |
| `get_submission_details`            | `submission_details.py`                | Get submission metadata (date, practice mode, build status) |
| `get_feedbacks`                     | `feedbacks.py`                         | Retrieve automated test feedback for the submission         |
| `get_build_logs_analysis`           | `build_logs_analysis.py`               | Analyze build/compilation logs                              |
| `get_additional_exercise_details`   | `additional_exercise_details.py`       | Get exercise due dates, bonus points, difficulty            |
| `exercise_problem_statement`        | `exercise_problem_statement.py`        | Retrieve the exercise problem statement                     |
| `single_exercise_problem_statement` | `single_exercise_problem_statement.py` | Get a specific exercise's problem statement                 |
| `exercise_example_solution`         | `exercise_example_solution.py`         | Get the example solution (when available)                   |
| `last_artifact`                     | `last_artifact.py`                     | Get the last CI/CD build artifact                           |

### Course & Content Tools

| Tool                        | File                           | Description                                                             |
| --------------------------- | ------------------------------ | ----------------------------------------------------------------------- |
| `lecture_content_retrieval` | `lecture_content_retrieval.py` | RAG retrieval from indexed lecture slides, transcriptions, and segments |
| `faq_content_retrieval`     | `faq_content_retrieval.py`     | RAG retrieval from indexed FAQ entries                                  |
| `exercise_list`             | `exercise_list.py`             | List all exercises in the course, with their IDs and types              |
| `course_details`            | `course_details.py`            | Get course metadata                                                     |
| `course_simple_details`     | `course_simple_details.py`     | Get simplified course information                                       |
| `competency_list`           | `competency_list.py`           | List course competencies and their descriptions                         |

### Student Analytics Tools

| Tool                       | File                          | Description                                      |
| -------------------------- | ----------------------------- | ------------------------------------------------ |
| `student_exercise_metrics` | `student_exercise_metrics.py` | Get student performance metrics across exercises |

## How Agents Select Tools

When `AbstractAgentPipeline` runs, it calls the pipeline's `get_tools()` method to get a list of tool closures. These are converted to LangChain `StructuredTool` objects via `generate_structured_tools_from_functions()` in `pipeline/shared/utils.py`.

The LangChain `create_tool_calling_agent` then formats the tool schemas (name, description, parameters) as part of the LLM prompt. The LLM decides which tools to call based on the conversation context and the tool descriptions.

```python
# From abstract_agent_pipeline.py
def _create_agent_executor(self, llm, prompt, tool_functions):
    tools = generate_structured_tools_from_functions(tool_functions)
    agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)
    return agent_executor, tools
```

The agent loop iterates: the LLM outputs a tool call, the executor runs the tool function, feeds the result back to the LLM, and repeats until the LLM produces a final text response.

## Tool Providers

`ChatPipeline` serves every chat mode, so it cannot hardcode a tool list. It resolves one per request from the **tool providers** in `tools/chat_tool_providers.py`.

A provider is a function that takes the pipeline state and returns either a ready tool closure or `None`. It owns one decision: whether this tool is useful for this request. It checks the preconditions, pulls the parameters out of the DTO, and delegates to the `create_tool_*` factory:

```python
State = AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant]


def provide_repository_files(state: State) -> Callable[[], str] | None:
    if not state.dto.programming_exercise_submission:
        return None
    return create_tool_repository_files(
        state.dto.programming_exercise_submission.repository, state.callback
    )
```

The providers are registered in one list, and `get_tools()` is a loop over it:

```python
CHAT_TOOL_PROVIDERS: list[Callable[[State], Optional[Callable]]] = [
    provide_lecture_retrieval,
    provide_lecture_list,
    provide_faq_retrieval,
    provide_course_details,
    ...
]


def get_tools(self, state) -> list[Callable]:
    tools = []
    for provider in CHAT_TOOL_PROVIDERS:
        tool = provider(state)
        if tool is not None:
            tools.append(tool)
    return tools
```

### What Providers Decide On

Most providers gate on **data availability** rather than on the chat mode. A missing programming submission removes the repository and build-log tools whether or not the mode says `PROGRAMMING_EXERCISE_CHAT`, and the exercise list stays available in every mode because the course DTO always carries it.

Three providers gate on flags that `ChatPipeline.prepare_state()` computes once per request:

| Flag                 | Set from                                                | Gates                                                    |
| -------------------- | ------------------------------------------------------- | -------------------------------------------------------- |
| `allow_lecture_tool` | `should_allow_lecture_tool()` — indexed lecture content | `provide_lecture_retrieval`, `provide_lecture_list`      |
| `allow_faq_tool`     | `should_allow_faq_tool()` — indexed FAQ entries         | `provide_faq_retrieval`                                  |
| `allow_memiris_tool` | User opt-in and existing memories                       | `provide_memory_search`, `provide_find_similar_memories` |

`prepare_state()` exists because the first two are Weaviate round trips that both the system prompt and the tool list depend on. Resolving them once, concurrently, before either is built avoids querying twice per request.

One provider bypasses the whole mechanism: when `prepare_state()` detects MCQ intent, `get_tools()` returns an empty list, because the agent only has to write a short intro while the MCQ sub-pipeline runs in parallel.

## Creating a New Tool

1. **Create the file** in `src/iris/tools/your_tool.py`.

2. **Write the factory function** following the pattern:

```python
def create_tool_your_feature(
    data: YourDataType,
    callback: StatusCallback,
) -> Callable[[], str]:

    def your_feature() -> str:
        """
        Clear description of what this tool does.
        The LLM reads this docstring to decide when to use the tool.
        Be specific about what information is returned.
        """
        callback.in_progress("Fetching your feature data...")
        # Process data and return a string
        return format_result(data)

    return your_feature
```

3. **Export it** from `src/iris/tools/__init__.py`.

4. **Add a provider** in `src/iris/tools/chat_tool_providers.py` and append it to `CHAT_TOOL_PROVIDERS`:

```python
def provide_your_feature(state: State) -> Optional[Callable]:
    if not state.dto.your_required_field:
        return None
    return create_tool_your_feature(state.dto.your_required_field, state.callback)
```

Return `None` whenever the tool would be useless. An agent that sees a tool and gets "no data available" back has wasted a round trip and learned nothing.

Pipelines other than `ChatPipeline` still build their tool list inside their own `get_tools()`.

:::tip Tool Docstring Quality
The tool's inner function docstring is critical — it is the only information the LLM has to decide whether to call the tool. Write clear, specific descriptions of what information the tool returns and when it should be used.
:::

:::warning Return Types
Tools should return **strings** or simple **dicts**. The return value is serialized and injected into the LLM's context, so keep it concise. Avoid returning large data structures that would consume too many tokens.
:::
