import unittest
import requests


class TestOpenAIForwardingInvalid(unittest.TestCase):
    def test(self):
        headers = {
            "Content-Type": "application/json"
        }

        data = {
            "model": "gpt-3.5-turbo",
            "prompt": "Say this is a test",
            "user": "",
            "password": ""
        }

        response = requests.post("http://localhost:8000/v1/chat/completions", json=data, headers=headers)
        assert response.status_code == 200
        assert "error" in str(response.text)
        assert "openai" in str(response.text)
        print(response.json())


if __name__ == '__main__':
    unittest.main()
