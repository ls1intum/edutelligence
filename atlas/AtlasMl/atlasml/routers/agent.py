import logging
from functools import lru_cache
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

router = APIRouter(prefix="", tags=["agent"])

class AgentChatRequest(BaseModel):
    message: str
    courseId: Optional[int] = None
    sessionId: Optional[str] = "default"

class AgentChatResponse(BaseModel):
    reply: str
    sessionId: str
    pendingConfirmation: bool = False

@lru_cache(maxsize=1)
def get_agent_instance() -> "AIAgent":
    """Get the global agent instance (no session management)."""
    if not AI_AGENT_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="AI Agent not available - check configuration",
        )
    try:
        agent = AIAgent(model_name="gpt-4o")
        logger.info("Created global agent instance")
        return agent
    except Exception as e:
        logger.exception("Failed to create agent instance")
        raise HTTPException(status_code=500, detail="Failed to initialize agent") from e

@router.post("/chat", response_model=AgentChatResponse, dependencies=[Depends(TokenValidator)])
async def chat_with_agent(request: AgentChatRequest) -> AgentChatResponse:
    """
    Chat endpoint for the AI agent
    """
    try:
        logger.info(f"Agent chat request: {request.message[:100]}...")
        agent = get_agent_instance()
        reply = await agent.handle_prompt_async(request.message, request.courseId)
        has_pending_confirmation = agent.pending_confirmation is not None
        logger.info(f"Agent response (pending_confirmation: {has_pending_confirmation})")
        return AgentChatResponse(
            reply=reply,
            sessionId=request.sessionId,
            pendingConfirmation=has_pending_confirmation
        )
    except ValueError as e:
        logger.warning("Invalid request: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Error processing agent chat request")
        raise HTTPException(status_code=500, detail="Failed to process agent request") from e

@router.get("/health")
async def agent_health():
    """
    Health check for the agent service.
    """
    try:
        if not AI_AGENT_AVAILABLE:
            return {
                "status": "unhealthy",
                "agent_available": False,
                "message": "AI Agent not available"
            }
        try:
            agent = get_agent_instance()
            artemis_ok = await agent.artemis_client.health_check()
            status = "healthy" if artemis_ok else "degraded"
            return {
                "status": status,
                "agent_available": True,
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
