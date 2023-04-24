"""
Registers the module with the Assessment Module Manager so that it knows that the module exists.
In microservice architecture, this is called service discovery.
"""
import asyncio
import os
import socket
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv

from .default_values import ASSESSMENT_MODULE_MANAGER_DEFAULT_URL
from .logger import logger


def get_module_config():
    if os.environ.get("HOST_NAME_FOR_MODULE_URL"):
        # Use the host name to construct the module URL
        # This is used for Docker Compose
        url = f"http://{socket.gethostname()}:{os.environ['PORT']}"
    else:
        # This is used for the local development setup
        url = f"http://localhost:{os.environ['PORT']}"
    return {
        "url": url,
        "type": os.environ["MODULE_TYPE"],
    }

async def register_module():
    """
    Registers the module with the Assessment Module Manager so that it knows that the module exists.
    """
    logger.info("Registering module with Assessment Module Manager...")
    while True:
        try:
            async with httpx.AsyncClient(base_url=ASSESSMENT_MODULE_MANAGER_DEFAULT_URL, timeout=5) as client:
                await client.post(f"/discover/{os.environ['MODULE_NAME']}", json=get_module_config())
            break
        except httpx.ConnectError:
            logger.warning(
                "Connection error while registering module. Is the Assessment Module Manager running? Retrying...")
            await asyncio.sleep(5)


async def unregister_module():
    """
    Unregisters the module with the Assessment Module Manager so that it knows that the module does not exist anymore.
    """
    async with httpx.AsyncClient(base_url=ASSESSMENT_MODULE_MANAGER_DEFAULT_URL) as client:
        await client.delete(f"/discover/{os.environ['MODULE_NAME']}")


@asynccontextmanager
async def lifespan(_):
    load_dotenv(".env")
    await register_module()
    yield  # the application is running...
    await unregister_module()
