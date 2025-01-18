import dotenv
from athena.approach_discovery.strategy_factory import SuggestionStrategyFactory
from athena.logger import logger
from sentence_transformers import SentenceTransformer

dotenv.load_dotenv(override=True)

logger.info("Loading Sentence Transformer model ")
embedding_model = model = SentenceTransformer('all-MiniLM-L6-v2')
logger.info(" Embedder loaded!")

def get_strategy_factory(base_class):
    return SuggestionStrategyFactory("module_text_llm", base_class)
 