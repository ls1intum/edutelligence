# GlobalSearchPipeline end-to-end evaluation

- date: 2026-07-07T14:13:44
- suite: 150 questions · modes: no_classifier
- entity prefetch: BM25 over Artemis_SearchableEntities (types ['exercise', 'faq', 'exam', 'channel'], limit 15) — simulates Artemis IrisLectureSearchResource.prefetchEntities

## Mode: no_classifier

- decision correctness: **110/150** (73.3%)
- answer recall (should-answer answered): 73.2% (82/112)
- answer precision (answers that were expected): 89.1%
- **grounding failures** (answered when null expected): 10/38

| category           | n   | correct | acc  |
| ------------------ | --- | ------- | ---- |
| DL/basic           | 15  | 15      | 1.00 |
| DL/smart           | 20  | 14      | 0.70 |
| DL/typos           | 10  | 9       | 0.90 |
| DL/vague           | 10  | 7       | 0.70 |
| PSE                | 15  | 10      | 0.67 |
| admin/cross        | 5   | 4       | 0.80 |
| concurrent         | 5   | 2       | 0.40 |
| entities/channels  | 8   | 3       | 0.38 |
| entities/courses   | 3   | 3       | 1.00 |
| entities/exercises | 10  | 8       | 0.80 |
| entities/lectures  | 4   | 0       | 0.00 |
| mixed              | 15  | 13      | 0.87 |
| out-of-scope       | 20  | 19      | 0.95 |
| vague/short        | 10  | 3       | 0.30 |

- hyde_ms: p50 1454 · p95 2405 · mean 1685 (n=150)
- retrieval_ms: p50 554 · p95 994 · mean 612 (n=150)
- answer_ms: p50 1683 · p95 2984 · mean 1723 (n=150)
- total_ms: p50 3761 · p95 5836 · mean 4043 (n=150)
- events: none
- handoff distribution (answered queries): {'lecture': 42, 'course': 33, 'exercise': 3, 'none': 14}
