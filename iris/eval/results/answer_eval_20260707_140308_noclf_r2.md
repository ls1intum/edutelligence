# GlobalSearchPipeline end-to-end evaluation

- date: 2026-07-07T14:03:08
- suite: 150 questions · modes: no_classifier
- entity prefetch: BM25 over Artemis_SearchableEntities (types ['exercise', 'faq', 'exam', 'channel'], limit 15) — simulates Artemis IrisLectureSearchResource.prefetchEntities

## Mode: no_classifier

- decision correctness: **113/150** (75.3%)
- answer recall (should-answer answered): 74.1% (83/112)
- answer precision (answers that were expected): 91.2%
- **grounding failures** (answered when null expected): 8/38

| category           | n   | correct | acc  |
| ------------------ | --- | ------- | ---- |
| DL/basic           | 15  | 15      | 1.00 |
| DL/smart           | 20  | 13      | 0.65 |
| DL/typos           | 10  | 9       | 0.90 |
| DL/vague           | 10  | 8       | 0.80 |
| PSE                | 15  | 11      | 0.73 |
| admin/cross        | 5   | 4       | 0.80 |
| concurrent         | 5   | 2       | 0.40 |
| entities/channels  | 8   | 2       | 0.25 |
| entities/courses   | 3   | 3       | 1.00 |
| entities/exercises | 10  | 8       | 0.80 |
| entities/lectures  | 4   | 0       | 0.00 |
| mixed              | 15  | 14      | 0.93 |
| out-of-scope       | 20  | 19      | 0.95 |
| vague/short        | 10  | 5       | 0.50 |

- hyde_ms: p50 1395 · p95 2620 · mean 1652 (n=150)
- retrieval_ms: p50 593 · p95 1048 · mean 645 (n=150)
- answer_ms: p50 1503 · p95 3100 · mean 2101 (n=150)
- total_ms: p50 3562 · p95 6572 · mean 4422 (n=150)
- events: {'refusal_suppressed': 1}
- handoff distribution (answered queries): {'course': 33, 'lecture': 43, 'exercise': 3, 'none': 12}
