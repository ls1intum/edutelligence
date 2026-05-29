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


def _litellm_candidate(model_name: str, cloud_provider_type: str | None) -> str:
    if not cloud_provider_type or cloud_provider_type == "openai":
        return model_name
    return f"{cloud_provider_type}/{model_name}"


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


async def _store_prices_for_pair(
    client: httpx.AsyncClient,
    model_id: int,
    model_name: str,
    provider_id: int,
    cloud_provider_type: str | None,
) -> None:
    candidate = _litellm_candidate(model_name, cloud_provider_type)
    data = await _fetch_model_data(client, candidate)
    if data is None and candidate != model_name:
        data = await _fetch_model_data(client, model_name)
    if data is None:
        logging.info(
            "price_updater: '%s' (provider_id=%s) not found in litellm catalog, will be free",
            model_name,
            provider_id,
        )
        return
    valid_from = datetime.datetime.now(datetime.timezone.utc)
    with DBManager() as db:
        for field, token_type in LITELLM_TO_TOKEN_TYPE.items():
            cost = data.get(field)
            if not cost:
                continue
            price_per_k = round(cost * 1e11)
            db.upsert_model_token_price(model_id, token_type, price_per_k, valid_from, provider_id=provider_id)
    logging.info(
        "price_updater: prices updated for '%s' (id=%s, provider_id=%s)",
        model_name,
        model_id,
        provider_id,
    )


async def fetch_and_store_prices() -> None:
    global _catalog_cache

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            _catalog_cache = await _fetch_full_catalog(client)
            logging.info("price_updater: catalog refreshed (%d models)", len(_catalog_cache))
        except Exception as exc:
            logging.error("price_updater: catalog fetch failed: %s", exc)

        with DBManager() as db:
            pairs = db.get_all_model_provider_pairs()

        for pair in pairs:
            await _store_prices_for_pair(
                client,
                model_id=pair["model_id"],
                model_name=pair["model_name"],
                provider_id=pair["provider_id"],
                cloud_provider_type=pair["cloud_provider_type"],
            )


async def fetch_price_for_single_model(model_id: int, model_name: str) -> None:
    with DBManager() as db:
        providers = db.get_cloud_providers_for_model(model_id)
    if not providers:
        logging.info("price_updater: no cloud providers for '%s' (id=%s), skipping", model_name, model_id)
        return
    async with httpx.AsyncClient(timeout=30) as client:
        for p in providers:
            await _store_prices_for_pair(
                client,
                model_id=model_id,
                model_name=model_name,
                provider_id=p["provider_id"],
                cloud_provider_type=p["cloud_provider_type"],
            )


async def run_price_updater() -> None:
    while True:
        try:
            await fetch_and_store_prices()
        except Exception as exc:
            logging.error("price_updater: unhandled error: %s", exc)
        await asyncio.sleep(UPDATE_INTERVAL_S)
