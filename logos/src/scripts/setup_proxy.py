"""
Setup script to initialize Logos as proxy.
"""
from typing import Union

from scripts.endpointmodules import *


def setup(base_url: str, provider_name: str, provider_type: str) -> Union[tuple, dict]:
    with DBManager() as man:
        su = man.setup()
        if "error" in su:
            return su
        logos_key = su["api_key"]
        data = {
            "logos_key": f"{logos_key}",
            "provider_name": f"{provider_name}",
            "base_url": f"{base_url}",
            "api_key": f"",
            "auth_name": "api-key",
            "auth_format": "{}",
            "provider_type": f"{provider_type}",
        }
        print(man.add_provider(**data), flush=True)
        data = {
            "logos_key": f"{logos_key}",
            "profile_name": "root",
            "process_id": 1,
        }
        print(man.add_profile(**data), flush=True)
        data = {
            "logos_key": f"{logos_key}",
            "profile_id": 1,
            "provider_id": 1,
        }
        print(man.connect_process_provider(**data), flush=True)
    print("Logos-Root-Key: ", logos_key, flush=True)
    return logos_key


def add_service(logos_key: str, base_url: str, provider_name: str, provider_type: str):
    out = endpoint_add_service(logos_key, "service")[0]
    service_key = out["logos-key"]
    print("Logos-Service-Key: ", service_key)
    process_id = out["process-id"]
    profile_id = endpoint_add_profile(logos_key, "service", process_id)[0]["profile-id"]
    provider_id = endpoint_add_provider(
        logos_key,
        base_url=base_url,
        provider_name=provider_name,
        api_key="",
        provider_type=provider_type,
    )[0]["provider-id"]
    print(endpoint_connect_process_provider(logos_key, profile_id, provider_id))
    return service_key
