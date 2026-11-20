from typing import Annotated, Literal

from pydantic import Field, SecretStr, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Password = Annotated[SecretStr, StringConstraints(min_length=1)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    postgres_db: NonBlank
    postgres_host: NonBlank = "127.0.0.1"
    postgres_port: Annotated[int, Field(ge=1, le=65535)] = 5432
    postgres_user: NonBlank
    postgres_password: Password
    rabbitmq_default_user: NonBlank
    rabbitmq_default_pass: Password
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
