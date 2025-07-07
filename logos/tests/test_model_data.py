import time
from json import JSONDecodeError

import matplotlib.pyplot as plt

import requests
from requests import Response

from logos.classification.classification_balancer import Balancer
from logos.classification.model_handler import ModelHandler

models = [
    {"id": 0,
     "name": "azure-gpt-4-omni",
     "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview",
     "api_id": 0,
     "weight_privacy": "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
     "tags": "#math;#chat",
     "parallel": 256,
     "description": "reasoning, advanced maths, coding",
     "classification_weight": Balancer(),
     },
    {"id": 1,
     "name": "o3-mini",
     "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/o3-mini/chat/completions?api-version=2024-12-01-preview",
     "api_id": 1,
     "weight_privacy": "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
     "tags": "#chat;#coding",
     "parallel": 256,
     "description": "chat, question answering, writing, coding",
     "classification_weight": Balancer(),
     },

    {"id": 2,
     "name": "deepseek-r1:70b",
     "endpoint": "https://gpu.aet.cit.tum.de/api/chat/completions",
     "api_id": 1,
     "weight_privacy": "LOCAL",
     "tags": "#coding #math-problems #multi-step-reasoning #computational-efficiency #high-capacity",
     "parallel": 256,
     "description": "Good at coding, math problems, and multi-step reasoning tasks with high computational efficiency",
     "classification_weight": Balancer(),
     },
    {"id": 3,
     "name": "gemma3:27b",
     "endpoint": "https://gpu.aet.cit.tum.de/api/chat/completions",
     "api_id": 1,
     "weight_privacy": "LOCAL",
     "tags": "#conversational-AI #natural-language-understanding #explanation-generation #general-purpose #chatbot",
     "parallel": 256,
     "description": "Strong in conversational AI, natural language understanding, and generating detailed explanations",
     "classification_weight": Balancer(),
     },
    {"id": 4,
     "name": "llama3.3:latest",
     "endpoint": "https://gpu.aet.cit.tum.de/api/chat/completions",
     "api_id": 1,
     "weight_privacy": "LOCAL",
     "tags": "#general-purpose #coding #writing #reasoning",
     "parallel": 256,
     "description": "Versatile for a wide range of tasks including coding, writing, and multi-step reasoning with open-source flexibility",
     "classification_weight": Balancer(),
     },
    {"id": 5,
     "name": "qwen3:30b-a3b",
     "endpoint": "https://gpu.aet.cit.tum.de/api/chat/completions",
     "api_id": 1,
     "weight_privacy": "LOCAL",
     "tags": "#problem-solving #coding #complex-reasoning #fine-tuned #specialized-tasks",
     "parallel": 256,
     "description": "Specialized in advanced problem-solving, coding, and complex reasoning tasks through fine-tuning.",
     "classification_weight": Balancer(),
     },
    {"id": 6,
     "name": "tinyllama:latest",
     "endpoint": "https://gpu.aet.cit.tum.de/api/chat/completions",
     "api_id": 1,
     "weight_privacy": "LOCAL",
     "tags": "#lightweight #basic-NLP #simple-coding #low-latency #efficient",
     "parallel": 256,
     "description": "Efficient for lightweight applications, handling basic NLP tasks and simple coding challenges quickly.",
     "classification_weight": Balancer(),
     },
    {"id": 7,
     "name": "gemma3:4b",
     "endpoint": "https://gpu.aet.cit.tum.de/api/chat/completions",
     "api_id": 1,
     "weight_privacy": "LOCAL",
     "tags": "#lightweight #chat #fast-response #basic-language-tasks #simple-applications",
     "parallel": 256,
     "description": "Lightweight model optimized for speed and simplicity in chat and straightforward language tasks.",
     "classification_weight": Balancer(),
     },
    {"id": 8,
     "name": "qwen3:32b",
     "endpoint": "https://gpu.aet.cit.tum.de/api/chat/completions",
     "api_id": 1,
     "weight_privacy": "LOCAL",
     "tags": "#problem-solving #coding #math-problems #high-capacity #general-purpose",
     "parallel": 256,
     "description": "Capable of handling a variety of tasks including problem-solving, coding, and math with high accuracy.",
     "classification_weight": Balancer(),
     },
]


def prepare_model_data():
    s = time.time()
    cost = ModelHandler(list())
    cost.add_model(None, 0)
    cost.add_model(None, 1)
    cost.add_model(1, 2)
    cost.add_model(1, 3)
    cost.add_model(1, 4)
    cost.add_model(1, 5)
    cost.add_model(1, 6)
    cost.add_model(1, 7)
    cost.add_model(1, 8)

    accuracy = ModelHandler(list())
    accuracy.add_model(None, 0)
    accuracy.add_model(None, 4)
    accuracy.add_model(None, 5)
    accuracy.add_model(None, 2)
    accuracy.add_model(None, 8)
    accuracy.add_model(None, 3)
    accuracy.add_model(None, 1)
    accuracy.add_model(None, 6)
    accuracy.add_model(None, 7)

    quality = ModelHandler(list())
    quality.add_model(None, 0)
    quality.add_model(None, 4)
    quality.add_model(None, 5)
    quality.add_model(None, 2)
    quality.add_model(None, 8)
    quality.add_model(None, 3)
    quality.add_model(None, 1)
    quality.add_model(None, 6)
    quality.add_model(None, 7)

    latency = ModelHandler(list())
    latency.add_model(None, 7)
    latency.add_model(None, 6)
    latency.add_model(None, 1)
    latency.add_model(None, 3)
    latency.add_model(None, 0)
    latency.add_model(None, 8)
    latency.add_model(None, 4)
    latency.add_model(None, 2)
    latency.add_model(None, 5)

    for v, i in cost.get_models():
        models[i]["weight_cost"] = v
    for v, i in accuracy.get_models():
        models[i]["weight_accuracy"] = v
    for v, i in quality.get_models():
        models[i]["weight_quality"] = v
    for v, i in latency.get_models():
        models[i]["weight_latency"] = v
    print("Model Handler Started: {:.2f}ms".format((time.time() - s) * 1000))
    return models


def test_send_to_azure(m, p, k):
    proxy_headers = {
        "Content-Type": "application/json",
        "api-key": f"{k}",
    }
    data = {
        "messages": [{"role": "user", "content": p}],
    }
    r: Response = requests.post(m["endpoint"], json=data, headers=proxy_headers)
    try:
        r: dict = r.json()
    except JSONDecodeError:
        r: dict = {"error": r.text}
    return r


def test_send_to_webui(m, p, k):
    url = 'https://gpu.aet.cit.tum.de/api/chat/completions'
    headers = {
        'Authorization': f'Bearer {k}',
        'Content-Type': 'application/json'
    }
    data = {
        "model": m["name"],
        "messages": [
            {
                "role": "user",
                "content": p
            }
        ]
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()


def get_from_id(m, i):
    for model in m:
        if model["id"] == i:
            return model
    return None


def create_html(responses, prompt):
    html_template = """
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>LLM-Comparison</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
                display: flex;
                flex-wrap: wrap;
            }
            
            .model-container {
                flex: 1;
                min-width: 300px;
                padding: 20px;
                border: 1px solid #ccc;
                margin: 10px;
                background-color: #f9f9f9;
            }
            
            .model-name {
                font-weight: bold;
                margin-bottom: 10px;
            }
            
            .response {
                white-space: pre-wrap;
                word-wrap: break-word;
                margin-bottom: 15px;
            }
            
            .metrics {
                background-color: #e8f4ff;
                padding: 10px;
                border-radius: 5px;
            }
        
            .chart-container {
                margin-top: 50px;
                text-align: center;
            }
        </style>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    </head>
    <body>
    {prompt_container}
    {model_containers}
    <div class="chart-container">
        <h2>LLM Weights</h2>
        <img src="model_weights.png" alt="Model Weights" style="max-width: 100%">
    </div>
    
    <script>
    document.addEventListener("DOMContentLoaded", function() {
        document.querySelectorAll('.response').forEach(element => {
            const markdownText = element.textContent;
            const htmlContent = marked.parse(markdownText);
            element.innerHTML = htmlContent;
        });
    });
    </script>
    </body>
    </html>
    """

    model_names = []
    total_weights = []

    model_containers = ""
    for model, (response, weight, time_latency, balancer) in responses.items():
        latency, accuracy, quality = balancer.weights["policy"]
        token = balancer.weights["token"][0]
        ai = balancer.weights["ai"][0]
        container = f"""
        <div class="model-container">
            <div class="model-name">{model}:</div>
            <div class="metrics">Duration: {time_latency}s</div>
            <div class="metrics">Latency: {latency}</div>
            <div class="metrics">Accuracy: {accuracy}</div>
            <div class="metrics">Quality: {quality}</div>
            <div class="metrics">Token: {token}</div>
            <div class="metrics">Laura: {ai}</div>
            <div class="metrics"><b>Weight: {weight}</b></div>
            <div class="response">{response}</div>
        </div>
        """
        model_names.append(model)
        total_weights.append(weight)
        model_containers += container

    prompt_container = f"""
        <div class="prompt-container" style="width: 100%">
            Prompt: {prompt}
        </div>
    """

    plt.figure(figsize=(10, 5))
    plt.bar(model_names, total_weights)
    plt.xlabel('Models')
    plt.ylabel('Weights')
    plt.title('Distribution of Model Weights')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig('model_weights.png', dpi=300)
    plt.close()

    final_html = html_template.replace("{prompt_container}", prompt_container).replace("{model_containers}", model_containers)

    with open("comparison.html", "w", encoding="utf-8") as file:
        file.write(final_html)

    print("HTML successfully exported")
