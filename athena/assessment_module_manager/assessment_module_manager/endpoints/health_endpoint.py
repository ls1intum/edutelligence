import httpx
from pydantic import BaseModel, Field
from typing import Literal

from .modules_endpoint import get_modules
from assessment_module_manager.app import app
from assessment_module_manager.logger import logger
from assessment_module_manager.module import Module


async def is_healthy(module: Module) -> bool:
    try:
        async with httpx.AsyncClient(base_url=str(module.url)) as client:
            response = await client.get('/')
        return response.status_code == 200 and response.json()["status"] == "ok"
    except httpx.ConnectError:
        logger.error("Server is not reachable: %s", module)
        return False
    except KeyError:
        logger.error("Response does not contain a 'status' key: %s", module)
        return False
    except TypeError:
        logger.error("Response is not JSON: %s", module)
        return False


class HealthResponse(BaseModel):
    """
    Response indicating whether the Assessment Module Manager is healthy,
    and whether all the modules are healthy (i.e. reachable).
    Additional information about the modules is also provided.
    """
    status: Literal["ok"] = "ok"
    modules: dict = Field(
        examples=[[
            {
                "module_example": {
                    "url": "http://localhost:5001",
                    "type": "programming",
                    "healthy": True,
                    "supportsEvaluation": True,
                    "supportsNonGradedFeedbackRequests": True,
                    "supportsGradedFeedbackRequests": True
                }
            }
        ]]
    )


@app.get("/health")
async def get_health() -> HealthResponse:
    """
    Health endpoint to find out whether the Assessment Module Manager is healthy,
    and whether all the modules are healthy (i.e. reachable).

    This endpoint is not authenticated.
    """
    return HealthResponse(
        modules={
            module.name: {
                "url": module.url,
                "type": module.type,
                "healthy": await is_healthy(module),
                "supportsEvaluation": module.supports_evaluation,
                "supportsNonGradedFeedbackRequests": module.supports_non_graded_feedback_requests,
                "supportsGradedFeedbackRequests": module.supports_graded_feedback_requests
            }
            for module in get_modules()
        }
    )
