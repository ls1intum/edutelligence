from fastapi import FastAPI

from shared.security import AuthMiddleware, add_security_schema_to_app
from shared.health import create_health_router

from app.logger import logger
from app.settings import settings
from app.project_meta import project_meta
from app.creation_steps.step8_review_and_refine.router import (
    router as review_and_refine_router,
)
from app.creation_steps.step3_create_solution_repository.router import (
    router as create_solution_repository_router,
)


app = FastAPI(
    title=project_meta.title,
    description=project_meta.description,
    version=project_meta.version,
    contact=project_meta.contact,
)

# Add security schema to the app, can be disabled for development
if not settings.DISABLE_AUTH:
    logger.warning(
        "API authentication is disabled. This is not recommended for production."
    )

    exclude_paths = ["/playground"]
    app.add_middleware(
        AuthMiddleware,
        api_key=settings.API_KEY,
        header_name="X-API-Key",
        exclude_paths=exclude_paths,
    )
    add_security_schema_to_app(
        app, header_name="X-API-Key", exclude_paths=exclude_paths
    )

# Add routers
app.include_router(create_health_router(app.version))
app.include_router(review_and_refine_router)
app.include_router(create_solution_repository_router)
