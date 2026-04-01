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
| `exercise_list`             | `exercise_list.py`             | List all exercises in the course                                        |
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

## Example: How Tools Are Loaded

Here is a simplified example from `ExerciseChatAgentPipeline.get_tools()`:

```python
def get_tools(self, state: AgentPipelineExecutionState) -> list[Callable]:
    tools = [
        create_tool_repository_files(dto.submission.repository, callback),
        create_tool_file_lookup(dto.submission.repository, callback),
        create_tool_get_submission_details(dto.submission, callback),
        create_tool_get_feedbacks(dto.submission, callback),
        create_tool_get_build_logs_analysis(dto.submission, callback),
        create_tool_get_additional_exercise_details(dto.exercise, callback),
    ]

    # Conditionally add RAG tools
    if should_allow_lecture_tool(dto):
        tools.append(create_tool_lecture_content_retrieval(
            lecture_retriever, course_id, base_url, callback, query, history, storage
        ))

    if should_allow_faq_tool(dto):
        tools.append(create_tool_faq_content_retrieval(...))

    return tools
```

Different pipelines provide different tool sets. For example:

- **Exercise chat** gets submission, feedback, build log, repository, and optionally lecture/FAQ tools.
- **Course chat** gets lecture content, FAQ, exercise list, and course details tools.
- **Lecture chat** focuses on lecture content retrieval tools.

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

4. **Register it** in the relevant pipeline's `get_tools()` method.

:::tip Tool Docstring Quality
The tool's inner function docstring is critical — it is the only information the LLM has to decide whether to call the tool. Write clear, specific descriptions of what information the tool returns and when it should be used.
:::

:::warning Return Types
Tools should return **strings** or simple **dicts**. The return value is serialized and injected into the LLM's context, so keep it concise. Avoid returning large data structures that would consume too many tokens.
:::
