# Request pipeline

This is the code-level reference for Logos request routing. The service overview and development entry point are in the [Logos README](../../../../README.md).

## Ownership boundaries

`main.py` owns HTTP authentication, request setup, mode selection, response forwarding, and final completion/usage recording. `RequestPipeline.process()` owns candidate classification, scheduling, and execution-context resolution. `ContextResolver` owns database/runtime resolution; `Executor` owns the upstream HTTP request. The route layer invokes the executor and releases the scheduled reservation after completion.

## Request modes

### Resource / classification mode

A request without a direct `model` enters resource mode:

1. `main.py` creates the authorized deployment set and passes it to `RequestPipeline`.
2. The pipeline applies the request privacy policy to deployments, then derives candidate models.
3. `ClassificationManager` applies policy filtering and token filtering. Laura's embedding classifier ranks the eligible candidates.
4. The active `ClassificationCorrectingScheduler` chooses an eligible model deployment/provider, using the candidate ranking together with its scheduling signals and queues.
5. `ContextResolver` obtains the chosen provider's execution context and `main.py` forwards the request through `Executor`.
6. Completion, response usage, scheduler/provider statistics, and monitoring events are recorded by the owning route and pipeline components.

A request with no eligible candidate, no schedulable deployment, or a queue timeout is completed as an error/timeout rather than being silently rerouted outside the eligible set.

### Direct-model mode

When a request names a model, `main.py` verifies access and restricts the candidate deployments to that model. It then reuses the resource-mode path with `skip_laura=True`.

Direct-model mode skips **only** Laura's ML ranking: privacy policy, policy filtering, token filtering, provider/deployment scheduling, context resolution, execution, and completion recording remain active. The scheduler can therefore select an eligible deployment/provider for the requested model; naming a model does not bypass policy or token checks.

## Execution and readiness

`ContextResolver` resolves the model/provider authorization data and creates the URL, authentication headers, and provider-specific execution context. `Executor` makes synchronous or streaming OpenAI-shaped upstream calls and extracts response usage where available.

Readiness retries are deliberately narrow. `RequestPipeline` retries an absent execution context only for a scheduled `logosnode` provider, and `ContextResolver` retries selection of a LogosNode lane while that lane transitions to an available state. Cloud and other provider paths do not inherit that lane-readiness retry behavior.

## Related components

- `classification/classification_manager.py`: policy, token, and Laura stages.
- `pipeline/correcting_scheduler.py`: active classification-correcting scheduler.
- `pipeline/context_resolver.py`: database/runtime execution context.
- `pipeline/executor.py`: streaming and non-streaming upstream calls.
- `monitoring/recorder.py`: request lifecycle monitoring.

The source tree includes alternate scheduler implementations for experimentation and tests. The application initializes `ClassificationCorrectingScheduler`; documentation must not describe an unused scheduler as the active request path.
