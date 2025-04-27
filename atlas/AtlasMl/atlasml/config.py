from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    WEAVIATE_HOST: str = "127.0.0.1"
    WEAVIATE_PORT: int = 8080
    WEAVIATE_GRPC_PORT: int = 50051
settings = Settings()