# Benchmark — INTERNAL run instructions (NOT anonymized)

> ⚠️ **INTERNAL ONLY — do NOT copy this file to the public artifact repo
> (`icse-logos`).** It contains the real hostnames, SSH users, and paths of the
> TUM test environment. Everything else in this folder is anonymized (`AnonTool`,
> `example.com`, `gpu-node-a/b`); this file is the key that maps those
> placeholders back to the real infrastructure so the benchmark can actually be
> run in-house.

The anonymized benchmark talks the **`anontool`** wire protocol (auth header
`anontool_key`, response headers `x-anontool-*`, admin routes `/anontooldb/...`,
worker config section `anontool:`). It therefore requires the **anontool-protocol
build** of the stack (the `icse27review/*` images, or a locally-built stack with
the external protocol surface renamed `logos→anontool`). Against the legacy
`logos`-protocol deployment it will not authenticate.

## Real ↔ placeholder mapping

| Benchmark flag / env               | Placeholder in repo            | Real value                                   |
|------------------------------------|--------------------------------|----------------------------------------------|
| `--anontool-url` / `ANONTOOL_URL`  | `https://anontool-test.example.com` | `https://logos-test.aet.cit.tum.de`     |
| `--anontool-key` / `ANONTOOL_KEY`  | `YOUR_KEY`                      | root key from `/root/bench-secrets.env`      |
| `--gpu-host` / `GPU_HOSTS`         | `gpu-node-a gpu-node-b`         | `deipapa.ase.cit.tum.de deimama.aet.cit.tum.de` |
| `--gpu-ssh-user` / `GPU_SSH_USER`  | `anontool-server`              | `logos-server`                               |
| `--anontool-ssh-host`              | `anontool-test.example.com`    | `logos-test.aet.cit.tum.de`                  |
| `--anontool-ssh-user`              | `anon-user`                    | `ge69yun`                                    |
| `--anontool-config`                | `anontool/anontool-workernode/config.yml` | `logos/logos-workernode/config.yml` |
| workernode env file (on GPU nodes) | `/opt/anontool-workernode/.env`| `/opt/logos-workernode/.env`                 |
| `CALIBRATION_PROVIDER_IDS`         | `"3 2"`                         | `3`=deipapa, `2`=deimama                     |

Provider IDs / model routing follow the live orchestrator (`/logosdb` admin API
on the legacy stack; `/anontooldb` on the anontool build).

## How the runs are actually launched

Runs execute **on the benchmark host `logos-test`** (as `root`), never from a
laptop — the private keys authorized on the GPU nodes live there.

```bash
# on logos-test, in a tmux session (long jobs — survive disconnects):
tmux new -s bench

cd /opt/edutelligence && git pull                 # pull the branch under test
set -a; . /root/bench-secrets.env; set +a         # loads ANONTOOL_KEY, ANONTOOL_URL, …

# full 5-model / 1000-request run, all scenarios + patterns:
SCENARIOS="anontool-nosleep,anontool-sleep,ray,kserve" \
NUM_SAMPLES=1000 SKIP_CALIBRATION=1 SHELLY=1 \
GPU_HOSTS="deipapa.ase.cit.tum.de deimama.aet.cit.tum.de" \
GPU_SSH_USER=logos-server \
  logos/benchmarks/run_bench.sh
```

`/root/bench-secrets.env` (git-ignored, on `logos-test`) holds at least:

```bash
ANONTOOL_KEY=<root key authorized on the GPU nodes>
ANONTOOL_URL=https://logos-test.aet.cit.tum.de
PYTHON=/root/bench-venv/bin/python
```

### Energy / Shelly wall power
`SHELLY=1` measures wall power via the Shelly plug. The campus firewall only
passes 443, so the pipeline starts a Traefik-routed HTTPS ingest sidecar and the
Raspberry-Pi `shelly_daemon.py` POSTs readings to it. Energy is written only to
`energy_timeline.csv` (per-second trace) — never to the request summary/detail.

### Calibration (expensive)
`SKIP_CALIBRATION=1` reuses the existing `model_profiles.yml` on the nodes. To
recalibrate: `RESET_CALIBRATION=1 CALIBRATION_PROVIDER_IDS="3 2"` (re-downloads
all weights — hours).

## Provisioning notes (real cluster)
- HF cache: `/mnt/ceph/.hf_cache` on both GPU nodes; `HF_TOKEN` in the workernode
  `.env`.
- `deipapa` (RTX/GPU node) + `deimama` — 2 GPUs each, `tensor_parallel_size=2`.
- Baselines (Ray / KServe) share the same GPUs; the harness teardown-barrier
  frees them between scenarios.
