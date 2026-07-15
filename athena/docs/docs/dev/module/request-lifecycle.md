---
title: Module Request Lifecycle
---

# Module Request Lifecycle

This page follows an Athena request from Artemis to a module and back. It complements the [module structure](./structure.md) reference, which defines the decorator signatures and module layout.

## 1. Artemis selects a module

Artemis selects a configured assessment module for an exercise type and calls the Assessment Module Manager's authenticated module-proxy route. The module name and type identify the target; Artemis can additionally provide module configuration and experiment context.

The manager validates that the named module exists and has the requested exercise type before forwarding the request. It preserves these request headers when present:

- `X-Module-Config` for configuration evaluated by the module's schema provider;
- `X-Experiment-ID`, `X-Module-Configuration-ID`, and `X-Run-ID` for experiment context; and
- `X-Server-URL`, the Artemis/LMS base URL used by a module that needs to call back into the LMS.

The manager authenticates the module-to-module call separately. For programming modules it also adds the repository-authorization secret associated with the supplied LMS URL; this value is not returned to Artemis or documented as a client configuration value.

## 2. The module contract processes the request

The Athena package exposes FastAPI endpoints through decorators in `athena/athena/endpoints.py`. The decorators authenticate the forwarded request, merge stored metadata, persist exercises/submissions/feedback where appropriate, deserialize module configuration, and call the implementation.

| Module concern | Decorator endpoint behavior |
| --- | --- |
| Submission intake | `@submissions_consumer` stores input and schedules the module consumer as a background task. |
| Submission selection | `@submission_selector` resolves stored submissions and returns a selected submission ID, or the manager fallback marker. |
| Tutor feedback intake | `@feedback_consumer` persists incoming feedback and schedules the consumer as a background task. |
| Feedback suggestions | `@feedback_provider` persists request context, invokes the provider, stores suggestions, and returns them. |
| Configuration | `@config_schema_provider` exposes the module's JSON schema; requests use the configured or default values. |
| Evaluation | `@evaluation_provider` handles the optional evaluation endpoint. |

The proxy wraps the module response with the resolved module name, status, data, and metadata before returning it to Artemis. A module can therefore process synchronously, schedule background work through its decorator, or implement its own documented workflow without changing the manager proxy contract.

## 3. LLM selection is a module decision

Artemis's selection of an Athena module is separate from `AiSelectionDecision`. For LLM-backed feedback providers without an explicit module configuration, the Athena decorator resolves the submitted decision within the module:

- `NO_AI` skips feedback-suggestion generation;
- `LOCAL_AI` requires a compatible local configuration and otherwise returns an unavailable-selection response; and
- other supported decisions execute in the module's AI-selection context.

Classical modules and explicitly configured modules do not automatically acquire this selection behavior. See the implementation READMEs for [LLM programming modules](https://github.com/ls1intum/edutelligence/tree/main/athena/modules/programming/module_programming_llm), [LLM quality modules](https://github.com/ls1intum/edutelligence/tree/main/athena/modules/programming/module_programming_quality_llm), [LLM modeling modules](https://github.com/ls1intum/edutelligence/tree/main/athena/modules/modeling/module_modeling_llm), [LLM text modules](https://github.com/ls1intum/edutelligence/tree/main/athena/modules/text/module_text_llm), and the classical module directories.

## 4. Programming-repository boundary

Programming modules receive the manager's repository-authorization header only after the module manager has associated it with the Artemis/LMS URL. Athena's repository authorization middleware keeps this internal to Athena module calls. A module uses the authenticated Artemis `AthenaInternalResource` boundary to retrieve repository data; it must not treat the original Artemis request or a client-provided URL as sufficient authorization.

This makes the boundary explicit: Artemis controls module selection and authenticated repository access, the manager proxies the request and credentials to the configured module, and the module owns its assessment algorithm and any applicable LLM selection.
