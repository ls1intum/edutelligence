import uvicorn

from .app import app
from .endpoints.health import health

# Add things to __all__ just to mark them as important to import
__all__ = ["app", "health"]
if __name__ == "__main__":
    uvicorn.run("assessment_module_manager.__main__:app", host="0.0.0.0", port=5000, reload=True)
