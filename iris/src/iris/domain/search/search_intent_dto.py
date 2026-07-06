from enum import Enum


class SearchIntent(str, Enum):
    TRIGGER_AI = "trigger_ai"
    SKIP_AI = "skip_ai"
