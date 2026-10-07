import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_secrets():
    # core.logger depends on config.settings, which isn't built until after this runs
    from loguru import logger
    import boto3
    from infisical_sdk import InfisicalSDKClient

    is_aws = (
            "AWS_LAMBDA_FUNCTION_NAME" in os.environ
            or "AWS_EXECUTION_ENV" in os.environ
    )

    def is_in_docker():
        return os.path.exists('/.dockerenv')

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

            client = InfisicalSDKClient(host="https://eu.infisical.com")
            client.auth.universal_auth.login(
                client_id=client_id,
                client_secret=auth_secret
            )


            infisical_secrets = client.secrets.list_secrets(
                project_id=project_id,
                environment_slug="prod" if is_aws else "dev",
                secret_path="/"
            )
            for s in infisical_secrets.secrets:
                os.environ[s.secretKey] = str(s.secretValue)
        except Exception as e:
            logger.opt(exception=e).warning(f"Error fetching secrets from Infisical: {type(e).__name__}: {e!r}")
    else:
        logger.warning("Missing INFISICAL_CLIENT_ID, INFISICAL_AUTH_SECRET, or INFISICAL_PROJECT_ID in environment variables")

    os.environ["DEBUG"] = "false" if is_aws or is_in_docker() else "true"
