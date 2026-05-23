from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://retailvision:retailvision_dev@localhost:5432/retailvision"
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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
