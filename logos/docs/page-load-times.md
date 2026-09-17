# Page load times

Where the web application's slow pages spend their time, what was changed about it, and
what is left. Every number here was measured against production data: either by
running the page's own query on the production host (`ssh logos`, read-only), or
against a full snapshot of it restored locally. Both are named per measurement,
because they differ by roughly 4x and quoting the local one alone would
understate the problem.

Snapshot used throughout: 2026-09-17, 689,682 `log_entry` rows, 2,419,395
`usage_tokens` rows, 530k `provider_snapshots` rows.

## Summary

| Page | Query | Before (prod) | After | Fixed by |
|---|---|---|---|---|
| Statistics | 8 aggregates per load | 6,460 ms | ~50 ms¹ | hourly rollup (035) |
| Statistics | enqueue event payload | 25 MB / load | none | chart reads the server series |
| Models | `findAllWithPricing` | 9,648 ms | ~2 ms¹ | index (036) |
| Billing | `findTeamBudgetHistory` | 18,264 ms | ~2,400 ms² | `log_entry_cost` restructured |

¹ measured on the local snapshot, which runs ~4x faster than the production host;
the production figure will be higher in absolute terms and similar in ratio.
² extrapolated from the snapshot's 4,746 ms -> 693 ms at the same 4x factor.

## Statistics page

### What was wrong

Every aggregate behind the page filters `log_entry` on the expression

```sql
COALESCE(timestamp_forwarding, timestamp_request, timestamp_response)
```

No index covered it, so each of the eight queries sequentially scanned the
table. Measured on the production host, one page load cost 6,460 ms of database
time, 3,443 ms of it in `findTotals` alone.

On top of that the page shipped **25 MB of JSON per load**: the request-volume
chart was drawn in the browser from the raw enqueue event of every request in
the range. That path was also wrong — see "Request volume" below.

### Why an index is not the answer

An expression index on that `COALESCE` was built and measured. It does not help
the default view: the 30-day preset selects ~60% of the table (416,722 of
689,682 rows), and at that selectivity a sequential scan is the cheaper plan.
The planner correctly keeps choosing it, and several queries got *slower* with
the index present because it tipped them into bitmap scans.

Counting 400k rows into 120 buckets is O(n) work. Only pre-aggregation removes
it.

### What was done

`log_entry_hourly_stats` (migration 035): an hourly rollup at the grain

```
(bucket_hour, model_id, provider_id, team_id, user_id, result_status, was_cold_start)
```

The entire history collapses to **12,591 rows / 3.4 MB** — a factor of 55.

Properties that matter:

- **Whole hours, and only ones that closed six hours ago.** A closed hour does
  not make its rows immutable — a request forwarded at 04:59 and still running
  at the 05:05 refresh would be rolled up with no status, duration, tokens or
  cost, and its effective timestamp puts it below the watermark where the live
  branch can no longer correct it. Production carries 1,050 such rows in closed
  hours. Six hours is sized against the request timeout rather than a
  percentile: a request cannot outlive `LOGOSNODE_INFER_TIMEOUT_SECONDS`, 600 s
  in production, so the gap is roughly 36× the longest one can still be
  running.
- **The boundary is a function of time alone.** Excluding rows by a mutable flag
  would look tighter and be worse: the rollup would hold what the flag said at
  refresh time while the reader tested what it says now, so a row that settled
  in between would belong to neither branch and drop out of the totals. A time
  boundary partitions the range exactly once regardless of what any row does
  afterwards.

### What the gap does not cover

Cost settlement has no timeout. It can land days after the request finished —
production's oldest unsettled completed row is 9.5 days old — so it changes rows
that are already inside the rollup. Those carry a stale cost until the next
rebuild.

That is bounded staleness, not a number that stays wrong: `REFRESH` recomputes
the whole view, so at most one refresh interval separates a late correction from
the page. `RequestLogStatsRollupTest` pins both halves — that a row past the
cutoff really is in the rollup and does not follow a change until a refresh, and
that a request still running is kept on the live side and does.

Removing even that window means tracking mutations, so a changed row leaves the
rollup and rejoins it. A view rebuilt whole cannot do it: it has no way to
retract a row's stale contribution, so any "take changed rows live as well"
rule double-counts them. It needs incremental maintenance over a real table —
listed under *Still open* below.
- **Ids, not derived values.** `provider_id`/`model_id` stay as ids and the
  reader joins `providers`/`models` live, so a renamed model or a changed
  privacy level shows up without a refresh.
- **Sums and counts, never averages.** Averaging pre-averaged hours would weight
  a quiet hour like a busy one.

The reader (`LogEntryRepository`) unions the rollup for hours below the
watermark with `log_entry` for the partial head hour and everything newer, using
one shared split point (`logos_stats_rollup_window`). Sharing it is deliberate:
if two aggregates disagreed by an hour about where the rollup ends, one would
double-count the overlap and another would drop a gap.

**A stale refresh costs query time, not correctness.** Because the split is
purely temporal, a lagging or failed refresh moves work back to `log_entry`
without changing a number. `RequestLogStatsRefreshService` refreshes hourly
(`REFRESH ... CONCURRENTLY`, guarded by a transaction-scoped advisory lock).
The transactional half lives in its own bean: Spring applies `@Transactional`
through a proxy, so a scheduled method calling it on `this` would run with no
transaction at all — and the advisory lock, being transaction-scoped, would then
be released the moment it was taken and guard nothing.

Sub-hour buckets (the "last hour"/"today" presets) bypass the rollup entirely —
it cannot express them — and are served from `log_entry` via the expression
index, which *is* the right tool at that selectivity.

Measured on the snapshot, the aggregates went from 1,769 ms to 22 ms; the merged
reader answers the 30-day totals in 51 ms against 504 ms live, with a 5.7-hour
live tail in play.

### Three queries nothing rendered

`findQueueDepth`, `findRuntimeByColdStart` and `findLastEventTs` were run on
every aggregate push. Their results are declared in the page's TypeScript types
and read by no component. That was ~700 ms per push on production for data
nobody displayed. Removed, along with the `avgVram` column of the time series,
which the client only ever set to `null` itself.

Removing `findQueueDepth` also removed the one aggregate a rollup cannot serve:
`PERCENTILE_CONT(0.95)` is not computable from per-hour sums.

## Request volume was broken

Not slow — wrong. The chart was built client-side from the raw enqueue events of
every request in the range, which the server capped at 200,000 rows ordered
**oldest first**:

```sql
ORDER BY le.timestamp_request, le.request_id LIMIT 200000
```

The default 30-day window holds 416,722 requests on production. So the chart
silently lost everything after the cut: measured against the snapshot, the most
recent **12 days 22 hours** of the default view were missing — a flat line —
while the KPI card directly above it counted all 416,722 requests.

The fix is to stop re-deriving the series in the browser. `stats.timeSeries` is
aggregated in the database over the whole range, arrives already bucketed, and
costs a few kilobytes. The 200k-event payload, its delta stream, the client-side
re-bucketing and the three repository queries behind them are gone.

One behavioural consequence: the chart used to redraw from the event deltas every
two seconds and now moves with the aggregate push, so at most every ten. Its
smallest bucket is 15 minutes (the "today" preset) and its default is six hours,
so the extra eight seconds are not visible. The KPI cards beside it already ran
on the aggregate push and are unchanged.

## Models page

`ModelRepository.findAllWithPricing` took **9,648 ms on production**, of which
9,500 ms sat in one `LEFT JOIN LATERAL` resolving each model's most recently used
provider — 195 ms per model across 49 models.

A comment claimed migration 014's `(model_id, timestamp_request)` made this a
single index seek. It did not. That index does not carry `provider_id`, and the
lateral filters on `provider_id IS NOT NULL`, so the planner instead chose
`idx_log_entry_performance_window` — `(timestamp_request DESC, provider_id,
model_id)` — which is covering but has `model_id` third. Equality on a
non-leading column is not seekable, so every model walked the index in timestamp
order until one of its rows turned up.

Migration 036 adds `(model_id, timestamp_request DESC) INCLUDE (provider_id)
WHERE provider_id IS NOT NULL`: model_id leads so the equality is a seek,
timestamp_request follows so `LIMIT 1` stops at the first row, provider_id rides
along so the scan stays index-only.

Snapshot: 252 ms -> 1.7 ms for the whole query; the lateral from 5.1 ms to
0.004 ms per model.

## Billing page

`findTeamBudgetHistory` took **18,264 ms on production**. Two causes, both in
how `log_entry_cost` was written:

1. The view's token rollup was a `LEFT JOIN LATERAL ... ON NOT le.cost_finalized
   AND ...`. A lateral is evaluated for every row and only *then* filtered by its
   `ON` clause, so every settled row paid for a full `usage_tokens` aggregation
   before the join discarded it. The plan shows it plainly: 415,233 aggregations
   run, 415,211 rows removed by the join filter. Only **22** rows needed it.
2. Billing joined `log_entry` a second time alongside the view, so each row was
   fetched twice by primary key.

Restructuring the view so the token rollup is a scalar subquery *inside* the
`CASE` branches that use it makes the work happen only where it is used —
a subquery in a `CASE` branch is evaluated only when that branch is taken.

Verified equivalent against the full snapshot: all 689,682 rows produce
identical values, identical totals. Snapshot timing 4,746 ms -> 693 ms.

## Still open

- **The billing join.** Even after the view fix, the plan joins `api_keys` to
  `log_entry` as a nested loop with a join filter — 46.9M pair comparisons for
  415k rows. Worth a look, but it is a planner/statistics question rather than a
  missing index, and the view fix already took the query out of the "unusable"
  range.
- **Incremental rollup refresh.** `REFRESH ... CONCURRENTLY` rebuilds all 12.5k
  rows hourly. That is cheap today, but a real table upserted per changed hour
  would buy two things at once: a refresh proportional to new traffic rather
  than to history, and the ability to retract a row's contribution when it
  changes — which is what would close the late-settlement staleness window
  above. It needs a change marker on `log_entry` (an `updated_at` maintained by
  a trigger would do) so the upsert knows which hours to recompute.
- **`provider_snapshots`.** 530k rows / 10 GB for a 7-day retention window, 9.5 GB
  of it JSONB payload. Nothing on the statistics page reads the history any more
  (the VRAM-remaining chart that did has been removed), only the latest sample
  per provider. The retention window and the payload columns are worth revisiting.
- **Per-tab subscriptions.** The two statistics tabs share one websocket, which
  still pushes both VRAM and aggregates regardless of which tab is open. Both are
  cheap now (~20 ms and ~107 ms), so this was not worth the protocol change yet.
