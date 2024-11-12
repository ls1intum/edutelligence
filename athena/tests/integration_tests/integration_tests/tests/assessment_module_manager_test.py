import requests
from integration_tests.runners.run_assessment_module_manager import run_assessment_module_manager
from integration_tests.runners.run_module_programming_llm import run_module_programming_llm
from integration_tests.runners.run_module_text_llm import run_module_text_llm
from integration_tests.runners.run_module_modeling_llm import run_module_modeling_llm


def test_health_endpoint(run_assessment_module_manager, run_module_programming_llm, run_module_text_llm, run_module_modeling_llm):
    response = requests.get("http://localhost:5100/health")

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    response_data = response.json()

    assert response_data.get("status") == "ok", "Unexpected status in response body"

    expected_modules = {
        "module_programming_llm": {
            "url": "http://localhost:5002",
            "type": "programming",
            "healthy": True,
            "supportsEvaluation": False,
            "supportsNonGradedFeedbackRequests": True,
            "supportsGradedFeedbackRequests": True
        },
        "module_text_llm": {
            "url": "http://localhost:5003",
            "type": "text",
            "healthy": True,
            "supportsEvaluation": True,
            "supportsNonGradedFeedbackRequests": False,
            "supportsGradedFeedbackRequests": True
        },
        "module_modeling_llm": {
            "url": "http://localhost:5008",
            "type": "modeling",
            "healthy": True,
            "supportsEvaluation": False,
            "supportsNonGradedFeedbackRequests": True,
            "supportsGradedFeedbackRequests": True
        }
    }

    modules = response_data.get("modules", {})
    for module_name, expected_data in expected_modules.items():
        assert module_name in modules, f"Module '{module_name}' is missing in response"
        module_data = modules[module_name]

        for key, expected_value in expected_data.items():
            actual_value = module_data.get(key)
            assert actual_value == expected_value, f"Module '{module_name}' has incorrect '{key}': expected {expected_value}, got {actual_value}"
