import yaml
from fastapi.openapi.utils import get_openapi
from shared.security import add_security_schema_to_openapi
from app.main import app
from app.settings import settings


def get_openapi_specs():
    openapi_json = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        contact=app.contact,
        routes=app.routes,
    )
    openapi_json = add_security_schema_to_openapi(
        openapi_json, header_name="X-API-Key", exclude_paths=["/playground"]
    )
    openapi_yaml = yaml.dump(openapi_json, allow_unicode=True)
    return openapi_yaml


def export():
    try:
        yaml_spec = get_openapi_specs()
        with open("./openapi.yaml", "w") as f:
            f.write(yaml_spec)
        print("OpenAPI YAML specification generated successfully.")
    except Exception as e:
        print(f"Error generating OpenAPI specs: {e}")
        exit(1)
