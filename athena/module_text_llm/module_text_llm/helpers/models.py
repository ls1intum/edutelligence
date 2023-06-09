import os 
from langchain.chat_models import AzureChatOpenAI, ChatOpenAI
import openai
 
OPENAI_API_TYPE = os.environ.get("OPENAI_API_TYPE")

# Validate environment variables
if "OPENAI_API_KEY" not in os.environ:
    raise EnvironmentError("OPENAI_API_KEY environment variable not set.")
if OPENAI_API_TYPE == "azure":
    if "OPENAI_API_BASE" not in os.environ:
        raise EnvironmentError("OPENAI_API_TYPE=azure but OPENAI_API_BASE environment variable not set.")
    if "OPENAI_API_VERSION" not in os.environ:
        raise EnvironmentError("OPENAI_API_TYPE=azure but OPENAI_API_VERSION environment variable not set.")
    if "AZURE_DEPLOYMENT_NAME" not in os.environ:
        raise EnvironmentError("OPENAI_API_TYPE=azure but AZURE_DEPLOYMENT_NAME environment variable not set.")
    
    AZURE_DEPLOYMENT_NAME = os.environ["AZURE_DEPLOYMENT_NAME"]
 
    # Check if deployment exists
    openai.api_type = "azure"
    openai.api_key = os.environ["OPENAI_API_KEY"]
    openai.api_base = os.environ["OPENAI_API_BASE"]
    openai.api_version = os.environ["OPENAI_API_VERSION"]
     
    deployments = openai.Deployment.list().data # type: ignore
    deployment_ids = [deployment.id for deployment in deployments]
    if AZURE_DEPLOYMENT_NAME not in deployment_ids:
        deployments = [{ "id": deployment.id, "model": deployment.model } for deployment in deployments]
        raise EnvironmentError(f"Deployment id '{AZURE_DEPLOYMENT_NAME}' not found, available deployments: {deployments}")

    # Initialize azure chat model
    chat = AzureChatOpenAI(deployment_name=AZURE_DEPLOYMENT_NAME, client="", temperature=0)
else:
    # Initialize openai chat model
    chat = ChatOpenAI(client="", temperature=0)
