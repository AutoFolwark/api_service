import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SPECIAL_MAPPING = {
    "DB_NAME": "API_DB_NAME",
    "DB_PASS": "API_DB_PASS",
    "DB_USER": "API_DB_USER",
}

AWS_CREDENTIAL_ENV_KEYS = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}


def _infisical_environment(is_aws: bool) -> str:

    value = os.environ.get("INFISICAL_ENV", "").strip()
    if value:
        return value
    return "prod" if is_aws else "dev"


def load_secrets():
    # core.logger depends on config.settings, which isn't built until after this runs
    from loguru import logger
    import boto3
    from infisical_sdk import InfisicalSDKClient

    aws_session = boto3.Session()
    aws_credentials = aws_session.get_credentials()
    is_aws = (
            "AWS_LAMBDA_FUNCTION_NAME" in os.environ
            or "AWS_EXECUTION_ENV" in os.environ
            or aws_credentials is not None
    )

    def is_in_docker():
        return os.path.exists('/.dockerenv')

    if is_aws:
        logger.info("Loading secrets from AWS Secrets Manager")
        try:
            secrets_client = aws_session.client(
                "secretsmanager",
                **({"region_name": aws_session.region_name} if aws_session.region_name else {}),
            )
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


            infisical_env = _infisical_environment(is_aws)
            logger.info("Loading secrets from Infisical environment {}", infisical_env)

            infisical_secrets = client.secrets.list_secrets(
                project_id=project_id,
                environment_slug=infisical_env,
                secret_path="/"
            )
            in_lambda = "AWS_LAMBDA_FUNCTION_NAME" in os.environ
            skipped_keys = []
            for s in infisical_secrets.secrets:
                # Lambda signs AWS calls with its role's key pair plus AWS_SESSION_TOKEN;
                # replacing only the key pair makes every AWS request fail with InvalidToken.
                if in_lambda and s.secretKey in AWS_CREDENTIAL_ENV_KEYS:
                    skipped_keys.append(s.secretKey)
                    continue
                secret_value = str(s.secretValue)
                os.environ[s.secretKey] = secret_value
                mapped_key = SPECIAL_MAPPING.get(s.secretKey)
                if mapped_key:
                    os.environ[mapped_key] = secret_value
            if skipped_keys:
                logger.info("Kept Lambda role credentials; ignored Infisical secrets {}", sorted(skipped_keys))
        except Exception as e:
            logger.opt(exception=e).warning(f"Error fetching secrets from Infisical: {type(e).__name__}: {e!r}")
    else:
        logger.warning("Missing INFISICAL_CLIENT_ID, INFISICAL_AUTH_SECRET, or INFISICAL_PROJECT_ID in environment variables")

    os.environ["DEBUG"] = "false" if is_aws or is_in_docker() else "true"
