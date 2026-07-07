# GlobalSearchPipeline end-to-end evaluation

- date: 2026-07-07T13:46:03
- suite: 150 questions · modes: no_hyde
- entity prefetch: BM25 over Artemis_SearchableEntities (types ['exercise', 'faq', 'exam', 'channel'], limit 15) — simulates Artemis IrisLectureSearchResource.prefetchEntities

## Mode: no_hyde

- decision correctness: **113/150** (75.3%)
- answer recall (should-answer answered): 68.8% (77/112)
- answer precision (answers that were expected): 97.5%
- **grounding failures** (answered when null expected): 2/38

| category           | n   | correct | acc  |
| ------------------ | --- | ------- | ---- |
| DL/basic           | 15  | 12      | 0.80 |
| DL/smart           | 20  | 12      | 0.60 |
| DL/typos           | 10  | 5       | 0.50 |
| DL/vague           | 10  | 9       | 0.90 |
| PSE                | 15  | 12      | 0.80 |
| admin/cross        | 5   | 5       | 1.00 |
| concurrent         | 5   | 3       | 0.60 |
| entities/channels  | 8   | 2       | 0.25 |
| entities/courses   | 3   | 3       | 1.00 |
| entities/exercises | 10  | 7       | 0.70 |
| entities/lectures  | 4   | 0       | 0.00 |
| mixed              | 15  | 13      | 0.87 |
| out-of-scope       | 20  | 20      | 1.00 |
| vague/short        | 10  | 10      | 1.00 |

- retrieval_ms: p50 346 · p95 393 · mean 403 (n=150)
- answer_ms: p50 1486 · p95 2758 · mean 1726 (n=135)
- total_ms: p50 1760 · p95 3158 · mean 1990 (n=150)
- events: none
- handoff distribution (answered queries): {'course': 27, 'lecture': 36, 'exercise': 3, 'none': 13}
