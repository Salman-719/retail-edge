from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://retailvision:retailvision_dev@localhost:5432/retailvision"
    REDIS_URL: str = "redis://localhost:6379/0"

    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "retailvision"
    S3_SECRET_KEY: str = "retailvision_dev"
    S3_BUCKET: str = "retailvision"

    SERVICE_NAME: str = "iep2-vision"
    PORT: int = 8002

    TMP_DIR: str = "/tmp/retailvision"


settings = Settings()
