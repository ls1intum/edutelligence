"""
Setup script to initialize Logos as proxy.
"""
from scripts.endpointmodules import *


def setup(base_url: str, provider_name: str) -> dict:
    with DBManager() as man:
        logos_key = man.setup()["api_key"]
    print("Logos-Root-Key: ", logos_key)
    print(endpoint_add_provider(logos_key, base_url=base_url, provider_name=provider_name, api_key=""))
    print(endpoint_add_profile(logos_key, "root", 1))
    print(endpoint_connect_process_provider(logos_key, 1, 1))
    return logos_key
