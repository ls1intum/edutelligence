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

### `AbstractAgentVariant`

Extends `AbstractVariant` for agent-based pipelines with cloud/local model selection:

```python
class AbstractAgentVariant(AbstractVariant):
    cloud_agent_model: str
    local_agent_model: str

    def required_models(self) -> set[str]:
        return {self.cloud_agent_model, self.local_agent_model}
```

This provides two model slots:

- **`cloud_agent_model`** — Used when Artemis does not request local execution.
- **`local_agent_model`** — Used when the request specifies local (on-premises) execution.

### Pipeline-specific Variants

Some pipelines extend `AbstractAgentVariant` to add extra model roles. For example, `ExerciseChatVariant` adds citation models:

```python
class ExerciseChatVariant(AbstractAgentVariant):
    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        cloud_agent_model: str,
        cloud_citation_model: str,
        local_agent_model: str,
        local_citation_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
            cloud_agent_model=cloud_agent_model,
            local_agent_model=local_agent_model,
        )
        self.cloud_citation_model = cloud_citation_model
        self.local_citation_model = local_citation_model

    def required_models(self) -> set[str]:
        return {
            self.cloud_agent_model,
            self.local_agent_model,
            self.cloud_citation_model,
            self.local_citation_model,
        }
```

## How Variants Are Declared

Each pipeline implements a `get_variants()` class method that returns its available variants. These are typically hardcoded:

```python
class ExerciseChatAgentPipeline(AbstractAgentPipeline[...]):

    @classmethod
    def get_variants(cls) -> List[AbstractVariant]:
        return [
            ExerciseChatVariant(
                variant_id="default",
                name="Default",
                description="Default exercise chat variant",
                cloud_agent_model="gpt-5-mini",
                cloud_citation_model="gpt-5-nano",
                local_agent_model="gpt-oss:120b",
                local_citation_model="gpt-oss:120b",
            ),
            # Additional variants can be added here
        ]
```

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
if local and hasattr(state.variant, "local_agent_model"):
    selected_version = state.variant.local_agent_model
elif (not local) and hasattr(state.variant, "cloud_agent_model"):
    selected_version = state.variant.cloud_agent_model
```

The selected version string (e.g., `"gpt-5-mini"`) is then passed to `ModelVersionRequestHandler`, which looks up the corresponding model configuration in `llm_config.yml`.

## Cloud vs. Local Execution

Iris supports two execution modes per variant:

| Mode      | Model Source        | Use Case                                               |
| --------- | ------------------- | ------------------------------------------------------ |
| **Cloud** | `cloud_agent_model` | Default: uses cloud-hosted models (OpenAI, Azure)      |
| **Local** | `local_agent_model` | On-premises: uses locally-hosted models (Ollama, etc.) |

The `local` flag is determined from the request's settings and passed through the entire pipeline execution.

## Feature Discovery

Artemis discovers available pipeline variants through the `GET /api/v1/pipelines/{feature}/variants` endpoint. The `{feature}` path parameter is a pipeline identifier (e.g., `CHAT`, `COURSE_CHAT`, `LECTURE_CHAT`). Each pipeline's variants are filtered by model availability and returned as `FeatureDTO` objects:

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

1. Open the pipeline class (e.g., `exercise_chat_agent_pipeline.py`).
2. Add a new instance to the list returned by `get_variants()`.
3. Ensure the model version strings match entries in your `llm_config.yml`.

To create a variant class for a new pipeline:

1. Create a new file in `src/iris/domain/variant/`.
2. Extend `AbstractAgentVariant` (or `AbstractVariant` for non-agent pipelines).
3. Add any additional model roles your pipeline needs (e.g., citation, embedding).
4. Override `required_models()` to return all model version strings.
