import dotenv
from athena.approach_discovery.strategy_factory import SuggestionStrategyFactory
from module_text_llm.approach_config import ApproachConfig

dotenv.load_dotenv(override=True)
strategyFactory = SuggestionStrategyFactory("module_text_llm", ApproachConfig)
