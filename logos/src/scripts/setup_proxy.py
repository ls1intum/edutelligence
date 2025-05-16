"""
Setup script to initialize Logos as proxy.
"""
from logos.src.scripts.endpointmodules import *


def setup():
    azure_base_url = ""
    response = endpoint_setup()
    logos_key = response.json()["api_key"]
    print("Logos-Root-Key: ", logos_key)
    _ = endpoint_add_provider(logos_key, base_url=azure_base_url, api_key="")
    _ = endpoint_add_profile(logos_key)
    _ = endpoint_connect_process_provider(logos_key)
