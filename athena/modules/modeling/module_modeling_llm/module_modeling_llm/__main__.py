from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=False)
from .app_factory import create_app

app = create_app()


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
