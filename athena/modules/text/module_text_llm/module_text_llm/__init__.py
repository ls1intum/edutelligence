import dotenv
from athena.approach_discovery.strategy_factory import SuggestionStrategyFactory

dotenv.load_dotenv(override=True)

def get_strategy_factory(base_class):
    return SuggestionStrategyFactory("module_text_llm", base_class)
