import requests

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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "modules": {
            module.name: {
                "url": module.url,
                "healthy": await is_healthy(module),
            }
            for module in get_module_list()
        }
    }
