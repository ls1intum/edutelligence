import yaml
from fastapi.openapi.utils import get_openapi
from app import main
from app.security import add_security_schema_to_openapi


def get_openapi_specs():
    openapi_json = get_openapi(
        title=main.app.title,
        version=main.app.version,
        description=main.app.description,
        contact=main.app.contact,
        routes=main.app.routes,
    )
    openapi_json = add_security_schema_to_openapi(openapi_json)
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
