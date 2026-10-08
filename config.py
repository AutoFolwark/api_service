from enum import Enum

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.utils import load_secrets

load_dotenv()




class Environment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "auction-api-service"
    DEBUG: bool = True
    ROOT_PATH: str = ''
    ENVIRONMENT: Environment = Environment.DEVELOPMENT

    @property
    def enable_docs(self) -> bool:
        return self.ENVIRONMENT in [Environment.DEVELOPMENT]

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = Field(
        default="test_db",
        alias="API_DB_NAME",
    )
    DB_USER: str = Field(
        default="postgres",
        alias="API_DB_USER",
    )
    DB_PASS: str = Field(
        default="testpass",
        alias="API_DB_PASS",
    )

    # gRPC
    GRPC_SERVER_PORT: str = "50051"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Auction API
    AUCTION_API_KEY: str = ""

    # Sitemaps
    SITE_URL: str = "https://bidmax.eu"
    SITEMAP_BUCKET: str = "files-production-307181770546-eu-central-1-an"
    SITEMAP_BUCKET_REGION: str = "eu-central-1"
    SITEMAP_PREFIX: str = "sitemaps/"
    # Traefik routes bidmax.eu/sitemaps/* to /public/v1/sitemaps/*; the generated index links child sitemaps here.
    SITEMAP_PUBLIC_BASE_URL: str = "https://bidmax.eu/sitemaps"
    SITEMAP_URL_TTL_SECONDS: int = 3600

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )



load_secrets()
settings = Settings()
