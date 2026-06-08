from enum import Enum


class AiSelectionDecision(str, Enum):
    CLOUD_AI = "CLOUD_AI"
    LOCAL_AI = "LOCAL_AI"
    NO_AI = "NO_AI"
