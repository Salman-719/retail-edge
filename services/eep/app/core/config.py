from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://retailvision:retailvision_dev@localhost:5432/retailvision"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # S3 / MinIO
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "retailvision"
    S3_SECRET_KEY: str = "retailvision_dev"
    S3_BUCKET: str = "retailvision"

    # Service identity
    SERVICE_NAME: str = "eep"
    PORT: int = 8000

    # Tmp directory for video/image processing
    TMP_DIR: str = "/tmp/retailvision"


settings = Settings()
