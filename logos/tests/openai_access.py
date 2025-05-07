import unittest
import requests

VALID_LOGOS_KEY = "lg-brik-KO1l_KFpavHs2GYg3Zs--AleSN_mOThIFz4SrM6yaraYAkAT7OXen2pmCtT5FwwTNjnM_OcKkmc1cmycS62aEG6n7MVxDHl1L24vEFw47-d8GDAq_KXQCoif-xDrNQNk"


class TestOpenAIForwardingProxy(unittest.TestCase):
    def test_logos_proxy_openai(self):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {VALID_LOGOS_KEY}"
        }

        data = {
            "model": "gpt-3.5-turbo",
            "prompt": "Say this is a test",
        }

        response = requests.post("http://localhost:8000/v1/chat/completions", json=data, headers=headers)
        assert response.status_code == 200
        assert "error" in str(response.text)
        assert "openai" in str(response.text)

    def test_logos_proxy_azure(self):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {VALID_LOGOS_KEY}",
            "provider": "azure",
            "deployment_name": "gpt-4o",
            "api_version": "2024-08-01-preview"
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the roman empire!"}],
            "temperature": 0.5
        }

        response = requests.post("http://localhost:8000/v1/chat/completions", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200
        assert "completion_tokens" in str(response.text)

    def test_logos_invalid_key(self):
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer ..."
        }

        data = {
            "model": "gpt-3.5-turbo",
            "prompt": "Say this is a test",
        }

        response = requests.post("http://localhost:8000/v1/chat/completions", json=data, headers=headers)
        content = eval(response.text)
        assert response.status_code == 200
        assert int(content[1]) == 401
        assert {"error":"No corresponding profile found for provided key"} == content[0]


if __name__ == '__main__':
    unittest.main()
