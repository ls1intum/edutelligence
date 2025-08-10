import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional


try:
    from atlasml.agent import AIAgent
    AI_AGENT_AVAILABLE = True
except ImportError as e:
    logging.error(f"Failed to import AIAgent: {e}")
    AI_AGENT_AVAILABLE = False

from atlasml.dependencies import TokenValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

# Global agent instance (no session management as per your requirements)
_global_agent = None

class AgentChatRequest(BaseModel):
    message: str
    courseId: Optional[int] = None
    sessionId: Optional[str] = "default"  # Keep for Java compatibility but ignore

class AgentChatResponse(BaseModel):
    reply: str
    sessionId: str
    pendingConfirmation: bool = False

def get_agent_instance() -> "AIAgent":
    """Get the global agent instance (no session management)."""
    global _global_agent
    
    if not AI_AGENT_AVAILABLE:
        raise HTTPException(status_code=500, detail="AI Agent not available - check configuration")
    
    if _global_agent is None:
        try:
            _global_agent = AIAgent(model_name="gpt-4o")
            logger.info("Created global agent instance")
        except Exception as e:
            logger.error(f"Failed to create agent instance: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}")
    
    return _global_agent

@router.post("/chat", response_model=AgentChatResponse, dependencies=[Depends(TokenValidator)])
async def chat_with_agent(request: AgentChatRequest) -> AgentChatResponse:
    """
    Chat endpoint for the AI agent - compatible with Artemis integration.
    
    This endpoint handles natural language requests for competency management,
    including competency suggestions and mappings to exercises.
    
    Args:
        request: Contains message, optional courseId, and sessionId (sessionId ignored)
        
    Returns:
        AgentChatResponse with reply and confirmation status
    """
    try:
        logger.info(f"Agent chat request: {request.message[:100]}...")
        
        # Get the global agent instance
        agent = get_agent_instance()
        
        # Process the message with course context
        reply = await agent.handle_prompt_async(request.message)
        
        # Check if there's a pending confirmation
        has_pending_confirmation = agent.pending_confirmation is not None
        
        logger.info(f"Agent response (pending_confirmation: {has_pending_confirmation})")
        
        return AgentChatResponse(
            reply=reply,
            sessionId=request.sessionId,  # Echo back for Java compatibility
            pendingConfirmation=has_pending_confirmation
        )
        
    except ValueError as e:
        logger.error(f"Invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing agent chat request: {e}")
        raise HTTPException(status_code=500, detail="Failed to process agent request")

@router.get("/health")
async def agent_health():
    """
    Health check for the agent service.
    
    Returns:
        Health status including agent availability and API connectivity
    """
    try:
        if not AI_AGENT_AVAILABLE:
            return {
                "status": "unhealthy",
                "agent_available": False,
                "message": "AI Agent not available"
            }
        
        # Check if we can create an agent instance
        try:
            agent = get_agent_instance()
            
            # Check Atlas (internal) and Artemis connectivity
            atlas_ok = await agent.atlas_client.health_check()
            artemis_ok = await agent.artemis_client.health_check()
            
            status = "healthy" if atlas_ok and artemis_ok else "degraded"
            
            return {
                "status": status,
                "agent_available": True,
                "atlas_connected": atlas_ok,
                "artemis_connected": artemis_ok
            }
            
        except Exception as e:
            logger.error(f"Agent health check failed: {e}")
            return {
                "status": "unhealthy",
                "agent_available": False,
                "message": str(e)
            }
            
    except Exception as e:
        logger.error(f"Agent health endpoint error: {e}")
        return {
            "status": "error",
            "agent_available": False,
            "message": str(e)
        }