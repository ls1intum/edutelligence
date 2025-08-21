"""
Entry point for the assessment module manager.
"""

import uvicorn
from uvicorn.config import LOGGING_CONFIG
from .app_factory import create_app
from .settings import Settings
from assessment_module_manager.logger import logger

app = create_app()


def main():
    """
    Start the assessment module manager using uvicorn.
    """
    settings = Settings()
    app.state.settings = settings

    LOGGING_CONFIG["formatters"]["default"][
        "fmt"
    ] = "%(asctime)s %(levelname)s --- [%(name)s] : %(message)s"
    LOGGING_CONFIG["formatters"]["access"][
        "fmt"
    ] = "%(asctime)s %(levelname)s --- [%(name)s] : %(message)s"
    logger.info("Starting assessment module manager")

    if settings.production:
        logger.info("Running in PRODUCTION mode")
        uvicorn.run(app, host="0.0.0.0", port=5100)
    else:
        logger.warning("Running in DEVELOPMENT mode")
        uvicorn.run(
            "assessment_module_manager.__main__:app",
            host="0.0.0.0",
            port=5100,
            reload=True,
        )


if __name__ == "__main__":
    main()
