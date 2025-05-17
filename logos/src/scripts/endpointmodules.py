"""
File containing methods calling logos endpoints.
"""
import requests
from requests import Response
import configparser


def endpoint_setup() -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/setup", json=dict(), headers=headers)


def endpoint_add_provider(logos_key: str, base_url: str, api_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "logos_key": f"{logos_key}",
        "provider_name": "azure",
        "base_url": f"{base_url}",
        "api_key": f"{api_key}",
        "auth_name": "api-key",
        "auth_format": "{}"
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_provider", json=data, headers=headers)


def endpoint_add_model(logos_key: str, endpoint: str) -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "logos_key": f"{logos_key}",
        "name": "GPT 4 Omni",
        "endpoint": f"{endpoint}",
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_model", json=data, headers=headers)


def endpoint_add_profile(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "logos_key": f"{logos_key}",
        "profile_name": "root",
        "process_id": 1,
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_profile", json=data, headers=headers)


def endpoint_connect_process_provider(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
        "temperature": 0.5,
        "logos_key": f"{logos_key}",
        "profile_id": 1,
        "api_id": 1,
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_process_provider", json=data,
                         headers=headers)


def endpoint_connect_process_model(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "logos_key": f"{logos_key}",
        "profile_id": 1,
        "model_id": 1,
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_process_model", json=data,
                         headers=headers)


def endpoint_connect_model_provider(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "logos_key": f"{logos_key}",
        "provider_id": 1,
        "model_id": 1,
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_model_provider", json=data,
                         headers=headers)


def endpoint_connect_model_api(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "logos_key": f"{logos_key}",
        "api_id": 1,
        "model_id": 1,
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_model_api", json=data,
                         headers=headers)


def endpoint_forward_prompt(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }

    data = {
        "messages": [{"role": "user", "content": "Tell me a fun fact about the visigoths!"}],
        "temperature": 0.5
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/v1/chat/completions", json=data, headers=headers)


def endpoint_add_service(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }

    data = {
        "logos_key": f"{logos_key}",
        "name": "service_proxy"
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_service", json=data, headers=headers)


def endpoint_add_service_profile(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }

    data = {
        "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
        "temperature": 0.5,
        "logos_key": f"{logos_key}",
        "profile_name": "service_profile",
        "process_id": 2,
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_profile", json=data, headers=headers)


def endpoint_add_service_provider(logos_key: str, base_url: str) -> Response:
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }

    data = {
        "logos_key": f"{logos_key}",
        "provider_name": "azure",
        "base_url": f"{base_url}",
        "api_key": "",
        "auth_name": "api-key",
        "auth_format": "{}"
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_provider", json=data, headers=headers)


def endpoint_add_service_connect(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }

    data = {
        "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
        "temperature": 0.5,
        "logos_key": f"{logos_key}",
        "api_id": 2,
        "profile_id": 2,
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_process_provider", json=data,
                         headers=headers)


def endpoint_proxy(logos_key: str, api_key: str, deployment_name: str, api_version: str) -> Response:
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
        "api_key": f"{api_key}",
        "deployment_name": f"{deployment_name}",
        "api_version": f"{api_version}",
    }

    data = {
        "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
        "temperature": 0.5
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/v1/chat/completions", json=data, headers=headers)


def endpoint_export(logos_key: str) -> Response:
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }

    data = {
        "logos_key": f"{logos_key}",
    }

    return requests.post("http://logos.ase.cit.tum.de:8080/logosdb/export", json=data, headers=headers)


def load_config():
    config = dict()
    configParser = configparser.RawConfigParser()
    configFilePath = "./logos/logos.conf"
    configParser.read(configFilePath)
    config["INIT_PROVIDER_BASE_URL"] = config.get('proxy_setup', 'INIT_PROVIDER_BASE_URL')
    config["INIT_PROVIDER_NAME"] = config.get('proxy_setup', 'INIT_PROVIDER_NAME')
    return config
