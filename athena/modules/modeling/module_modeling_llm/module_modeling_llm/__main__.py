from athena.runtime.module_app import create_module_app
from .plugin import ModelingPlugin

app = create_module_app(ModelingPlugin())


def main():
    from athena.app import run_app
    from athena.settings import Settings
    import os

    settings = Settings(
        PRODUCTION=os.getenv("PRODUCTION", "False").lower() in ("true", "1", "yes"),
        SECRET=os.getenv("SECRET", "development-secret"),
    )
    run_app(app, settings)


if __name__ == "__main__":
    main()
