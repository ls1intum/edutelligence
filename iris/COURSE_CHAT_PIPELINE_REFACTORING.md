# Agent Pipeline Migration Guide

## Overview

This document provides a comprehensive guide for migrating existing pipelines to inherit from the `AbstractAgentPipeline` base class. This migration standardizes pipeline architecture, improves maintainability, and reduces code duplication across the system.

## Background

Many pipelines in the system were originally implemented as custom classes that directly extended the base `Pipeline` class and manually handled common agent concerns such as:

- Agent execution and state management
- Tool creation and configuration
- LLM initialization and prompt assembly
- Memory management (Memiris integration)
- Error handling and status callbacks

The `AbstractAgentPipeline` was introduced to provide a standardized framework that handles these common concerns automatically, allowing pipeline implementations to focus on domain-specific logic.

## Completed Migrations

### ✅ Course Chat Pipeline

- **Status**: Complete
- **Features**: Tools extracted to `src/iris/common/tools.py`
- **Benefits**: Reduced code duplication, standardized execution flow
- **Date Completed**: Previous migration

### ✅ Exercise Chat Agent Pipeline

- **Status**: Complete
- **Features**:
  - Tools extracted to `src/iris/common/exercise_chat_tools.py`
  - Utilities extracted to `src/iris/common/exercise_chat_utils.py`
  - Full inheritance from `AbstractAgentPipeline`
  - Type safety improvements
  - Code quality score: 8.10/10 (pylint)
- **Benefits**:
  - Eliminated ~200+ lines of boilerplate code
  - Standardized tool creation pattern
  - Improved error handling and state management
  - Better separation of concerns
- **Date Completed**: August 9, 2025

## When to Migrate

### Pipelines That Should Migrate

Pipelines that exhibit these characteristics are good candidates for migration:

- Use LangChain agents with tool calling
- Have manual agent execution loops
- Create and manage tools dynamically
- Handle memory creation/retrieval
- Process chat history and user messages
- Use status callbacks for progress updates

### Pipelines That May Not Need Migration

- Simple transformation pipelines without agent interaction
- Pipelines that don't use LLMs or tools
- Legacy pipelines with complex custom execution logic that doesn't fit the agent pattern

## Migration Process

### Phase 1: Analysis and Preparation

#### 1.1 Analyze Current Implementation

Identify the following components in your existing pipeline:

**Required Components (must be migrated):**

- [ ] LLM creation and configuration
- [ ] Tool creation and management
- [ ] System prompt/message building
- [ ] Agent execution logic
- [ ] Memory management (if applicable)

**Optional Components (may need special handling):**

- [ ] Custom pre-processing logic
- [ ] Post-processing and result transformation
- [ ] Custom error handling
- [ ] Status callback management
- [ ] Citation processing
- [ ] Suggestion generation

#### 1.2 Identify Domain-Specific Logic

Document any logic that is unique to your pipeline:

- Custom tool configurations
- Specialized prompt templates
- Domain-specific data processing
- Custom storage mechanisms
- Unique callback requirements

### Phase 2: Implementation Changes

#### 2.1 Update Class Declaration

**Before:**

```python
class YourPipeline(Pipeline[YourVariant]):
```

**After:**

```python
class YourPipeline(AbstractAgentPipeline[YourExecutionDTO, YourVariant]):
```

#### 2.2 Simplify Constructor

**Before:**

```python
def __init__(
    self,
    callback: YourStatusCallback,
    variant: str = "default",
    # other domain-specific parameters
):
    super().__init__(implementation_id="your_pipeline")
    # Manual initialization of LLM, database, retrievers, etc.
    self.llm = create_llm(variant)
    self.db = VectorDatabase()
    # ... other initialization
```

**After:**

```python
def __init__(
    self,
    # keep only domain-specific parameters
    custom_param: Optional[str] = None,
):
    super().__init__(implementation_id="your_pipeline")
    # Store only domain-specific state
    self.custom_param = custom_param
    # Remove: LLM, database, callback, variant initialization
    # These are now handled by the abstract pipeline
```

**Key Changes:**

- Remove `callback` and `variant` parameters (passed to `__call__` instead)
- Remove manual database/LLM initialization
- Keep only domain-specific initialization

#### 2.3 Implement Required Abstract Methods

##### A. `is_memiris_memory_creation_enabled()`

```python
def is_memiris_memory_creation_enabled(
    self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant]
) -> bool:
    """Return True if background memory creation should be enabled."""
    # Example implementations:
    # return bool(state.dto.user and state.dto.user.memiris_enabled)
    # return False  # if memory not supported
    # return state.dto.enable_memory  # if controlled by DTO flag
```

##### B. `get_tools()`

```python
def get_tools(
    self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant]
) -> list[Callable]:
    """Create and return tools for the agent."""

    # Get user query for tools that need it
    query_text = self.get_text_of_latest_user_message(state)

    # Create storage for shared data between tools
    if not hasattr(state, 'custom_storage'):
        setattr(state, 'custom_storage', {})

    # Use callback from state
    callback = state.callback

    # Build tool list based on available data and permissions
    tool_list: list[Callable] = []

    if state.dto.some_condition:
        tool_list.append(create_your_tool(state.dto, callback))

    # Add conditional tools based on data availability
    if hasattr(state.dto, 'optional_data') and state.dto.optional_data:
        tool_list.append(create_optional_tool(state.dto, callback))

    return tool_list
```

##### C. `build_system_message()`

```python
def build_system_message(
    self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant]
) -> str:
    """Build the system message/prompt for the agent."""

    # Option 1: Simple string-based prompt
    return f"You are an AI assistant for {state.dto.context}. Follow these instructions..."

    # Option 2: Template-based prompt (recommended)
    template_context = {
        "current_date": datetime.now(tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "context": state.dto.context,
        "has_history": bool(state.message_history),
        # Add other context variables
    }

    return self.prompt_template.render(template_context)

    # Option 3: Complex conditional prompt building
    prompt_parts = ["You are an AI assistant."]

    if state.dto.some_feature_enabled:
        prompt_parts.append("You have access to special features.")

    if state.message_history:
        prompt_parts.append("Consider the conversation history.")

    return "\n\n".join(prompt_parts)
```

##### D. `get_agent_params()` and `get_memiris_tenant()`

```python
def get_agent_params(
    self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant]
) -> dict[str, Any]:
    """Return parameters passed to the agent executor."""
    # Most pipelines can return an empty dict
    return {}

    # Some pipelines might need custom parameters:
    # return {"max_iterations": 10, "early_stopping_method": "generate"}

def get_memiris_tenant(self, dto: YourExecutionDTO) -> str:
    """Return the tenant identifier for memory management."""
    if not dto.user:
        raise ValueError("User is required for memiris tenant")
    return get_tenant_for_user(dto.user.id)
```

**Note**: The `create_llm()` method is no longer required! The abstract pipeline automatically creates an `IrisLangchainChatModel` using `state.variant.agent_model` and stores it in `state.llm`.

#### 2.4 Implement Optional Hook Methods

##### A. `pre_agent_hook()` - Setup and Initialization

```python
def pre_agent_hook(self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant]) -> None:
    """Initialize resources before agent execution."""

    # Initialize retrievers, databases, external services
    self.your_retriever = YourRetriever(state.db.client)
    self.external_service = ExternalServiceClient()

    # Validate preconditions
    if not state.dto.required_field:
        raise ValueError("Required field missing")

    # Set up any custom state
    state.custom_data = {}
```

##### B. `post_agent_hook()` - Post-processing

```python
def post_agent_hook(self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant]) -> str:
    """Process results after agent execution."""

    # Apply post-processing to results
    processed_result = self.process_citations(state.result, state.custom_storage)
    state.result = processed_result

    # Generate additional outputs
    self.generate_suggestions(state.result, state.dto)

    # Update callback with final results
    state.callback.done(
        "Processing complete",
        final_result=state.result,
        additional_data=getattr(state, 'custom_storage', {})
    )

    return state.result
```

##### C. `on_agent_step()` - Step-by-step Processing

```python
def on_agent_step(
    self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant],
    step: dict[str, Any]
) -> None:
    """Handle each agent execution step."""

    # Track token usage
    if hasattr(state, 'llm') and hasattr(state.llm, 'tokens'):
        self._append_tokens(state.llm.tokens, PipelineEnum.YOUR_PIPELINE)

    # Update progress
    if step.get('intermediate_steps'):
        state.callback.in_progress(f"Processing step {len(step['intermediate_steps'])}")

    # Custom step processing
    self.handle_custom_step_logic(step)
```

#### 2.5 Update Main Call Method

**Before:**

```python
def __call__(self, dto: YourExecutionDTO, **kwargs):
    # 100+ lines of manual execution logic
    # Agent setup, tool creation, execution, etc.
```

**After:**

```python
def __call__(self, dto: YourExecutionDTO, variant: YourVariant, callback: YourStatusCallback):
    """Execute the pipeline with the provided arguments."""
    try:
        logger.info(f"Running {self.__class__.__name__}...")

        # Delegate to parent class for standardized execution
        super().__call__(dto, variant, callback)

    except Exception as e:
        logger.error(f"Error in {self.__class__.__name__}", exc_info=e)
        callback.error(f"Pipeline execution failed: {str(e)}")
```

### Phase 3: Method Consolidation

#### 3.1 Consolidate Helper Methods

**Tool Creation:**

```python
# Before: Separate methods
def _create_tools(...) -> list[Callable]: ...
def get_tools(...) -> list[Callable]:
    return self._create_tools(...)

# After: Single method
def get_tools(...) -> list[Callable]:
    # All logic consolidated here
```

**Prompt Building:**

```python
# Before: Separate methods
def _build_prompt(...) -> str: ...
def build_system_message(...) -> str:
    return self._build_prompt(...)

# After: Single method
def build_system_message(...) -> str:
    # All logic consolidated here
```

#### 3.2 Remove Redundant Methods

Remove methods that are now handled by the abstract pipeline:

- Manual agent execution loops
- Tool registration and management
- LLM initialization and configuration
- Basic error handling and callbacks
- Standard memory management

### Phase 4: Type Safety and Validation

#### 4.1 Add Proper Type Annotations

```python
from typing import Any, Callable, List, Optional
from ...domain.variant.abstract_variant import AbstractVariant

class YourPipeline(AbstractAgentPipeline[YourExecutionDTO, YourVariant]):
    # Add type annotations for all attributes
    custom_retriever: Optional[YourRetriever]
    custom_service: Optional[ExternalService]
    tokens: List[Any]
```

#### 4.2 Add Null Safety Checks

```python
def build_system_message(self, state: AgentPipelineExecutionState[YourExecutionDTO, YourVariant]) -> str:
    # Check for required fields
    if not state.dto.user:
        raise ValueError("User is required")

    # Handle optional fields safely
    custom_instructions = state.dto.custom_instructions or ""

    # Use getattr for dynamic attributes
    custom_data = getattr(state, 'custom_storage', {})
```

#### 4.3 Handle Type Checker Issues

```python
# For dynamic state attributes, use setattr/getattr
if not hasattr(state, 'custom_storage'):
    setattr(state, 'custom_storage', {})

custom_data = getattr(state, 'custom_storage', {})

# For inheritance type issues, add type ignore comments
@classmethod
def get_variants(cls) -> List[YourVariant]:  # type: ignore[override]
    return [...]
```

#### 4.4 Run Type Checking

```bash
# Run mypy to identify type issues
python -m mypy src/iris/pipeline/your_pipeline.py --show-error-codes

# Fix any issues found, adding type ignore comments for false positives
```

### Phase 5: Testing and Validation

#### 5.1 Functional Testing

- [ ] Verify all existing functionality works identically
- [ ] Test all variants and configurations
- [ ] Validate tool execution and results
- [ ] Confirm memory creation and retrieval
- [ ] Test error handling and edge cases

#### 5.2 Integration Testing

- [ ] End-to-end pipeline execution
- [ ] Integration with external services
- [ ] Callback and status update functionality
- [ ] Performance and resource usage

#### 5.3 Regression Testing

- [ ] Compare outputs with original implementation
- [ ] Verify no behavioral changes
- [ ] Test all supported input formats
- [ ] Validate error messages and codes

## Common Migration Patterns

### Pattern 1: Simple Tool-Based Pipeline

```python
class SimplePipeline(AbstractAgentPipeline[SimpleDTO, SimpleVariant]):
    def get_tools(self, state):
        return [create_simple_tool(state.dto)]

    def build_system_message(self, state):
        return "You are a helpful assistant."

    def create_llm(self, state):
        return create_standard_llm(state.variant.agent_model)
```

### Pattern 2: Complex Multi-Tool Pipeline

```python
class ComplexPipeline(AbstractAgentPipeline[ComplexDTO, ComplexVariant]):
    def get_tools(self, state):
        tools = [create_base_tool(state.dto)]

        if state.dto.feature_a_enabled:
            tools.append(create_feature_a_tool(state.dto))

        if state.dto.feature_b_enabled:
            tools.extend(create_feature_b_tools(state.dto))

        return tools

    def pre_agent_hook(self, state):
        self.setup_external_services(state.dto)

    def post_agent_hook(self, state):
        return self.post_process_results(state.result)
```

### Pattern 3: Template-Based Pipeline

```python
class TemplatePipeline(AbstractAgentPipeline[TemplateDTO, TemplateVariant]):
    def __init__(self):
        super().__init__(implementation_id="template_pipeline")
        self.jinja_env = Environment(loader=FileSystemLoader("templates"))
        self.template = self.jinja_env.get_template("pipeline_prompt.j2")

    def build_system_message(self, state):
        context = {
            "user_name": state.dto.user.name,
            "context": state.dto.context,
            "features": state.dto.enabled_features
        }
        return self.template.render(context)
```

## Troubleshooting Common Issues

### Issue 1: Type Checker Errors

**Problem:** mypy reports incompatible override types
**Solution:** Use `# type: ignore[override]` for false positives, fix real type mismatches

### Issue 2: Missing State Attributes

**Problem:** Accessing attributes that don't exist on state object
**Solution:** Use `setattr()`/`getattr()` for dynamic attributes

### Issue 3: Callback Type Mismatches

**Problem:** Tool functions expect specific callback types
**Solution:** Use type casting: `callback = cast(YourCallbackType, state.callback)`

### Issue 4: Tool Dependencies

**Problem:** Tools need access to retrievers/services initialized in constructor
**Solution:** Initialize dependencies in `pre_agent_hook()` using state.db

### Issue 5: Complex Post-Processing

**Problem:** Existing pipeline has complex result transformation
**Solution:** Move logic to `post_agent_hook()` and return processed result

## Best Practices

### 1. Keep Domain Logic Separate

- Put business logic in the concrete pipeline class
- Use abstract pipeline for common agent concerns
- Don't override private methods unless absolutely necessary

### 2. Use State Object Effectively

- Store shared data in state using `setattr()`
- Access state data safely with `getattr()` and defaults
- Don't modify state structure in hooks

### 3. Handle Errors Gracefully

- Add comprehensive null checks
- Use try-catch in hook methods to avoid breaking execution
- Provide meaningful error messages

### 4. Maintain Backward Compatibility

- Keep the same public API when possible
- Document any breaking changes
- Provide migration instructions for callers

### 5. Optimize Performance

- Initialize expensive resources in `pre_agent_hook()`
- Cache reusable data in state object
- Avoid redundant computations in tool creation

## Validation Checklist

### Pre-Migration

- [ ] Analyzed current implementation and identified components
- [ ] Documented domain-specific logic and requirements
- [ ] Identified potential migration challenges
- [ ] Created test cases for existing functionality

### During Migration

- [ ] Updated class inheritance and constructor
- [ ] Implemented all required abstract methods
- [ ] Added appropriate hook methods
- [ ] Consolidated helper methods
- [ ] Updated main call method

### Post-Migration

- [ ] All tests pass with identical behavior
- [ ] Type checking passes (mypy clean)
- [ ] Performance is acceptable
- [ ] Documentation updated
- [ ] Migration reviewed and approved

### Quality Gates

- [ ] No functional regressions
- [ ] Code is cleaner and more maintainable
- [ ] Follows established patterns
- [ ] Type safety improved
- [ ] Error handling robust

## Conclusion

Migrating to `AbstractAgentPipeline` standardizes pipeline architecture across the system and reduces maintenance overhead. The migration process involves:

1. **Analysis** - Understanding current implementation
2. **Refactoring** - Implementing abstract methods and hooks
3. **Consolidation** - Removing redundant code
4. **Validation** - Ensuring functional correctness
5. **Testing** - Comprehensive regression testing

The result is a more maintainable, consistent, and robust pipeline implementation that benefits from shared infrastructure while preserving domain-specific functionality.

This migration serves as a foundation for future pipeline development and establishes patterns that should be followed for new agent-based pipelines in the system.
