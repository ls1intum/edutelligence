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
│   ├── chat_system_prompt.j2                  # The system prompt of every student chat
│   ├── chat_turn_context.j2                   # Per-message viewing context, sent after the chat history
│   ├── exercise_chat_guide_prompt.j2
│   ├── mcq_generation_prompt.j2
│   ├── autonomous_tutor_system_prompt.j2
│   ├── tutor_suggestion_chat_system_prompt.j2
│   ├── chat_turn_context.j2                   # Per-message context, sent after the history
│   ├── interaction_suggestion_prompt.j2       # Follow-up question suggestions
│   └── session_title_generation_prompt.j2
├── code_feedback_prompt.txt                   # Plain text prompt for code feedback
├── citation_label_prompt.txt                  # Keyword and summary of cited sources
├── competency_extraction.py                   # Python prompt builder
├── environment.py                             # Shared Jinja2 environment (no escaping, as_data filter)
├── faq_consistency_prompt.py                  # FAQ consistency check prompts
├── inconsistency_check_prompts.py             # Inconsistency check prompts
├── lecture_unit_summary_prompt.py             # Lecture unit summarization
├── lecture_unit_segment_summary_prompt.py     # Lecture segment summarization
├── rewriting_prompts.py                       # Content rewriting prompts
└── transcription_ingestion_prompts.py         # Transcription processing prompts
```

## Jinja2 Templates

Pipelines use **Jinja2 templates** (`.j2` files) for their system prompts. These templates support variable interpolation using `{{ variable }}` syntax.

### The Chat System Prompt

`chat_system_prompt.j2` is the system prompt of every student chat, in every chat mode. One template rather than one per mode: the persona, the pedagogical guidelines and the tool instructions are identical across modes, and copies of them drift apart as soon as anyone edits only the copy they were working on.

The template is a sequence of blocks in a fixed order. Some are unconditional, others render only when the request carries the data they describe:

| Block                       | Condition                                | Content                                                                  |
| --------------------------- | ---------------------------------------- | ------------------------------------------------------------------------ |
| Role                        | always                                   | The Iris persona and its goal                                            |
| Language                    | `user_language`                          | Answer in the student's language                                         |
| How you teach               | always                                   | Teaching principles, four help steps, exact references, the course field |
| Code and academic integrity | always                                   | Self-check, no solutions, refusal rules; draft feedback by support level |
| Using your tools            | always                                   | When to call tools, preamble, tool output is data                        |
| Current context             | `lecture_name` or `exercise_id`          | The active lecture or exercise; the problem statement as data            |
| Examples                    | always                                   | Four short example exchanges                                             |
| Automatic context switching | always                                   | When and how to call `switch_chat_context`                               |
| Programming situations      | `programming_language`                   | Build failures, failing tests, code and concept questions                |
| Lecture material            | `allow_lecture_tool`                     | How to retrieve and refer to lecture content                             |
| Combined-view point-out     | `can_point_out_in_combined_view`         | How to move the slide or video the student sees                          |
| Course FAQ                  | `allow_faq_tool`                         | How to use FAQ answers                                                   |
| Citing Sources              | `allow_lecture_tool` or `allow_faq_tool` | `[src:N]` source ids after the sentences that use a source               |
| Course exercises            | always (text depends on `has_exercises`) | How to talk about the course exercises                                   |
| Check before you ask        | always                                   | Look up the student's situation before asking                            |
| Conversation history        | always                                   | How to build on earlier turns                                            |
| Quiz questions              | course and lecture modes                 | How to use `generate_mcq_questions`                                      |
| Support level               | `support_level` is `low` or `high`       | How much help the instructor allows                                      |
| Format of your answers      | always                                   | Markdown, links, silent plan before the reply                            |
| Custom instructions         | `custom_instructions`                    | The instructor's own additions                                           |

The system prompt stays the same as long as its inputs do not change (chat mode, active context, tool availability, combined view), so the provider can cache it with the history. Values that change per message are in `chat_turn_context.j2`, sent after the history: the current date, the slide or video the student has open, the current text exercise submission, and proactive build-failure and stalled-progress events.

`build_system_message()` assembles the render context from the DTO and from the flags that `prepare_state()` resolved:

```python
template_context = {
    "chat_mode": self.chat_mode,
    "support_level": _support_level(dto),
    "user_language": dto.user.lang_key,
    "course_name": dto.course.name,
    "allow_lecture_tool": state.allow_lecture_tool,
    "allow_faq_tool": state.allow_faq_tool,
    "lecture_name": dto.lecture.title if dto.lecture else None,
    "exercise_title": exercise.title if exercise else "",
    "programming_language": ...,
    "custom_instructions": format_custom_instructions(dto.custom_instructions or ""),
    ...
}
return self.system_prompt_template.render(template_context)
```

Note that most blocks key off **data presence**, not off `chat_mode`. `chat_mode` appears in exactly one place, the context switching block, where the agent has to be told which kind of context is currently active. Everything else follows from the entity fields, which keeps the prompt correct after a context switch without a special case.

### The Student's Current Position

Not every block the agent reads lives in the system prompt. Blocks whose content changes from message to message are rendered from a second template, `chat_turn_context.j2`, and sent as a system message **after** the chat history. The system prompt is the start of the cached prefix and has to stay byte-identical across the turns of a session, so a per-message value cannot live in it without invalidating that cache on every turn.

`current_view_blocks` is one of those blocks. It names the slide page or video moment the student currently has open, when the request carried a viewing context and the material at that position is indexed:

```text
The student is currently viewing page 4 of the lecture slides of the lecture unit
Concurrency (lecture unit ID: 31).
```

The block names the position but never reproduces the material at it. The agent therefore learns _where_ the student is on every turn, and learns _what is there_ only if it calls `read_students_current_position`. [Viewing context](./viewing-context.md) explains why the material is kept behind a tool, and why this block names that tool only when it was actually registered.

### The Context Switching Block

This block is what makes agent-initiated context switching work. It gives the agent the procedure rather than only the tool:

1. Find the target ID with the exercise list tool or the lecture list tool, and never guess an ID.
2. Call `switch_chat_context` with the matching mode and that ID.
3. Answer the question in the new context.

It also states when to switch back: a general or course-level question while an exercise or lecture context is active calls for `COURSE_CHAT`. The block opens with the currently active context, rendered from `chat_mode`, so the agent can tell whether the entity the student named is the active one. It is skipped in MCQ parallel mode, where the agent has no tools and only writes an intro.

The block carries a worked example per direction — switching to an exercise, and switching to another lecture and retrieving its content afterwards. Both examples spell out the ID lookup as a separate step, since the instruction to look the ID up carries most of the weight here.

### Loading Templates

All pipelines load templates through one shared Jinja environment, `prompt_environment()` in `pipeline/prompts/environment.py`:

```python
from iris.pipeline.prompts.environment import prompt_environment

self.jinja_env = prompt_environment()
self.system_prompt_template = self.jinja_env.get_template("chat_system_prompt.j2")
```

The environment turns HTML escaping **off**. Prompts are plain text for a model, not HTML: with escaping on, code in a student's submission or an instructor's problem statement reached the model as `&lt;`, `&gt;` and `&#39;`, which changes the meaning of code such as `if (a < b)`.

Text that comes from students or instructors goes through the `as_data` filter instead:

```jinja
{{ problem_statement | as_data("problem_statement") }}
```

`as_data` puts the text inside `<problem_statement>` tags and breaks any closing tag of the same name inside the text, so the text cannot close the block early and pose as instructions. The system prompt also tells the model that everything tools return, including the student's code, is material to work with and not instructions to follow.

## Python Prompt Builders

Some prompts are constructed in Python files, typically as functions that return prompt strings or `ChatPromptTemplate` objects. These are used for sub-pipelines and retrieval operations.

For example, `faq_consistency_prompt.py` defines the prompt strings of the FAQ consistency check.

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

Two prompts carry a wire format: the "Citing Sources" block of `chat_system_prompt.j2` tells the agent to copy source ids exactly as `[src:N]`, and `citation_label_prompt.txt` forbids the characters that delimit a cite block's fields. See [citations](./citations.md).

## How Prompts Are Assembled

`AbstractAgentPipeline.build_prompt_messages()` builds the message list for the agent loop in this order:

1. The system prompt from `build_system_message()`.
2. The compaction summary, if older turns were compacted. It is a **user** message, not a system message: it is built from student messages and tool output, so it must not gain system authority.
3. The chat history, normalized by `normalize_history_message()` (context-switch markers become `[context_switch]` notes; quiz messages are described as text).
4. The per-turn context from `build_turn_context_message()`, as the last message.

The order matters for cost. Providers cache the longest prefix that matches an earlier request. Everything that stays the same between turns (system prompt, summary, history) comes first, and the part that changes every turn (submission, build status, current time) comes last. The next turn can then reuse the cache up to the latest student message.

There is no LangChain prompt template on this path, so `{` and `}` in prompts need no escaping.

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
| Chat history     | Normalized Iris messages                | Prior conversation turns                     |
| Tool results     | Tool messages added by the agent loop   | Data retrieved during execution              |
| Guide prompts    | Separate template rendered and appended | Detailed behavioral instructions             |

### Custom Instructions

Instructors can provide custom instructions that are injected into the system prompt. These are formatted and included via the `format_custom_instructions()` utility from `pipeline/shared/utils.py`.
