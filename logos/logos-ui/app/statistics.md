# Statistics Page Data Flow

This document explains what each chart on [`statistics.tsx`](./statistics.tsx) renders, where its data comes from, and how it is transported.

## Charts on the page

1. `Recent Requests`

- Component: `RequestStack`
- Data: latest request-event rows (`request_id`, model/provider, status, queue/run timing, priority, error)
- Source: backend `DBManager.get_latest_requests(...)`

2. `VRAM Utilization` (donut)

- Components: `PlotlyPieChart` (web) or `react-native-gifted-charts` pie (native)
- Data: latest VRAM snapshot for selected Ollama provider:
  - used/free/total VRAM
  - loaded models and per-model VRAM
- Source: backend `DBManager.get_ollama_vram_deltas(...)` (ws v2) or `get_ollama_vram_stats(...)` (legacy/fallback)

3. `Request Volume`

- Components:
  - Web: `PlotlyRequestVolumeChart` (provider stack + model stack modes)
  - Native: `InteractiveZoomableChart`
- Data:
  - aggregated time-series (`cloud`, `local`, `total`) for selected range
  - optional per-model bucket counts
  - raw enqueue events used for accurate client-side re-bucketing when zooming
- Source: backend `DBManager.get_request_event_stats(...)` + `get_request_enqueues_in_range(...)`

4. `Request Type` (cloud vs local)

- Components: same pie strategy as above (Plotly on web, gifted-charts on native)
- Data: `stats.totals.cloudRequests` and `stats.totals.localRequests`

5. `Model Share`

- Components: same pie strategy as above
- Data: top models from `stats.modelBreakdown`

6. `VRAM Remaining` (time-series)

- Components:
  - Web: `PlotlyVramChart`
  - Native: `VramChart` (gifted-charts line chart)
- Data: per-provider VRAM snapshots over time, with day filter
- Source: websocket deltas (`vram_init` / `vram_delta`) or HTTP fallback

## Transport: websocket vs HTTP

## Primary path (current)

- Hook: `useStatsWebSocketV2`
- Endpoint: `GET ws://.../ws/stats/v2?key=<logos_key>`
- Initial client message:
  - `action: "init"`
  - selected VRAM day
  - timeline range + target buckets
  - `timeline_deltas: false` (client disables timeline delta polling to avoid unused work)
- Server push cadence:
  - latest requests: every ~2s (only when changed)
  - VRAM deltas: every ~5s (incremental by snapshot cursor)
  - timeline deltas: optional (disabled by this page)

## Fallback / legacy paths

- Legacy `/ws/stats` still exists server-side for compatibility, but the current statistics page does not use it.
- HTTP endpoint used for VRAM recovery/manual refresh:
  - `POST /logosdb/get_ollama_vram_stats`

## Chart libraries

1. `Plotly` (web only)

- Loaded at runtime via `plotly-loader.web.ts` (CDN script)
- Used by:
  - `plotly-request-volume-chart.web.tsx`
  - `plotly-vram-chart.web.tsx`
  - `plotly-pie-chart.web.tsx`

2. `react-native-gifted-charts` (native + non-Plotly paths)

- Used for line/pie rendering in:
  - `interactive-zoomable-chart.tsx`
  - `vram-chart.tsx`
  - pie charts in `statistics.tsx`

## Where VRAM utilization originates

VRAM values are not guessed by the UI. They are collected server-side from Ollama runtime state:

1. The monitor layer polls Ollama admin API (`/api/ps`) to read currently loaded models and `size_vram` usage.
2. Poll results are written into `ollama_provider_snapshots` (`total_vram_used_bytes`, `loaded_models`, timestamps).
3. Statistics endpoints/websockets read these snapshots and convert them to chart payloads (`used_vram_mb`, `remaining_vram_mb`, etc.).

Relevant backend files:

- `src/logos/monitoring/ollama_monitor.py`
- `src/logos/dbutils/dbmanager.py`
- `src/logos/main.py` (`/ws/stats/v2`, `/logosdb/get_ollama_vram_stats`)
