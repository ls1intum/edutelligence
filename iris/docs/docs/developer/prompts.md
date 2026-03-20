---
title: Prompts
---

# Prompts

Prompts define how Iris communicates with LLMs. They establish the AI tutor's personality, pedagogical approach, and task-specific behavior. Iris uses a combination of Jinja2 templates and Python prompt builders.

## Prompt Location

All prompts live under `src/iris/pipeline/prompts/`:

```
prompts/
├── templates/                                 # Jinja2 templates for system prompts
│   ├── exercise_chat_system_prompt.j2
│   ├── exercise_chat_guide_prompt.j2
│   ├── course_chat_system_prompt.j2
│   ├── lecture_chat_system_prompt.j2
│   ├── text_exercise_chat_system_prompt.j2
│   ├── autonomous_tutor_system_prompt.j2
│   ├── tutor_suggestion_chat_system_prompt.j2
│   └── session_title_generation_prompt.j2
├── code_feedback_prompt.txt                   # Plain text prompt for code feedback
├── citation_prompt.txt                        # Citation generation prompt
├── citation_keyword_prompt.txt                # Citation keyword extraction
├── citation_summary_prompt.txt                # Citation summary generation
├── summary_prompt.txt                         # General summarization
├── competency_extraction.py                   # Python prompt builder
├── faq_consistency_prompt.py                  # FAQ consistency check prompts
├── faq_retrieval_prompts.py                   # FAQ retrieval query rewriting
├── inconsistency_check_prompts.py             # Inconsistency check prompts
├── iris_interaction_suggestion_prompts.py     # Follow-up question suggestions
├── lecture_retrieval_prompts.py               # Lecture RAG query rewriting
├── lecture_unit_summary_prompt.py             # Lecture unit summarization
├── lecture_unit_segment_summary_prompt.py     # Lecture segment summarization
├── rewriting_prompts.py                       # Content rewriting prompts
└── transcription_ingestion_prompts.py         # Transcription processing prompts
```

## Jinja2 Templates

The main chat pipelines use **Jinja2 templates** (`.j2` files) for their system prompts. These templates support variable interpolation using `{{ variable }}` syntax.

### Example: Exercise Chat System Prompt

From `templates/exercise_chat_system_prompt.j2`:

```
Current Date: {{ current_date }}

You're Iris, the proactive AI programming tutor integrated into Artemis,
the online learning platform of the Technical University of Munich (TUM).

Instead of guessing or asking the student for information, you have to
use the available tools to look up the necessary data...
```

The template receives variables from the pipeline's `build_system_message()` method:

```python
def build_system_message(self, state):
    return self.system_prompt_template.render(
        current_date=datetime_to_string(datetime.now(pytz.utc)),
        # ... other variables
    )
```

### Loading Templates

Pipelines load Jinja2 templates in their `__init__`. Since chat pipelines live in `pipeline/chat/`, the path navigates up to the `prompts/templates/` directory:

```python
from jinja2 import Environment, FileSystemLoader, select_autoescape

# From a chat pipeline in pipeline/chat/
template_dir = os.path.join(os.path.dirname(__file__), "..", "prompts", "templates")
self.jinja_env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(["j2"]),
)
self.system_prompt_template = self.jinja_env.get_template(
    "exercise_chat_system_prompt.j2"
)
```

Pipelines that live directly in `pipeline/` (like `SessionTitleGenerationPipeline`) use a simpler path without the `..`.

## Python Prompt Builders

Some prompts are constructed in Python files, typically as functions that return prompt strings or `ChatPromptTemplate` objects. These are used for sub-pipelines and retrieval operations.

For example, `lecture_retrieval_prompts.py` defines prompt strings for query rewriting during RAG:

```python
# From lecture_retrieval_prompts.py
lecture_retriever_initial_prompt_lecture_pages = """
You write good and performant vector database queries, in particular for Weaviate,
from chat histories between an AI tutor and a student.
The query should be designed to retrieve context information from indexed lecture slides...
"""
```

## Plain Text Prompts

Simple, single-purpose prompts use `.txt` files with placeholder variables in `{curly_braces}`:

```text title="code_feedback_prompt.txt"
Exercise Problem Statement:
{problem_statement}

Chat History:
{chat_history}

User question:
{question}

Feedbacks (from automated tests):
{feedbacks}
...
```

These are loaded and formatted using Python's `str.format()` or passed directly to LangChain prompt templates.

## How Prompts Are Assembled

In `AbstractAgentPipeline`, the full prompt is assembled in two steps:

### 1. System Message Construction

Each pipeline implements `build_system_message()` to produce the system prompt string:

```python
def build_system_message(self, state):
    # Render the Jinja2 template with context
    return self.system_prompt_template.render(
        current_date=...,
        custom_instructions=...,
        # ... pipeline-specific variables
    )
```

### 2. History and Scratchpad Assembly

The `assemble_prompt_with_history()` method combines the system message with chat history and the agent scratchpad:

```python
def assemble_prompt_with_history(self, state, system_prompt):
    prefix_messages = [
        ("system", system_prompt.replace("{", "{{").replace("}", "}}"))
    ]
    history_lc_messages = [
        convert_iris_message_to_langchain_message(msg)
        for msg in state.message_history
    ]
    combined = (
        prefix_messages
        + history_lc_messages
        + [("placeholder", "{agent_scratchpad}")]
    )
    return ChatPromptTemplate.from_messages(combined)
```

:::note
The `{` and `}` characters in the system prompt are escaped to `{{` and `}}` to prevent LangChain from interpreting them as template variables. Only `{agent_scratchpad}` remains as a true placeholder.
:::

## Prompt Design Patterns

### Pedagogical Guidelines

Chat prompts consistently enforce these pedagogical principles:

- **Do not solve exercises for students** — guide them toward discovering solutions independently.
- **Use tools proactively** — look up submission data, build logs, and feedback instead of asking the student.
- **Provide hints, not answers** — give clues and best practices to direct the student's attention.
- **Adjust help level** — gradually increase assistance if the student is stuck.
- **Respect academic integrity** — never provide code that can be directly copied into the exercise.

### Context Injection

Prompts use several patterns to inject runtime context:

| Pattern          | Example                                 | Used For                                     |
| ---------------- | --------------------------------------- | -------------------------------------------- |
| Jinja2 variables | `{{ current_date }}`                    | Date, custom instructions, exercise metadata |
| Chat history     | Converted to LangChain messages         | Prior conversation turns                     |
| Tool results     | Injected by agent scratchpad            | Data retrieved during execution              |
| Guide prompts    | Separate template rendered and appended | Detailed behavioral instructions             |

### Custom Instructions

Instructors can provide custom instructions that are injected into the system prompt. These are formatted and included via the `format_custom_instructions()` utility from `pipeline/shared/utils.py`.
