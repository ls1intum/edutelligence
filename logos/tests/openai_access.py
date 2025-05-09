import unittest
import requests

VALID_LOGOS_KEY = ""


class TestOpenAIForwardingProxy(unittest.TestCase):
    def test_setup(self):
        """
action == "add_process_connection":
            return db.add_process_connection(request.headers["logos_key"], request.headers["profile_name"],
                                             int(request.headers["process_id"]), int(request.headers["api_id"]))
        :return:
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {VALID_LOGOS_KEY}",
            "deployment_name": "gpt-4o",
            "api_version": "2024-08-01-preview"
        }

        data = {
            "messages": [{"role": "user", "content": "Tell me a fun fact about the ostrogothic empire!"}],
            "temperature": 0.5
        }

        response = requests.post("http://localhost:8000/v1/chat/completions", json=data, headers=headers)
        from pprint import pprint
        pprint(response.json())
        assert response.status_code == 200


if __name__ == '__main__':
    unittest.main()
