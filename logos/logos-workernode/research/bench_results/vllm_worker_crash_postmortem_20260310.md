# vLLM Worker Crash Postmortem (2026-03-10)

## Incident Summary

A `vLLM::Worker_TP1` process aborted (`SIGABRT`) during tensor-parallel serving, after which GPU memory stayed allocated and could not be recovered by normal process cleanup.

## Impact

- DeepSeek memory sweep benchmark was blocked after the first two points.
- GPUs reported ~12 GB used on each card while no usable process ownership was visible.
- Recovery required host-level reset/reboot path instead of normal lane restart.

## Evidence

1. System crash artifact:
   - `/var/crash/_usr_bin_python3.12.1018.crash`
   - `ProcCmdline: VLLM::Worker_TP1` at line 77
   - `Signal: 6` / `SignalName: SIGABRT` at lines 1710-1711
   - `Date: Tue Mar 10 14:29:56 2026` at line 3
2. Unpacked crash metadata:
   - `/tmp/apport_unpack_1018/ProcStatus` shows `State: D (disk sleep)` and `Name: VLLM::Worker_TP`.
3. Stuck VRAM after crash:
   - `nvidia-smi --query-gpu=index,memory.used,memory.total` reported:
     - GPU0: `12012 / 16384` MB
     - GPU1: `12012 / 16384` MB
   - `nvidia-smi --query-compute-apps=...` returned `[N/A]` ownership fields.
4. Run configuration confirms vLLM V1 + TP=2 + NCCL:
   - `bench_results/sleep_benchmark_20260310_113827/deepseek-ai__deepseek-r1-0528-qwen3-8b.log:18`
   - same line includes `disable_custom_all_reduce=False`.

## Related but Separate Failure

Earlier the same day, another run failed for a different reason: missing `ninja` for JIT build.

- `FileNotFoundError: [Errno 2] No such file or directory: 'ninja'`
  - `bench_results/sleep_benchmark_20260310_111727/deepseek-ai__deepseek-r1-0528-qwen3-8b.log:94`
  - `...:228`
- Engine startup failure:
  - `...:230` and `...:256`

This is not the same as the later driver-wedge behavior, but it increases instability/noise during startup.

## Root Cause Assessment

### Most Likely Primary Cause (high confidence)

- A TP worker (`Worker_TP1`) hit a fatal CUDA/NCCL error path and aborted.
- After abort, GPU context cleanup was incomplete; VRAM stayed pinned and normal `kill`/lane restart did not reclaim it.

### Contributing Factors

- Tensor parallel (`tensor_parallel_size=2`) across both GPUs increases NCCL/all-reduce surface.
- `disable_custom_all_reduce=False` keeps custom all-reduce path enabled.
- Missing `ninja` in earlier run indicates environment was not fully hardened for flashinfer/JIT path.

## What You Can Do About It

Yes, there is a lot you can do.

### P0: Immediate Hardening

1. Ensure build tooling exists on worker nodes:
   - install `ninja` (`ninja-build`) before vLLM startup.
2. Reduce NCCL risk surface for this hardware:
   - add `--disable-custom-all-reduce` to vLLM extra args.
3. Add VRAM headroom:
   - avoid pushing utilization near max while doing lane reconfigure sweeps.
4. Prefer 1-GPU replicas over TP=2 when possible:
   - isolates failures to one GPU lane instead of both cards.

### P1: Operational Safety

1. Add staged recovery in controller:
   - stop lane -> kill known lane PIDs -> query compute-apps -> attempt GPU reset -> cordon lane.
2. Add auto-cordon watchdog:
   - if vLLM unhealthy and VRAM remains high without valid owner, remove lane from routing immediately.
3. Treat reboot as last-resort lane-worker recovery:
   - but only on GPU worker node, not control plane VM.

### P2: Architecture

1. Separate control plane from GPU workers.
2. Keep at least two GPU workers for failover.
3. Canary stress test each new vLLM/driver stack before production rollout.

## Recommended Next Experiment (After Recovery/Reboot)

Run the same `N=32,64,128` sweep with two variants:

1. Baseline: current flags.
2. Stability profile:
   - `--disable-custom-all-reduce`
   - lower `gpu_memory_utilization`
   - optional NCCL safety envs (`NCCL_P2P_DISABLE=1`, `NCCL_ASYNC_ERROR_HANDLING=1`) on test node.

Compare:
- throughput/latency,
- crash incidence,
- stuck-VRAM incidence across repeated runs.

