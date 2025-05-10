import unittest
import requests

VALID_LOGOS_KEY = "lg-root-ZD3WgLOTMp21qrzJ2ahHT22TCWvaPHVItute4bPKvCaOfnNO49zRIfEseBPT1rhV2icpRRWSVfIaxZIDPXuyE5D7f4bMlMiMVlw8GncPcaBryCwm6rAgQYHQABphdtde"


class TestOpenAIForwardingProxy(unittest.TestCase):
    def test_setup(self):
        """
        provider_name: str
    base_url: str
    api_key: str
    auth_name: str
    auth_format: str
        """
        headers = {
            "Content-Type": "application/json",
            "logos_key": f"{VALID_LOGOS_KEY}"
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5,
        }

        response = requests.post("http://localhost:8000/v1/chat/completions", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200


if __name__ == '__main__':
    unittest.main()
