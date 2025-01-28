import dotenv
import os
from cryptography.fernet import Fernet
from athena.approach_discovery.strategy_factory import SuggestionStrategyFactory
import numpy as np

dotenv.load_dotenv(override=True)
def get_strategy_factory(base_class):
    return SuggestionStrategyFactory("module_text_llm", base_class)


def decrypt_keywords(filename="keywords_encrypted.txt"):
    encryption_key = os.getenv("ENCRYPTION_KEY") 
    if not encryption_key:
        return [""]
    
    cipher = Fernet(encryption_key)
    with open(filename, "rb") as f:
        encrypted_keywords = f.read()
    decrypted_keywords = cipher.decrypt(encrypted_keywords).decode()
    return decrypted_keywords.split(", ")

keywords = decrypt_keywords()

def load_embeddings_from_file(filename="keyword_embeddings.npy"):
    """
    Load embeddings from a .npy file.

    Parameters:
        filename (str): The filename from which embeddings will be loaded.

    Returns:
        np.ndarray: The loaded embeddings.
    """
    if os.path.exists(filename):
        embeddings = np.load(filename)
        print(f"Embeddings loaded from {filename}")
        return embeddings

    print(f"{filename} does not exist.")
    return None

keywords_embeddings = load_embeddings_from_file("keywords_embeddings.npy")
