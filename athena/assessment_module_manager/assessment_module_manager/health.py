from typing import Annotated

import requests
from pydantic import BaseModel, Field

from .app import app
from .logger import logger
from .module import Module, get_module_list


async def is_healthy(module: Module) -> bool:
    try:
        response = requests.get(module.url)
        return response.status_code == 200 and response.json()["status"] == "ok"
    except requests.exceptions.ConnectionError:
        logger.error("Server is not reachable: %s", module)
        return False
    except KeyError:
        logger.error("Response does not contain a 'status' key: %s", module)
        return False
    except TypeError:
        logger.error("Response is not JSON: %s", module)
        return False


class HealthResponse(BaseModel):
    status: str = Field(const=True, default="ok", example="ok")
    modules: dict = Field(
        example=[
            {
                "module_example": {
                    "url": "http://localhost:5001",
                    "healthy": True
                }
            }
        ]
    )


@app.get("/health")
async def health() -> HealthResponse:
    """
    Health endpoint to find out whether the Assessment Module Manager is healthy,
    and whether all the modules are healthy (i.e. reachable).
    """
    return HealthResponse(
        modules={
            module.name: {
                "url": module.url,
                "healthy": await is_healthy(module),
            }
            for module in get_module_list()
        }
    )
