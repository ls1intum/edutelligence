import os

from ollama import Client

ollama_client: Client = Client(
    os.environ.get("OLLAMA_HOST"),
    auth=(os.environ.get("OLLAMA_USERNAME"), os.environ.get("OLLAMA_PASSWORD")),
)


def ensure_model_present(model: str) -> None:
    models = [model.model for model in ollama_client.list()["models"]]
    if model not in models:
        print(f"Model {model} not found. Pulling...")
        ollama_client.pull(model)
    else:
        print(f"Model {model} is already present.")


def is_loaded(model: str) -> bool:
    models = [model.model for model in ollama_client.ps()["models"]]
    return model in models


def load_model(model: str, duration: str = "5m") -> None:
    print(f"Loading model {model} for {duration}...")
    ollama_client.chat(model, messages=[], keep_alive=duration)
    print(f"Model {model} loaded.")


def unload_model(model: str) -> None:
    print(f"Unloading model {model}...")
    ollama_client.chat(model, messages=[], keep_alive=0)
    print(f"Model {model} unloaded.")
