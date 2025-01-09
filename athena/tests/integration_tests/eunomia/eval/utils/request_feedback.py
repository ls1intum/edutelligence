import requests
from requests.exceptions import HTTPError
from typing import List, Tuple
from pydantic import ValidationError

from eval.models.schemas.external.api_response import LLMUsage, APIResponse
from eval.models.schemas.external.feedback import ModelingFeedback

def request_feedback(server_url: str, payload: dict) -> Tuple[List[ModelingFeedback], LLMUsage]:
    """
    Sends a submission payload to the given server_url endpoint and returns a tuple containing:
    - A list of ModelingFeedback objects as parsed from the server response.
    - An LLMUsage object representing the LLM usage metadata.

    Args:
        server_url (str): The URL of the athena server endpoint
        payload (dict): The JSON-serializable dictionary payload containing submission data.

    Returns:
        (List[ModelingFeedback], LLMUsage): A tuple of (feedback list, llm usage) instances.
    """
    headers = {
        "X-Server-URL": "http://localhost:8080",
        "Authorization": "abcdef12345"
    }

    # Send POST request to server
    response = requests.post(server_url, json=payload, headers=headers)
    try:
        response.raise_for_status()
    except HTTPError as http_err:
        raise HTTPError(f"Server returned HTTP error: {http_err}") from http_err

    # Parse JSON content
    try:
        response_content = response.json()

    except ValueError as json_err:
        raise ValueError("Failed to decode JSON response from the server.") from json_err

    # Parse the response into APIResponse
    try:
        api_response = APIResponse(**response_content)
    except ValidationError as val_err:
        raise ValidationError(f"Response did not match APIResponse schema: {val_err}") from val_err

    # Extract the data (list of ModelingFeedback) and meta (LLMUsage)
    feedback_list = api_response.data
    llm_usage = api_response.meta

    return feedback_list, llm_usage