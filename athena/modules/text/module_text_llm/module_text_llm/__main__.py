from athena.runtime.module_app import create_module_app
from .plugin import TextPlugin

app = create_module_app(TextPlugin())


def main():
    from athena.app import run_app
    from athena.settings import Settings

    settings = Settings()
    run_app(app, settings)


if __name__ == "__main__":
    main()
