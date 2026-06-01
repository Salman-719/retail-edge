import os

from pydantic_settings import BaseSettings


def _database_url() -> str:
    """Build DATABASE_URL from individual RDS env vars injected by ECS Secrets Manager,
    falling back to the full DATABASE_URL env var for local/docker-compose use."""
    host = os.getenv("DB_HOST")
    if host:
        user = os.getenv("DB_USER", "retailvision")
        pw = os.getenv("DB_PASS", "")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "retailvision")
        return f"postgresql+asyncpg://{user}:{pw}@{host}:{port}/{name}"
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://retailvision:retailvision_dev@localhost:5432/retailvision",
    )


class Settings(BaseSettings):
    DATABASE_URL: str = _database_url()
    REDIS_URL: str = "redis://localhost:6379/0"
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_PUBLIC_URL: str = ""
    S3_ACCESS_KEY: str = "retailvision"
    S3_SECRET_KEY: str = "retailvision_dev"
    S3_BUCKET: str = "retailvision"
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    VISION_INTERNAL_TOKEN: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
