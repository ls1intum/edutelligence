# Page load times

This page shows where the slow pages of the web application spend their time.
It also shows what was changed and what is left to do. Every number on this page
comes from production data. Each number comes from one of two sources. The first
source is the query of the page, run on the production host (`ssh logos`,
read-only). The second source is a full snapshot of the production data,
restored locally. Each measurement names its source. The two sources differ by
a factor of about 4. If this page gave only the local number, it would
understate the problem.

Snapshot used on this page: 2026-09-17, 689,682 `log_entry` rows, 2,419,395
`usage_tokens` rows, 530k `provider_snapshots` rows.

## Summary

| Page | Query | Before (prod) | After | Fixed by |
|---|---|---|---|---|
| Statistics | 8 aggregates per load | 6,460 ms | ~50 ms¹ | hourly rollup (035) |
| Statistics | enqueue event payload | 25 MB / load | none | chart reads the server series |
| Models | `findAllWithPricing` | 9,648 ms | ~2 ms¹ | index (036) |
| Billing | `findTeamBudgetHistory` | 18,264 ms | ~2,400 ms² | `log_entry_cost` restructured |

¹ Measured on the local snapshot. The local snapshot runs ~4x faster than the production host.
The production figure is higher in absolute terms and has a similar ratio.
² Extrapolated from the snapshot figure (4,746 ms -> 693 ms) with the same 4x factor.

## Statistics page

### What was wrong

Every aggregate behind the page filters `log_entry` on this expression:

```sql
COALESCE(timestamp_forwarding, timestamp_request, timestamp_response)
```

No index covered the expression. Thus each of the eight queries did a
sequential scan of the table. On the production host, one page load used
6,460 ms of database time. The `findTotals` query alone used 3,443 ms of it.

In addition, the page sent **25 MB of JSON per load**. The browser drew the
request-volume chart from the raw enqueue event of every request in the range.
This path was also wrong. See "Request volume" below.

### Why an index is not the answer

We built an expression index on that `COALESCE` and measured it. It does not
help the default view. The 30-day preset selects ~60% of the table (416,722 of
689,682 rows). At this selectivity, a sequential scan is the cheaper plan. The
planner correctly continues to choose it. Several queries became *slower* with
the index, because the index caused bitmap scans.

To count 400k rows into 120 buckets is O(n) work. Only pre-aggregation removes
this work.

### What was done

`log_entry_hourly_stats` (migration 035) is an hourly rollup with this grain:

```
(bucket_hour, model_id, provider_id, team_id, user_id, result_status, was_cold_start)
```

The entire history becomes **12,591 rows / 3.4 MB**. This is a reduction by a
factor of 55.

These properties are important:

- **Whole hours only.** The rollup never includes the partial current hour.
  Thus the reader always has the live branch for this hour.
- **Ids, not derived values.** `provider_id` and `model_id` stay as ids. The
  reader joins `providers` and `models` live. Thus a renamed model or a changed
  privacy level shows without a new pass.
- **Sums and counts, never averages.** An average of pre-averaged hours gives a
  quiet hour the same weight as a busy hour.

The reader (`LogEntryRepository`) combines two data sources with a union. The
first source is the rollup for the hours below the watermark. The second source
is `log_entry` for the partial head hour and all newer data. All aggregates use
one shared split point (`logos_stats_rollup_window`). The sharing is
intentional. Assume that two aggregates differ by one hour about the end of the
rollup. Then one aggregate counts the overlap twice and another aggregate
drops a gap.

The reader reads both bounds as scalar subqueries: `(SELECT mv_lo FROM w)`. It
does not join the window into the `FROM` list. This is necessary and not a
matter of style. If the query joins the window, the bound is a join column.
Postgres cannot use a join column as an index condition. Then Postgres
materializes every row of the range, including the token `LATERAL` and the cost
join. After that it filters down to the live tail. On the production snapshot,
this takes **1,837 ms against 52 ms** for the same answer.

### Freshness: why a table and not a materialized view

A `log_entry` row can change after its hour closes. The orchestrator writes the
status, the response time, and the tokens when the request finishes. Cost
settlement can come days later. On production, the oldest unsettled completed
row is 9.5 days old. A rollup that is rebuilt completely cannot handle this. It
cannot retract the old contribution of a row. Thus it continues to show the
value that was true at the last build.

For this reason, the rollup is a table that Logos maintains incrementally.
`log_entry` has an `updated_at` column that a trigger sets. Each pass
recomputes exactly the hours with rows that changed since the last pass:

| | measured on the production snapshot |
|---|---|
| initial backfill | 3.7 s |
| `ALTER TABLE ADD COLUMN updated_at` | 4 ms (no rewrite — the column has no default) |
| a pass with nothing changed | **2.9 ms** |
| a pass after a late settlement on a 10-month-old row | **110 ms** (1 hour, 2 rows) |

For this reason, the pass runs every minute and not every hour. It also finds a
settlement that comes days later in the same way as a request that just
finished.

Two limits apply to the stale data:

- **The pass interval.** A row that changes between two passes is stale for
  about 1 minute. A pass also keeps its cutoff one `write-lag` (1 minute)
  behind `now()`. Thus the pass cannot skip a write transaction that starts
  before the cutoff and commits after the cutoff. This adds one more pass of
  latency. For this reason, the lag is a parameter and not a constant.
- **The freshness guard of the reader.** If no pass completes within 15
  minutes, `logos_stats_rollup_window` returns an empty window. Then every
  aggregate reads `log_entry`. Logos does not trust a rollup that nobody
  maintains. The page becomes slow, but it does not become wrong.

`RequestLogStatsRollupTest` tests all of these points. It tests that the next
pass corrects a changed row. It tests that a row that moves to a later hour
leaves no count in the hour that it left. It tests that an aged state row
sends every aggregate to the live data with identical numbers.

### Three queries nothing rendered

`findQueueDepth`, `findRuntimeByColdStart` and `findLastEventTs` ran on every
aggregate push. The TypeScript types of the page declare their results, but no
component reads them. These queries used ~700 ms per push on production for
data that nobody saw. We removed them. We also removed the `avgVram` column of
the time series. The client only set this column to `null`.

When we removed `findQueueDepth`, we also removed the one aggregate that a
rollup cannot serve. `PERCENTILE_CONT(0.95)` cannot be computed from sums per
hour.

## Request volume was broken

The chart was not slow. It was wrong. The browser built the chart from the raw
enqueue events of every request in the range. The server limited these events to
200,000 rows, ordered **oldest first**:

```sql
ORDER BY le.timestamp_request, le.request_id LIMIT 200000
```

The default 30-day window holds 416,722 requests on production. Thus the chart
silently lost all data after the cut. On the snapshot, the most recent
**12 days 22 hours** of the default view were missing. The chart showed a flat
line. The KPI card directly above the chart counted all 416,722 requests.

The fix is to stop the derivation of the series in the browser.
`stats.timeSeries` is aggregated in the database over the whole range. It
arrives already bucketed and has a size of a few kilobytes. We removed the
200k-event payload, its delta stream, the client-side re-bucketing, and the
three repository queries behind them.

This changes one behavior. Before, the chart redrew from the event deltas every
2 s. Now the chart updates with the aggregate push, which is at most every 10 s.
The smallest bucket of the chart is 15 minutes (the "today" preset) and the
default is six hours. Thus the extra 8 s are not visible. The KPI cards next
to the chart already used the aggregate push. They did not change.

## Models page

`ModelRepository.findAllWithPricing` took **9,648 ms on production**. One
`LEFT JOIN LATERAL` used 9,500 ms of this time. This join finds the most
recently used provider of each model. It used 195 ms for each model, for 49
models.

A comment said that the `(model_id, timestamp_request)` index of migration 014
made this query a single index seek. This was not true. That index does not
contain `provider_id`, and the lateral filters on `provider_id IS NOT NULL`.
Thus the planner chose `idx_log_entry_performance_window` instead. Its columns
are `(timestamp_request DESC, provider_id, model_id)`. This index is covering,
but `model_id` is the third column. An equality on a non-leading column cannot
use a seek. Thus each model walked the index in timestamp order until a row of
the model appeared.

Migration 036 adds `(model_id, timestamp_request DESC) INCLUDE (provider_id)
WHERE provider_id IS NOT NULL`. The first column is `model_id`, so the equality
is a seek. The second column is `timestamp_request`, so `LIMIT 1` stops at the
first row. The index includes `provider_id`, so the scan stays index-only.

Snapshot: 252 ms -> 1.7 ms for the whole query. The lateral changed from 5.1 ms
to 0.004 ms for each model.

## Billing page

`findTeamBudgetHistory` took **18,264 ms on production**. There were two
causes. Both are in the way `log_entry_cost` was written:

1. The token rollup of the view was a `LEFT JOIN LATERAL ... ON NOT le.cost_finalized
   AND ...`. The database evaluates a lateral for every row and filters it
   with the `ON` clause only after that. Thus every settled row paid for a full
   `usage_tokens` aggregation before the join discarded the row. The plan shows
   this: 415,233 aggregations ran, and the join filter removed 415,211 rows.
   Only **22** rows needed the aggregation.
2. Billing joined `log_entry` a second time together with the view. Thus the
   database fetched each row twice by primary key.

We restructured the view. The token rollup is now a scalar subquery *inside* the
`CASE` branches that use it. Thus the work occurs only where it is necessary.
The database evaluates a subquery in a `CASE` branch only when it takes that
branch.

We verified the equivalence against the full snapshot. All 689,682 rows give
identical values and identical totals. Snapshot timing: 4,746 ms -> 693 ms.

## Still open

- **The billing join.** The view fix did not change one problem. The plan joins
  `api_keys` to `log_entry` as a nested loop with a join filter. This makes 46.9M
  pair comparisons for 415k rows. This needs a review. It is a planner and
  statistics question and not a missing index. The view fix already moved the
  query out of the "unusable" range.
- **`provider_snapshots`.** The table has 530k rows / 10 GB for a retention
  window of 7 days. JSONB payload uses 9.5 GB of this size. Nothing on the
  statistics page reads the history now. We removed the VRAM-remaining chart
  that did. The page reads only the latest sample for each provider. Review the
  retention window and the payload columns.
- **Per-tab subscriptions.** The two statistics tabs share one websocket. This
  websocket pushes both VRAM and aggregates, for any open tab. Both are cheap
  now (~20 ms and ~107 ms). Thus the change of the protocol is not necessary
  yet.
