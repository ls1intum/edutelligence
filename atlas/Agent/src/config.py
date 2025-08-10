import os
from dotenv import load_dotenv

# Load from .env file
load_dotenv()

class AgentConfig:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
    AZURE_API_VERSION = os.getenv("AZURE_API_VERSION")
    
    # Atlas API configuration
    ATLAS_API_URL = os.getenv("ATLAS_API_URL", "http://localhost:8001")
    ATLAS_API_TOKEN = os.getenv("ATLAS_API_TOKEN")
    
    # Artemis API configuration  
    ARTEMIS_API_URL = os.getenv("ARTEMIS_API_URL", "http://localhost:8080")
    ARTEMIS_API_TOKEN = os.getenv("ARTEMIS_API_TOKEN")
