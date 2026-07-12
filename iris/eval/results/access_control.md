# Access-control adversarial checks

- date: 2026-07-12T23:28:09

| case | check | result | detail |
|---|---|---|---|
| A1 | student of course 7 gets results | PASS | 20 results |
| A2 | all results belong to course 7 | PASS | courses seen: {7} |
| A3 | non-existent course id yields nothing | PASS | 0 results |
| A4 | course 9 context never returns course 7 content | PASS | courses seen: {9} |
| B1 | empty courseIds returns zero results | PASS | 0 results |
| C1 | unreleased units hidden from students | PASS | 12 hidden, 0 leaked (now=2025-06-30, dated units=12) |
| C2 | same units visible to staff (filter is role-scoped) | PASS | 12 dated unit(s) retrievable as staff |
| D1 | SKIP_AI returns no answer | PASS |  |
| D2 | SKIP_AI consumed zero LLM tokens | PASS | token entries: 0 |
| D3 | SKIP_AI still returns search results | PASS | 4 sources |
| E1 | missing model dir falls open to TRIGGER_AI | PASS | output: trigger_ai |

**11/11 passed**