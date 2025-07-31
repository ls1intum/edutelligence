"""
Model initialization using LangChain's init_chat_model with OpenRouter support.

This module provides a unified interface for initializing chat models from various providers
using LangChain's modern init_chat_model function, with additional support for OpenRouter.
"""

from langchain.chat_models import init_chat_model
from app.openrouter import ChatOpenRouter
from app.openwebui import ChatOpenWebUI


def init_hyperion_chat_model(model_name: str, **kwargs):
    """
    Initialize a chat model with support for standard LangChain providers plus OpenRouter and OpenWebUI.
    
    Args:
        model_name: Model identifier in format "provider:model" or just "model"
                   Supported formats:
                   - "openai:o4-mini" (OpenAI)
                   - "azure_openai:o4-mini" (Azure OpenAI) 
                   - "ollama:deepseek-r1:70b" (Ollama)
                   - "anthropic:claude-3-5-sonnet-latest" (Anthropic)
                   - "openrouter:meta-llama/llama-3.1-8b-instruct" (OpenRouter)
                   - "openwebui:deepseek-r1:70b" (OpenWebUI)
        **kwargs: Additional arguments passed to the model initialization
    
    Returns:
        Initialized chat model instance
        
    Environment Variables Required:
        For OpenAI:
            - OPENAI_API_KEY
            
        For Azure OpenAI:
            - AZURE_OPENAI_API_KEY
            - AZURE_OPENAI_ENDPOINT  
            - OPENAI_API_VERSION (optional, defaults to latest)
            
        For Ollama:
            - OLLAMA_HOST (optional, defaults to http://localhost:11434)
            
        For Anthropic:
            - ANTHROPIC_API_KEY
            
        For OpenRouter:
            - OPENROUTER_API_KEY
            
        For OpenWebUI:
            - OPENWEBUI_BASE_URL
            - OPENWEBUI_API_KEY
    """
    if model_name.startswith("openrouter:"):
        # Handle OpenRouter separately as it's not supported by init_chat_model
        actual_model = model_name.replace("openrouter:", "")
        return ChatOpenRouter(model=actual_model, **kwargs)
    
    if model_name.startswith("openwebui:"):
        # Handle OpenWebUI separately as it's not supported by init_chat_model
        actual_model = model_name.replace("openwebui:", "")
        return ChatOpenWebUI(model=actual_model, **kwargs)
    
    # Use LangChain's init_chat_model for all other providers
    return init_chat_model(model_name, **kwargs)
