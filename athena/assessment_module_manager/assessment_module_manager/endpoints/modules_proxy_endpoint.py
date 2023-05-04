from typing import Dict, Any

from fastapi import HTTPException
from starlette.responses import JSONResponse

from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, AvailableModuleNames, find_module_by_name, \
    request_to_module
from athena.common.schemas import ExerciseType


@app.post(
    "/modules/{module_type}/{module_name}/{path:path}",
    responses={
        400: {
            "description": "Module is not of the requested type",
        },
        404: {
            "description": "Module is not found (not listed in modules.ini)",
        },
        503: {
            "description": "Module is not available",
        },
    },
    response_model=ModuleResponse[Any],
)
async def proxy_to_module(
    module_type: ExerciseType, module_name: AvailableModuleNames, path: str, data: Dict[Any, Any]
) -> JSONResponse:
    """
    This endpoint is called by the LMS to proxy requests to modules.
    See the module documentation for the possible choices for paths.
    Example module documentation on this: [http://localhost:5001/docs](http://localhost:5001/docs).
    """
    module = await find_module_by_name(module_name)
    if module is None:
        raise HTTPException(status_code=404, detail=f"Module {module_name} not found. Is it listed in modules.ini?")
    if module.type != module_type:
        raise HTTPException(status_code=400, detail=f"Found module {module_name} is not of type {module_type}.")
    resp = await request_to_module(
        module,
        '/' + path,
        data,
    )
    return JSONResponse(
        status_code=resp.status,
        content=resp.dict(),
    )
