"""Read public dataset metadata and a bounded preview from the HF viewer."""

import json
from typing import Any

import httpx
from fastapi import HTTPException


async def _get_json(url: str, params: dict[str, Any]) -> Any:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 401, 403, 404, 422}:
            raise HTTPException(
                400,
                "Dataset metadata unavailable. Choose a public, ungated dataset supported by the Hugging Face viewer.",
            ) from exc
        raise HTTPException(503, "Hugging Face is temporarily unavailable. Try again.") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(503, "Could not load Hugging Face metadata. Try again.") from exc


async def search_datasets(query: str) -> dict[str, Any]:
    """Search the Hub for public datasets, returning identifiers only."""
    rows = await _get_json(
        "https://huggingface.co/api/datasets",
        {
            "search": query,
            "limit": 20,
            "sort": "downloads",
            "direction": -1,
        },
    )
    return {
        "datasets": [
            {"id": row["id"]} for row in rows if row.get("id") and not row.get("private") and not row.get("gated")
        ]
    }


async def dataset_metadata(dataset: str, subset: str | None = None, split: str | None = None) -> dict[str, Any]:
    """Resolve configurations, splits and text columns for the dataset picker."""
    data = await _get_json("https://datasets-server.huggingface.co/splits", {"dataset": dataset})
    splits = [{"subset": row["config"], "split": row["split"]} for row in data.get("splits", [])]
    if not splits:
        raise HTTPException(400, "No dataset splits are available yet. Try another dataset.")
    subsets = list(dict.fromkeys(row["subset"] for row in splits))
    subset = subset or ("main" if "main" in subsets else subsets[0])
    available_splits = [row["split"] for row in splits if row["subset"] == subset]
    split = split or ("test" if "test" in available_splits else next(iter(available_splits), ""))
    if split not in available_splits:
        raise HTTPException(400, "The selected dataset configuration or split does not exist.")
    preview = await _get_json(
        "https://datasets-server.huggingface.co/first-rows",
        {
            "dataset": dataset,
            "config": subset,
            "split": split,
        },
    )
    columns = [
        feature["name"]
        for feature in preview.get("features", [])
        if isinstance(feature.get("type"), dict) and feature["type"].get("dtype") in {"string", "large_string"}
    ]
    if not columns:
        raise HTTPException(400, "This dataset has no text columns. Select a dataset with a plain-text prompt column.")
    # Reuse first-rows, which is already needed for column discovery. Include
    # structured reference answers as text, but never render dataset HTML/media.
    reference_names = {"answer", "answers", "response", "completion", "output", "target", "solution", "label"}
    preview_columns = [
        feature["name"]
        for feature in preview.get("features", [])
        if feature["name"] in columns or feature["name"].lower() in reference_names
    ]
    preview_rows = []
    for index, item in enumerate(preview.get("rows", [])[:5]):
        cells = {}
        truncated = set(item.get("truncated_cells", []))
        for column in preview_columns:
            value = item.get("row", {}).get(column)
            value = value if value is None or isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if value is not None and len(value) > 2000:
                value = value[:2000]
                truncated.add(column)
            cells[column] = value
        preview_rows.append(
            {
                "row_index": item.get("row_idx", index),
                "cells": cells,
                "truncated_columns": [column for column in preview_columns if column in truncated],
            }
        )
    return {
        "dataset": dataset,
        "subset": subset,
        "split": split,
        "splits": splits,
        "text_columns": columns,
        "preview_columns": preview_columns,
        "preview_rows": preview_rows,
    }
