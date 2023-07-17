from typing import Dict, Any, Optional
from fastapi import Body, HTTPException, Request
from starlette.responses import JSONResponse

from athena.authenticate import authenticated
from athena.schemas import ExerciseType
from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, AvailableModuleNames, find_module_by_name, request_to_module


@app.api_route(
    "/modules/{module_type}/{module_name}/{path:path}",
    methods=["POST", "GET"],
    responses={
        400: {
            "description": "Module is not of the requested type",
        },
        403: {
            "description": "API secret is invalid - set the environment variable SECRET and the X-API-Secret header "
                           "to the same value",
        },
        404: {
            "description": "Module is not found (not listed in modules.ini)",
        },
        503: {
            "description": "Module is not available",
        },
    },
    response_model=ModuleResponse[Any, Any],
)
@authenticated
async def proxy_to_module(
    module_type: ExerciseType, module_name: AvailableModuleNames, path: str, request: Request, data: Optional[Dict[Any, Any]] = Body(None),
) -> JSONResponse:
    """
    This endpoint is called by the LMS to proxy requests to modules.
    See the module documentation for the possible choices for paths.
    Example module documentation on this: [http://localhost:5001/docs](http://localhost:5001/docs).
    """
    if request.method == "GET" and data is not None:
        raise HTTPException(status_code=400, detail="GET request should not contain a body")

    module = await find_module_by_name(module_name)
    if module is None:
        raise HTTPException(status_code=404, detail=f"Module {module_name} not found. Is it listed in modules.ini?")
    if module.type != module_type:
        raise HTTPException(status_code=400, detail=f"Found module {module_name} is not of type {module_type}.")
    
    module_config = request.headers.get('X-Module-Config')
    resp = await request_to_module(
        module,
        module_config,
        '/' + path,
        data,
        method=request.method,
    )
    return JSONResponse(
        status_code=resp.status,
        content=resp.dict(),
    )
