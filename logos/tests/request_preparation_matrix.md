# Request Preparation Matrix

This matrix tracks the request-path and capacity-planner scenarios covered by tests for loaded, sleeping, and not-yet-loaded models. It also marks the reliability cases added for request-time single-flight wake/load and last-mile retry.

## Request-time Prepare

| Scenario | State / Setup | Coverage |
| --- | --- | --- |
| Ready lane returned directly | Loaded lane already exists for the model | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_proceeds_with_first_status` |
| Request-time wake | Selected lane is sleeping and vLLM | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_for_request_wakes_sleeping_lane` |
| Same sleeping lane, concurrent requests | Two requests hit the same sleeping lane; only one wake should execute | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_concurrent_same_sleeping_lane_uses_single_wake` |
| Request-time wake with reclaim | Sleeping target needs VRAM reclaimed from an idle competitor first | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_for_request_reclaims_idle_competitor_first` |
| Request-time cold load | No lane exists for the model; request triggers load | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_cold_load` |
| Same cold model, concurrent requests | Two requests hit the same unloaded model; only one load should execute while followers wait on stale status | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_concurrent_same_cold_model_uses_single_load_while_status_is_stale` |
| Different cold models, concurrent requests | Concurrent loads merge desired lane sets instead of stomping each other | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_concurrent_cold_loads_serialize_desired_lane_mutations` |
| Single-flight cleanup after failure | Failed leader wake/load must clear state so the next request can lead | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_failure_clears_single_flight_for_next_request` |
| Insufficient VRAM rejects request-time cold load | Unloaded model cannot be placed and no reclaim is available | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_cold_load_insufficient_vram` |
| First-status gate blocks request-time prepare | Worker connected but has not published runtime yet | `tests/unit/capacity/test_capacity_planner.py::test_prepare_lane_deferred_without_first_status` |

## Request Execution And Retry

| Scenario | State / Setup | Coverage |
| --- | --- | --- |
| Sync infer retry on lane readiness failure | First infer hits `state=sleeping`, re-prepare switches lane, second infer succeeds | `tests/unit/main/test_request_logging.py::test_sync_response_retries_logosnode_lane_readiness_error_and_releases_all_reservations` |
| Streaming infer retry on lane readiness failure | First stream hits `state=sleeping`, re-prepare switches lane, second stream succeeds | `tests/unit/main/test_request_logging.py::test_streaming_response_retries_logosnode_lane_readiness_error_and_releases_all_reservations` |
| Retry cleanup on final error | Request retries once, second infer still fails, all reservations are released | `tests/unit/main/test_request_logging.py::test_sync_response_releases_retry_reservations_after_final_logosnode_error` |
| Scheduler release on context-resolution failure | Capacity reservation is released when context resolution returns `None` or raises | `tests/unit/main/test_execute_modes.py::test_pipeline_releases_capacity_when_context_resolution_fails`, `tests/unit/main/test_execute_modes.py::test_pipeline_releases_capacity_when_context_resolution_raises` |

## Lane Selection And Worker Queue Pressure

| Scenario | State / Setup | Coverage |
| --- | --- | --- |
| Least-active replica wins | Multiple running lanes for the same model | `tests/unit/main/test_node_controller_integration.py::test_registry_selects_least_active_lane` |
| Lower backend queue wins | Same model, same active count, different `queue_waiting` / `requests_running` | `tests/unit/main/test_node_controller_integration.py::test_registry_prefers_lane_with_lower_vllm_queue_pressure` |
| Request-ready selector rejects cold vLLM lane | vLLM lane exists but is not ready for request-time infer | `tests/unit/main/test_node_controller_integration.py::test_registry_request_ready_selection_excludes_cold_vllm_lane` |
| Request-ready selector allows starting non-vLLM lane | Non-vLLM lane can lazy-load on first request | `tests/unit/main/test_node_controller_integration.py::test_registry_request_ready_selection_allows_starting_non_vllm_lane` |
| Parallel command isolation | Multiple command RPCs complete out of order without crossing streams | `tests/unit/main/test_node_controller_integration.py::test_registry_parallel_command_roundtrip_out_of_order` |
| Parallel stream isolation | Multiple stream RPCs stay isolated by command id | `tests/unit/main/test_node_controller_integration.py::test_registry_parallel_stream_roundtrip_is_isolated` |
| Stale session rejection / worker conflict | Offline or conflicting worker sessions | `tests/unit/main/test_node_controller_integration.py::test_registry_stale_session_raises`, `tests/unit/main/test_node_controller_integration.py::test_registry_rejects_different_worker_for_active_provider` |

## Scheduler View And Candidate Ranking

| Scenario | State / Setup | Coverage |
| --- | --- | --- |
| Loaded plus sleeping aggregation | One loaded vLLM lane plus one sleeping lane for same model | `tests/unit/sdi/test_scheduler_view.py::test_scheduler_view_loaded_vllm_and_sleeping_ollama` |
| All lanes cold | No loaded lane exists for the model | `tests/unit/sdi/test_scheduler_view.py::test_scheduler_view_all_cold_lanes` |
| Backend metrics flow through | Queue depth, running requests, TTFT histogram propagate into scheduler view | `tests/unit/sdi/test_scheduler_view.py::test_scheduler_view_vllm_with_backend_metrics` |
| Stopped / error lanes retained in view | Lowest-rank states still appear in the model view | `tests/unit/sdi/test_scheduler_view.py::test_scheduler_view_includes_stopped_error_lanes` |
| Warmth ordering | Running > loaded > sleeping > starting > cold > stopped > error | `tests/unit/sdi/test_scheduler_view.py::test_warmest_state_ordering` |
| Sleep warmth ordering | Awake > unknown > sleeping > unsupported | `tests/unit/sdi/test_scheduler_view.py::test_warmest_sleep_ordering` |
| Correcting scheduler loaded-vs-cold ranking | Loaded or sleeping candidates beat colder candidates when penalties apply | `tests/unit/pipeline/test_correcting_scheduler.py::test_loaded_beats_cold_due_to_penalty`, `tests/unit/pipeline/test_correcting_scheduler.py::test_sleeping_beats_cold` |
| Cross-provider choice | Azure may beat a cold local candidate | `tests/unit/pipeline/test_correcting_scheduler.py::test_azure_selected_when_local_cold` |
| Reserve fallthrough | First candidate cannot reserve capacity, scheduler falls through | `tests/unit/pipeline/test_correcting_scheduler.py::test_reserve_failure_falls_through` |

## Feasibility, Placement, And Reclaim

| Scenario | State / Setup | Coverage |
| --- | --- | --- |
| Straight feasibility pass / fail / unknown | Load fits, OOMs, or lacks a profile | `tests/unit/capacity/test_capacity_planner.py::test_feasibility_passes`, `tests/unit/capacity/test_capacity_planner.py::test_feasibility_rejects_oom`, `tests/unit/capacity/test_capacity_planner.py::test_feasibility_no_profile_allows` |
| Feasibility with per-token KV math | KV budget derived from `kv_per_token_bytes` impacts placement feasibility | `tests/unit/capacity/test_capacity_planner.py::test_feasibility_uses_per_token_kv` |
| Load VRAM math | vLLM load cost uses base residency plus KV cache | `tests/unit/capacity/test_capacity_planner.py::test_vllm_vram_estimate_uses_base_plus_kv` |
| Wake VRAM math | Wake cost uses loaded minus sleeping residual VRAM | `tests/unit/capacity/test_capacity_planner.py::test_vram_wake_costs_net_increase` |
| Multi-action VRAM budgeting | Later actions see reduced remaining VRAM | `tests/unit/capacity/test_capacity_planner.py::test_vram_cumulative_tracking` |
| Low-damage reclaim plan | Prefer smaller sleep combinations over one large reclaim | `tests/unit/capacity/test_capacity_planner.py::test_request_reclaim_prefers_small_sleep_combo_over_large_single_sleep` |
| Smallest sufficient stop candidate | When stopping is needed, stop the smallest sufficient lane | `tests/unit/capacity/test_capacity_planner.py::test_request_reclaim_prefers_smallest_sufficient_stop_candidate` |
| Queue-aware reclaim skip | Do not reclaim a lane that already has worker queue pressure | `tests/unit/capacity/test_capacity_planner.py::test_request_reclaim_skips_lane_with_queue_waiting` |
| Reservation-aware reclaim skip | Do not reclaim a lane reserved for an in-flight request | `tests/unit/capacity/test_capacity_planner.py::test_request_reclaim_skips_lane_with_request_reservation` |
| GPU-overlap reclaim preference | When the reclaim plan is otherwise equivalent, free GPUs overlapping the target first | `tests/unit/capacity/test_capacity_planner.py::test_request_reclaim_prefers_gpu_overlap_when_plan_is_equivalent` |
| Anti-flip cooldown | Recently prepared lanes are protected from immediate reclaim | `tests/unit/capacity/test_capacity_planner.py::test_anti_flip_blocks_request_reclaim_within_cooldown` |
| Eviction predictor | Estimate whether a new load would require eviction | `tests/unit/capacity/test_capacity_planner.py::test_would_require_eviction_true_when_vram_tight`, `tests/unit/capacity/test_capacity_planner.py::test_would_require_eviction_false_when_vram_available` |

## Idle, Demand, And Background Planner Behavior

| Scenario | State / Setup | Coverage |
| --- | --- | --- |
| Idle sleep thresholds | Loaded lane idles into L1 sleep, sleeping lane idles into L2 | `tests/unit/capacity/test_capacity_planner.py::test_idle_sleep_l1_after_threshold`, `tests/unit/capacity/test_capacity_planner.py::test_idle_sleep_l2_after_threshold` |
| No background stop for sleeping lanes | Background planner deepens sleep instead of stopping | `tests/unit/capacity/test_capacity_planner.py::test_idle_lane_stays_sleeping_without_background_stop` |
| Active-request guards | No idle sleep/deepen while requests are active | `tests/unit/capacity/test_capacity_planner.py::test_idle_sleep_skips_active_requests`, `tests/unit/capacity/test_capacity_planner.py::test_idle_sleep_l2_skips_active_requests` |
| Ollama skip | Non-vLLM lanes do not get sleep actions | `tests/unit/capacity/test_capacity_planner.py::test_no_sleep_for_ollama_lanes` |
| Demand wake / load / no-op | High demand wakes sleeping lane or loads missing model; low demand does nothing | `tests/unit/capacity/test_capacity_planner.py::test_demand_wake_sleeping_lane`, `tests/unit/capacity/test_capacity_planner.py::test_demand_load_new_model`, `tests/unit/capacity/test_capacity_planner.py::test_demand_below_threshold_no_action` |
| Offline-provider and capability gating | Skip offline providers and models outside worker capabilities | `tests/unit/capacity/test_capacity_planner.py::test_demand_actions_skip_offline_provider`, `tests/unit/capacity/test_capacity_planner.py::test_demand_actions_respect_worker_capabilities` |
| Preemptive load-then-sleep | Previously served vLLM models may be loaded and parked | `tests/unit/capacity/test_capacity_planner.py::test_preemptive_sleep_loads_previously_served_model` |
| Capability seeding | Zero-lane worker can pre-load demanded capability models | `tests/unit/capacity/test_capacity_planner.py::test_capability_seeding_zero_lane_worker` |

## Confirmation And Control-Plane Semantics

| Scenario | State / Setup | Coverage |
| --- | --- | --- |
| Confirmation timeout | Command sent but snapshot never reaches expected state | `tests/unit/capacity/test_capacity_planner.py::test_confirmation_timeout_returns_false` |
| Confirmation success | Snapshot reaches expected state and tracking is updated | `tests/unit/capacity/test_capacity_planner.py::test_confirmation_success` |
| Stop confirmation | Lane disappears from runtime snapshot | `tests/unit/capacity/test_capacity_planner.py::test_stop_confirmation_lane_gone` |
| Wake confirmation resets idle tracking | Woken lane is protected from immediate re-sleep | `tests/unit/capacity/test_capacity_planner.py::test_wake_confirmation_resets_idle_timer_and_clears_sleep_tracking` |
| Wake timeout budget | Wake command uses the full request-time timeout budget | `tests/unit/capacity/test_capacity_planner.py::test_wake_command_uses_full_timeout_budget` |
| Declarative lane-set merge | `load` preserves existing desired lanes; `stop` removes only target lane | `tests/unit/capacity/test_capacity_planner.py::test_load_uses_apply_lanes_with_state_merge`, `tests/unit/capacity/test_capacity_planner.py::test_stop_uses_apply_lanes_removing_target` |
| KV reconfigure sleep-first | Lane is slept before `reconfigure_lane` restart | `tests/unit/capacity/test_capacity_planner.py::test_reconfigure_kv_cache_sleeps_before_restart` |

## Current Gap Policy

- New request-time reliability cases should be added here whenever the planner or worker state model changes.
- If a behavior change is intentional but not yet covered, add it under the relevant section as a documented gap in the same pull request.
