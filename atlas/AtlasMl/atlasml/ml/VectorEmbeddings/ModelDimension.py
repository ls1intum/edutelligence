from enum import Enum

class ModelDimension(Enum):
    text_embedding_three_small = 1536
    text_embedding_three_large = 3072
    # Add more models that are to be used and their vector dimensions