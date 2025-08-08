import requests
import os

print(os.getcwd())

with open("logos/tests/key.txt", "r") as file:
    lines = file.readlines()
    VALID_LOGOS_KEY = lines[0].strip()
    VALID_GTP4O_KEY = lines[1]
    VALID_3OMNI_KEY = lines[2]
    VALID_WEBUI_KEY = lines[3]


def test_resource():
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{VALID_LOGOS_KEY}",
        "policy": "3"
    }

    data = {
        "messages": [{"role": "user", "content": "Tell me a riddle from the anglo-saxons!"}],
        "temperature": 0.5
    }

    response = requests.post("https://0.0.0.0:8080/v1/chat/completions", json=data, headers=headers, verify=False, stream=True)
    ll = 200
    cll = 0
    lines = list()
    for line in response.iter_lines():
        lines.append(line.decode())
        data = eval(
            line.decode().removeprefix("data: ").strip().replace("false", "False").replace("true", "True").replace(
                "null", "None"))
        if "choices" in data and data["choices"] and "delta" in data["choices"][0] and "content" in \
                data["choices"][0]["delta"]:
            content = data["choices"][0]["delta"]["content"]
            print(content, end="", flush=True)
            cll += len(content)
            if "\n" in content:
                cll = 0
        if cll >= ll:
            print(flush=True)
            cll = 0
    # for line in lines:
    #     pprint(line)
    assert response.status_code == 200


if __name__ == "__main__":
    test_resource()