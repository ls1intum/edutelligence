from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    WEAVIATE_HOST: str = "http://localhost:8088"

settings = Settings()