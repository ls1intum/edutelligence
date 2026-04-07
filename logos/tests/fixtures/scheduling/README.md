# Scheduling Workload CSVs

Each workload lives in this directory and must be a UTF-8 CSV with the following header row:

```
request_id,arrival_offset,mode,priority,body_json
```

## Field Details

- `request_id` *(optional)*: unique identifier for the row. If omitted, IDs are auto-generated in row order.
- `arrival_offset` *(required)*: float milliseconds (relative to the start of the replay) when this request should be issued.
- `mode` *(optional)*: request mode, either `"interactive"` or `"batch"`. Defaults to `"interactive"` if not specified.
  - **interactive**: Real-time user-facing requests requiring low latency
  - **batch**: Background processing requests that can tolerate higher latency
- `priority` *(optional)*: request priority level, one of `"low"`, `"mid"`, or `"high"`. Defaults to `"mid"` if not specified.
  - **low**: Priority value 1 (best-effort, can be delayed)
  - **mid**: Priority value 5 (standard priority)
  - **high**: Priority value 10 (urgent, should be processed first)
- `body_json` *(required)*: complete JSON string for the request body. Must be valid JSON.

## Model Selection Behavior

Logos supports two modes of operation that can be controlled via the request payload:

### Direct Model Selection (Skip Classification)

If `body_json` includes a `"model"` field that matches an existing database model name, the request will be sent directly to that model. Classification is skipped.

**Example:**
```csv
request_id,arrival_offset,mode,priority,body_json
req-1,1500,batch,low,"{""model"":""qwen3:30b-a3b"",""messages"":[{""role"":""user"",""content"":""Explain quicksort algorithm""}]}"
```

**Use case:** Benchmarking scheduling behavior with a fixed model.

### Classification Mode (Let Logos Choose)

If the `"model"` field is absent or doesn't match any database model, Logos will run its classification pipeline to select the best model based on the prompt content and policy settings.

**Example:**
```csv
request_id,arrival_offset,mode,priority,body_json
req-1,1500,interactive,high,"{""messages"":[{""role"":""user"",""content"":""Explain quicksort algorithm""}]}"
```

**Use case:** Benchmarking classification + scheduling together.

### Verifying Which Mode Was Used

Check the output CSV or database:
- If `classification_statistics` is NULL → Direct model selection
- If `classification_statistics` contains data → Classification ran

## Sample Workloads

- `sample_workload_direct.csv` - All requests use direct model selection (no classification)
- `sample_workload_classify.csv` - All requests trigger classification
- `sample_workload_mixed.csv` - Mix of both modes in one workload
- `sample_workload.csv` - Default mixed example

## Notes

- JSON strings must use double-quoted strings and escape internal quotes with `""` (CSV standard)
- For programmatic generation, use Python's `csv` module with `json.dumps()`
- `mode` and `priority` columns are optional; omit them for default values (interactive, mid)
- Additional columns are ignored
