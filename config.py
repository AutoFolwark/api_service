import base64
import json
import logging
import os
from enum import Enum

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.logger import logger

load_dotenv()

config_logger = logging.getLogger(__name__)


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
    DB_NAME: str = "test_db"
    DB_USER: str = "postgres"
    DB_PASS: str = "testpass"

    # gRPC
    GRPC_SERVER_PORT: str = "50051"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Auction API
    AUCTION_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


def load_secrets():
    import boto3
    from infisical_sdk import InfisicalSDKClient

    is_aws = (
            "AWS_LAMBDA_FUNCTION_NAME" in os.environ
            or "AWS_EXECUTION_ENV" in os.environ
    )
    if is_aws:
        logger.info("Loading secrets from AWS Secrets Manager")
        try:
            secrets_client = boto3.client('secretsmanager')
            response = secrets_client.get_secret_value(SecretId="prod")
            secrets_dict = json.loads(response['SecretString'])

            client_id = secrets_dict.get("INFISICAL_CLIENT_ID")
            auth_secret = secrets_dict.get("INFISICAL_AUTH_SECRET")
            project_id = secrets_dict.get("INFISICAL_PROJECT_ID")
        except Exception as e:
            logger.error(f"Error loading secrets from AWS Secrets Manager: {e}")
            raise e

    else:
        logger.info("Loading secrets from environment variables")

        client_id = os.environ.get("INFISICAL_CLIENT_ID")
        auth_secret = os.environ.get("INFISICAL_AUTH_SECRET")
        project_id = os.environ.get("INFISICAL_PROJECT_ID")

        logger.info("Loaded secrets from environ successfully")


    if client_id and auth_secret and project_id:
        try:

            client = InfisicalSDKClient(host="https://app.infisical.com")
            client.auth.universal_auth.login(
                client_id=client_id,
                client_secret=auth_secret
            )


            infisical_secrets = client.secrets.list_secrets(
                project_id=project_id,
                environment_slug="production" if is_aws else "development",
                secret_path="/"
            )
            for s in infisical_secrets.secrets:
                os.environ[s.secretKey] = str(s.secretValue)
        except Exception as e:
            config_logger.warning(f"Error fetching secrets from Infisical: {e}")
    else:
        logger.warning("Missing INFISICAL_CLIENT_ID, INFISICAL_AUTH_SECRET, or INFISICAL_PROJECT_ID in environment variables")


load_secrets()
settings = Settings()
