# Scheduling Workload CSVs

Each workload lives in this directory and must be a UTF-8 CSV with the following header row:

```
request_id,arrival_offset,prompt,mode[,body_json][,body_template]
```

Field details:

- `request_id` *(optional)*: unique identifier for the row. If omitted, IDs are auto-generated in row order.
- `arrival_offset` *(required)*: float seconds (relative to the start of the replay) when this request should be issued.
- `prompt` *(required)*: user-facing text used in the default payload or template substitution.
- `mode` *(required)*: string passed through to the API (e.g., `interactive`).
- `body_json`: raw JSON string for the request body. Must be valid JSON if present.
- `body_template`: JSON template with `${prompt}` placeholder; used when `body_json` is absent.

Notes:
- Provide either `body_json` *or* `body_template`; the runner falls back to a minimal payload if both are empty.
- Any JSON column should contain a double-quoted, serialized JSON string (run workload CSVs through `json.dumps` if generated programmatically).
- Additional columns are ignored.

See `sample_workload.csv` for a working example.
