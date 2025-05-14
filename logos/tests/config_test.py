"""
Simple config test for a single root user
1. Run test_setup() single
2. Set VALID_LOGOS_KEY to the key provided in the previous response
3. Set API-Endpoints and Provider BaseURLs
4. Run all tests. The last test should print out a response from a registered LLM
"""

import unittest
import requests

global VALID_LOGOS_KEY
VALID_LOGOS_KEY = ""
VALID_SERVICE_KEY = ""

BASE_URL = ""
API_KEY = ""
MODEL_ENDPOINT = ""
DEPLOYMENT_NAME = ""
API_VERSION = ""


class TestOpenAIForwardingProxy(unittest.TestCase):
    def test_setup(self):
        headers = {
            "Content-Type": "application/json",
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/setup", json=dict(), headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200
        global VALID_LOGOS_KEY
        VALID_LOGOS_KEY = response.json().get("api_key")

    def test_add_provider(self):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "provider_name": "azure",
            "base_url": f"{BASE_URL}",
            "api_key": f"{API_KEY}",
            "auth_name": "api-key",
            "auth_format": "{}"
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_provider", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_add_model(self):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "name": "GPT 4 Omni",
            "endpoint": f"{MODEL_ENDPOINT}",
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_model", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_add_profile(self):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "profile_name": "root",
            "process_id": 1,
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_profile", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_connect_process_provider(self):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "profile_id": 1,
            "api_id": 1,
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_process_provider", json=data,
                                 headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_connect_process_model(self):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "profile_id": 1,
            "model_id": 1,
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_process_model", json=data,
                                 headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_connect_model_provider(self):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "provider_id": 1,
            "model_id": 1,
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_model_provider", json=data,
                                 headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_connect_model_api(self):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "api_id": 1,
            "model_id": 1,
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_model_api", json=data,
                                 headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_forward_prompt(self):
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_LOGOS_KEY}",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the caledonian tribe in britain!"}],
            "temperature": 0.5
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/v1/chat/completions", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_add_service(self):
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_LOGOS_KEY}",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "name": "service_proxy"
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_service", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_add_service_profile(self):
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_LOGOS_KEY}",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "profile_name": "service_profile",
            "process_id": 2,
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_profile", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_add_service_provider(self):
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_LOGOS_KEY}",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "provider_name": "azure",
            "base_url": f"{BASE_URL}",
            "api_key": "",
            "auth_name": "api-key",
            "auth_format": "{}"
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/add_provider", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_add_service_connect(self):
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_LOGOS_KEY}",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
            "temperature": 0.5,
            "logos_key": f"{VALID_LOGOS_KEY}",
            "api_id": 2,
            "profile_id": 2,
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/connect_process_provider", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_proxy(self):
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_SERVICE_KEY}",
            "api_key": f"{API_KEY}",
            "deployment_name": f"{DEPLOYMENT_NAME}",
            "api_version": f"{API_VERSION}",
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the western roman empire!"}],
            "temperature": 0.5
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/v1/chat/completions", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200

    def test_export(self):
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_LOGOS_KEY}",
        }

        data = {
            "logos_key": f"{VALID_LOGOS_KEY}",
        }

        response = requests.post("http://logos.ase.cit.tum.de:8080/logosdb/export", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200


if __name__ == '__main__':
    unittest.main()
