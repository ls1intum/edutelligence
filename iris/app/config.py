from pydantic import BaseSettings


class Settings(BaseSettings):
    openai_token: str
    openai_api_base: str
    openai_api_type: str
    openai_api_version: str
    openai_deployment_id: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
