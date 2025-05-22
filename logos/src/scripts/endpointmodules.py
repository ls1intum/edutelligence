"""
File containing methods calling logos endpoints.
"""
from requests import Response

from logos.dbmanager import DBManager


def endpoint_add_provider(logos_key: str, base_url: str, provider_name: str, api_key: str) -> Response:
    data = {
        "logos_key": f"{logos_key}",
        "provider_name": f"{provider_name}",
        "base_url": f"{base_url}",
        "api_key": f"{api_key}",
        "auth_name": "api-key",
        "auth_format": "{}"
    }
    with DBManager() as man:
        return man.add_provider(**data)


def endpoint_add_profile(logos_key: str, profile_name: str, process_id: int) -> Response:
    data = {
        "logos_key": f"{logos_key}",
        "profile_name": profile_name,
        "process_id": process_id,
    }
    with DBManager() as man:
        return man.add_profile(**data)


def endpoint_connect_process_provider(logos_key: str, profile_id: int, api_id: int) -> Response:
    data = {
        "logos_key": f"{logos_key}",
        "profile_id": profile_id,
        "api_id": api_id,
    }

    with DBManager() as man:
        return man.connect_process_provider(**data)
