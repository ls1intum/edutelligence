import yaml
from fastapi.openapi.utils import get_openapi
from shared.security import add_security_schema_to_openapi
from app.settings import settings

# Needs to be set to True before importing app.main
settings.IS_GENERATING_OPENAPI = True

from app.main import app


def get_openapi_specs():
    """Generate OpenAPI schema for the application."""
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
    """Export OpenAPI schema to a YAML file."""
    try:
        yaml_spec = get_openapi_specs()
        with open("./openapi.yaml", "w") as f:
            f.write(yaml_spec)
        print("OpenAPI YAML specification generated successfully.")
        return 0
    except Exception as e:
        print(f"Error generating OpenAPI specs: {e}")
        return 1


if __name__ == "__main__":
    export()
