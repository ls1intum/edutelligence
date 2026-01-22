"""
File containing methods calling logos endpoints.
"""
from logos.dbutils.dbmanager import DBManager


def endpoint_add_provider(logos_key: str, base_url: str, provider_name: str, api_key: str):
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


def endpoint_add_profile(logos_key: str, profile_name: str, process_id: int):
    data = {
        "logos_key": f"{logos_key}",
        "profile_name": profile_name,
        "process_id": process_id,
    }
    with DBManager() as man:
        return man.add_profile(**data)


def endpoint_connect_process_provider(logos_key: str, profile_id: int, provider_id: int):
    data = {
        "logos_key": f"{logos_key}",
        "profile_id": profile_id,
        "provider_id": provider_id,
    }

    with DBManager() as man:
        return man.connect_process_provider(**data)


def endpoint_add_service(logos_key: str, name: str):
    data = {
        "logos_key": f"{logos_key}",
        "name": name,
    }

    with DBManager() as man:
        return man.add_service(**data)
