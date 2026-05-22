import asyncio
import datetime
import logging

import httpx

from logos.dbutils.dbmanager import DBManager

LITELLM_API_BASE = "https://api.litellm.ai/model_catalog"
UPDATE_INTERVAL_S = 86_400
CATALOG_PAGE_SIZE = 50

LITELLM_TO_TOKEN_TYPE: dict[str, str] = {
    "input_cost_per_token": "prompt_tokens",
    "output_cost_per_token": "completion_tokens",
    "cache_read_input_token_cost": "prompt_cached_tokens",
    "output_cost_per_reasoning_token": "completion_reasoning_tokens",
    "input_cost_per_audio_token": "prompt_audio_tokens",
    "output_cost_per_audio_token": "completion_audio_tokens",
}

_catalog_cache: list[dict] = []


async def _fetch_full_catalog(client: httpx.AsyncClient) -> list[dict]:
    all_models = []
    page = 1
    while True:
        resp = await client.get(
            LITELLM_API_BASE,
            params={"page": page, "page_size": CATALOG_PAGE_SIZE},
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        all_models.extend(data)
        if len(data) < CATALOG_PAGE_SIZE:
            break
        page += 1
    return all_models


def get_cached_catalog() -> list[dict]:
    return _catalog_cache


async def _fetch_model_data(client: httpx.AsyncClient, model_name: str) -> dict | None:
    for candidate in {model_name, model_name.lower()}:
        try:
            resp = await client.get(f"{LITELLM_API_BASE}/{candidate}")
        except Exception as exc:
            logging.warning("price_updater: HTTP error for %s: %s", candidate, exc)
            return None
        if resp.status_code == 200:
            return resp.json()
    return None


async def fetch_and_store_prices() -> None:
    global _catalog_cache

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            _catalog_cache = await _fetch_full_catalog(client)
            logging.info("price_updater: catalog refreshed (%d models)", len(_catalog_cache))
        except Exception as exc:
            logging.error("price_updater: catalog fetch failed: %s", exc)

        with DBManager() as db:
            models = db.get_all_models_basic()

        for model in models:
            model_name = model["name"]
            model_id = model["id"]

            data = await _fetch_model_data(client, model_name)

            if data is None:
                logging.info(
                    "price_updater: '%s' not found in litellm catalog, will be free", model_name
                )
                continue

            valid_from = datetime.datetime.now(datetime.timezone.utc)
            with DBManager() as db:
                for field, token_type in LITELLM_TO_TOKEN_TYPE.items():
                    cost = data.get(field)
                    if not cost:
                        continue
                    price_per_k = round(cost * 1e11)
                    db.upsert_model_token_price(model_id, token_type, price_per_k, valid_from)

            logging.info("price_updater: prices updated for '%s' (id=%s)", model_name, model_id)


async def fetch_price_for_single_model(model_id: int, model_name: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        data = await _fetch_model_data(client, model_name)
        if data is None:
            logging.info("price_updater: '%s' (id=%s) not in litellm, stays free", model_name, model_id)
            return
        valid_from = datetime.datetime.now(datetime.timezone.utc)
        with DBManager() as db:
            for field, token_type in LITELLM_TO_TOKEN_TYPE.items():
                cost = data.get(field)
                if not cost:
                    continue
                price_per_k = round(cost * 1e11)
                db.upsert_model_token_price(model_id, token_type, price_per_k, valid_from)
        logging.info("price_updater: prices updated for '%s' (id=%s)", model_name, model_id)


async def run_price_updater() -> None:
    while True:
        try:
            await fetch_and_store_prices()
        except Exception as exc:
            logging.error("price_updater: unhandled error: %s", exc)
        await asyncio.sleep(UPDATE_INTERVAL_S)