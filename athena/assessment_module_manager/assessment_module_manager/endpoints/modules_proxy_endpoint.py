from typing import Dict, Any, Optional
from fastapi import Body, HTTPException, Request
from starlette.responses import JSONResponse

from assessment_module_manager.authenticate import authenticated
from athena.schemas import ExerciseType
from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, find_module_by_name, request_to_module


@app.api_route(
    "/modules/{module_type}/{module_name}/{path:path}",
    methods=["POST", "GET"],
    responses={
        400: {
            "description": "Module is not of the requested type",
        },
        403: {
            "description": "API secret is invalid - set the environment variable SECRET and the Authorization header "
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
    module_type: ExerciseType, module_name: str, path: str, request: Request, data: Optional[Dict[Any, Any]] = Body(None),
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
    
    # Prepare headers (except Authorization)
    headers = {}
    
    # Module configuration
    module_config = request.headers.get('X-Module-Config')
    if module_config:
        headers['X-Module-Config'] = module_config

    # Experiment information tracking experiment, module configuration, and run
    experiment_id = request.headers.get('X-Experiment-ID')
    if experiment_id:
        headers['X-Experiment-ID'] = experiment_id
    module_configuration_id = request.headers.get('X-Module-Configuration-ID')
    if module_configuration_id:
        headers['X-Module-Configuration-ID'] = module_configuration_id
    run_id = request.headers.get('X-Run-ID')
    if run_id:
        headers['X-Run-ID'] = run_id
    lms_server_url = request.headers.get('X-Server-URL')
    if lms_server_url:
        headers['X-Server-URL'] = lms_server_url

    resp = await request_to_module(
        module,
        headers,
        '/' + path,
        lms_server_url,
        data,
        method=request.method,
    )
    return JSONResponse(
        status_code=resp.status,
        content=resp.model_dump(),
    )
