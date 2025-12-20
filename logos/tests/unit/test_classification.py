from logos.classification.classification_manager import ClassificationManager
from logos.classification.laura_embedding_classifier import LauraEmbeddingClassifier
from logos.classification.model_handler import ModelHandler

import time

def testing():
    models = [
        {"id": 0,
         "name": "azure-gpt-4-omni",
         "endpoint": "/gpt-4o/chat/completions?api-version=2024-08-01-preview",
         "api_id": 0,
         "weight_privacy": "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
         "tags": "#math;#coding",
         "parallel": 256,
         "description": "reasoning, advanced maths, coding",
         "classification_weight": 1,
         },
        {"id": 1,
         "name": "o3-mini",
         "endpoint": "/o3-mini/chat/completions?api-version=2024-12-01-preview",
         "api_id": 1,
         "weight_privacy": "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
         "tags": "#chat;#coding",
         "parallel": 256,
         "description": "chat, question answering, writing, coding",
         "classification_weight": 1,
         },
    ]

    s = time.time()
    cost = ModelHandler(list())
    cost.add_model(None, 0)
    cost.add_model(None, 1)

    accuracy = ModelHandler(list())
    accuracy.add_model(None, 0)
    accuracy.add_model(None, 1)

    quality = ModelHandler(list())
    quality.add_model(None, 0)
    quality.add_model(None, 1)

    latency = ModelHandler(list())
    latency.add_model(None, 0)
    latency.add_model(0, 1)
    # print("Model Handler Started: {:.2f}ms".format(time.time() - s) * 1000, flush=True)

    print("Cost", cost.get_models(), flush=True)
    print("Accuracy", accuracy.get_models(), flush=True)
    print("Quality", quality.get_models(), flush=True)
    print("Latency", latency.get_models(), flush=True)

    for v, i in cost.get_models():
        models[i]["weight_cost"] = v
    for v, i in accuracy.get_models():
        models[i]["weight_accuracy"] = v
    for v, i in quality.get_models():
        models[i]["weight_quality"] = v
    for v, i in latency.get_models():
        models[i]["weight_latency"] = v

    from pprint import pprint
    pprint(models)

    policy = {
        "id": 0,
        "name": "lax_all",
        "entity_id": 0,
        "description": "Somehow all LLMs that come into mind",
        "threshold_privacy": "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
        "threshold_latency": 4,
        "threshold_accuracy": 4,
        "threshold_cost": -4,
        "threshold_quality": 4,
        "priority": 255,
        "topic": "",
    }
    s = time.time()
    classifier = ClassificationManager(models)
    # print("Classification Manager started: {:.2f}ms".format(time.time() - s) * 1000)
    s = time.time()

    prompt = "Let's chat a bit about our life :)"
    results = classifier.classify(prompt, policy)
    # print("Classification finished in: {:.2f}ms".format(time.time() - s) * 1000)

    for result in results:
        print(f"Model {models[result[0]]['name']} got weight {result[1]}")


if __name__ == "__main__":
    testing()
