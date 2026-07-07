# GlobalSearchPipeline end-to-end evaluation

- date: 2026-07-07T02:46:41
- suite: 150 questions · modes: no_hyde
- entity prefetch: BM25 over Artemis_SearchableEntities (types ['exercise', 'faq', 'exam', 'channel'], limit 15) — simulates Artemis IrisLectureSearchResource.prefetchEntities

## Mode: no_hyde

- decision correctness: **109/150** (72.7%)
- answer recall (should-answer answered): 65.2% (73/112)
- answer precision (answers that were expected): 97.3%
- **grounding failures** (answered when null expected): 2/38

| category           | n   | correct | acc  |
| ------------------ | --- | ------- | ---- |
| DL/basic           | 15  | 11      | 0.73 |
| DL/smart           | 20  | 12      | 0.60 |
| DL/typos           | 10  | 5       | 0.50 |
| DL/vague           | 10  | 8       | 0.80 |
| PSE                | 15  | 10      | 0.67 |
| admin/cross        | 5   | 5       | 1.00 |
| concurrent         | 5   | 2       | 0.40 |
| entities/channels  | 8   | 2       | 0.25 |
| entities/courses   | 3   | 3       | 1.00 |
| entities/exercises | 10  | 7       | 0.70 |
| entities/lectures  | 4   | 0       | 0.00 |
| mixed              | 15  | 14      | 0.93 |
| out-of-scope       | 20  | 20      | 1.00 |
| vague/short        | 10  | 10      | 1.00 |

- retrieval_ms: p50 305 · p95 443 · mean 311 (n=150)
- answer_ms: p50 1400 · p95 2670 · mean 1578 (n=135)
- total_ms: p50 1607 · p95 2954 · mean 1764 (n=150)
- events: none
- handoff distribution (answered queries): {'course': 27, 'lecture': 32, 'exercise': 3, 'none': 13}
