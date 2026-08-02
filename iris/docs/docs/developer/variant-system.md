---
title: Variant System
---

# Variant System

Variants allow a single pipeline to be deployed with different LLM model configurations. Artemis selects which variant to use at request time, enabling A/B testing, cost optimization, and gradual rollouts of new models.

## Variant Class Hierarchy

### `AbstractVariant`

**Location:** `src/iris/domain/variant/abstract_variant.py`

The base class for all variants:

```python
class AbstractVariant(ABC):
    variant_id: str
    name: str
    description: str

    @abstractmethod
    def required_models(self) -> set[str]:
        """Return the set of model version strings this variant needs."""
        ...

    def feature_dto(self) -> FeatureDTO:
        """Returns a FeatureDTO for communicating available variants to Artemis."""
        return FeatureDTO(id=self.variant_id, name=self.name, description=self.description)
```

Every variant must declare which models it requires via `required_models()`. This allows the system to validate at startup whether all necessary models are configured.

### `Variant`

**Location:** `src/iris/domain/variant/variant.py`

One generic class covers every pipeline. A `Variant` stores a **role-to-model** mapping plus the full set of model IDs it needs:

```python
class Variant(AbstractVariant):
    _role_models: dict[str, dict[str, str]]   # role -> {"local": id, "cloud": id}
    _required_model_ids: set[str]

    def model(self, role: str, local: bool) -> str:
        """Return the model ID for the given role and environment."""
        env = "local" if local else "cloud"
        return self._role_models[role][env]
```

A role is a job inside the pipeline — `chat`, `citation`, `rerank`. Callers ask for a role and get the model configured for the current environment. A pipeline adds a role by naming it in `ROLES` and configuring a model for it per variant.

## How Variants Are Declared

Pipelines declare their variants through class attributes, and the default `get_variants()` on `Pipeline` derives the variant objects from them:

```python
class ChatPipeline(AbstractAgentPipeline[ChatPipelineExecutionDTO, Variant]):
    PIPELINE_ID = "chat_pipeline"
    ROLES = {"chat"}
    VARIANT_DEFS = [
        ("default", "Default", "Uses a smaller model for faster responses."),
        ("advanced", "Advanced", "Uses a larger model, balancing speed and quality."),
    ]
    DEPENDENCIES = [
        Dep("citation_pipeline", variant="same"),
        Dep("session_title_generation_pipeline"),
        Dep("interaction_suggestion_pipeline", variant="course"),
        Dep("mcq_generation_pipeline"),
        Dep("lecture_retrieval_pipeline"),
        Dep("faq_retrieval_pipeline"),
        ...
    ]
```

- **`ROLES`** — The model roles this pipeline resolves itself. An orchestrator with `ROLES = set()` needs no `llm_configuration` entry of its own.
- **`VARIANT_DEFS`** — The variant IDs the pipeline offers, with the name and description that reach the Artemis UI.
- **`DEPENDENCIES`** — Sub-pipelines whose models count toward this pipeline's required models. `variant="same"` inherits the parent's variant ID, anything else pins a literal one.

A pipeline can still override `get_variants()` when the derivation does not fit.

## How Variants Are Resolved

When Artemis sends a pipeline execution request, the flow is:

1. **Artemis includes a variant ID** in the `PipelineExecutionSettingsDTO.variant` field (defaults to `"default"`).
2. The FastAPI router calls `validate_pipeline_variant(dto.settings, PipelineClass)`.
3. This function reads `settings.variant`, then calls `PipelineClass.get_variants()` to get all available variants.
4. It matches the requested variant ID against the available variants and validates that the required models are available in `llm_config.yml`.
5. The validated variant ID is passed to the pipeline worker, which resolves the full variant object.

Inside `AbstractAgentPipeline.__call__`, the variant determines model selection:

```python
# From abstract_agent_pipeline.py __call__:
selected_version = state.variant.model("chat", local)
```

The selected version string (e.g., `"gpt-5-mini"`) is then passed to `ModelVersionRequestHandler`, which looks up the corresponding model configuration in `llm_config.yml`.

## Cloud vs. Local Execution

Every role in a variant carries both a cloud and a local model ID:

| Mode      | Resolved by                  | Use Case                                               |
| --------- | ---------------------------- | ------------------------------------------------------ |
| **Cloud** | `variant.model(role, False)` | Default: uses cloud-hosted models (OpenAI, Azure)      |
| **Local** | `variant.model(role, True)`  | On-premises: uses locally-hosted models (Ollama, etc.) |

The `local` flag is determined from the request's settings and passed through the entire pipeline execution.

## Feature Discovery

Artemis discovers available pipeline variants through the `GET /api/v1/pipelines/{feature}/variants` endpoint. The `{feature}` path parameter is a member of the `Features` enum (`CHAT`, `COMPETENCY_GENERATION`, `INCONSISTENCY_CHECK`, `TUTOR_SUGGESTION`, `REWRITING`, `LECTURE_INGESTION`, `FAQ_INGESTION`, `AUTONOMOUS_TUTOR`). All student chats share the single `CHAT` feature, which `PIPELINE_BY_FEATURE` maps to `ChatPipeline`. Each pipeline's variants are filtered by model availability and returned as `FeatureDTO` objects:

```python
@dataclass
class FeatureDTO:
    id: str           # variant_id
    name: str         # Human-readable name
    description: str  # Description shown in Artemis UI
```

This allows the Artemis admin UI to display available features and let instructors select which variant to use for their course.

## Creating a New Variant

To add a new variant to an existing pipeline:

1. Open the pipeline class (e.g., `chat_pipeline.py`).
2. Add an entry to `VARIANT_DEFS`.
3. Add the matching variant to the pipeline's `llm_configuration` entry, so every role resolves to a model that exists in `llm_config.yml`.

To give a pipeline a new model role:

1. Add the role name to the pipeline's `ROLES`.
2. Configure a cloud and a local model for that role, per variant.
3. Read it with `state.variant.model("<role>", local)`. An unconfigured role raises a `KeyError` that names the roles the variant does have.
