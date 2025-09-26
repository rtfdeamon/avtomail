from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env."""

    project_name: str = Field(default="Avtomail")
    api_v1_prefix: str = Field(default="/api")
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/avtomail",
        description="SQLAlchemy database URL",
    )

    imap_host: str = Field(default="imap.example.com")
    imap_port: int = Field(default=993)
    imap_username: str | None = None
    imap_password: str | None = None
    imap_folder: str = Field(default="INBOX")

    smtp_host: str = Field(default="smtp.example.com")
    smtp_port: int = Field(default=587)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = Field(default=True)
    smtp_from_address: str = Field(default="[email protected]")

    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3")
    llm_confidence_marker: str = Field(
        default="MANAGER",
        description="Marker that signals the LLM is uncertain and requires human review.",
    )
    auto_send_llm_replies: bool = Field(
        default=False,
        description="Controls whether confident LLM responses are sent automatically.",
    )

    secret_key: str = Field(default="change-me", repr=False)
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30)

    poll_interval_seconds: int = Field(default=120)
    enable_task_queue: bool = Field(default=True)
    celery_broker_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/0")
    celery_task_always_eager: bool = Field(default=False)
    celery_task_eager_propagates: bool = Field(default=True)
    default_admin_email: str = Field(default="admin", description="Bootstrap admin login")
    default_admin_password: str = Field(default="admin", description="Bootstrap admin password", repr=False)

    attachments_dir: str = Field(default="storage/attachments")
    max_attachment_size_mb: int = Field(default=25)

    manager_review_delay_minutes: int = Field(default=0)
    language_detection_min_chars: int = Field(default=20)
    log_level: str = Field(default="INFO")
    sentry_dsn: str | None = Field(default=None, repr=False)
    sentry_environment: str | None = None
    sentry_traces_sample_rate: float = Field(default=0.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Return the application settings singleton."""

    return Settings()
