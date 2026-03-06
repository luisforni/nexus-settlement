from typing import List

from pydantic import Field, field_validator, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: str = Field(
        default="development",
        description="Runtime environment: development | staging | production",
    )
    DEBUG: bool = Field(default=False)
    SETTLEMENT_LOG_LEVEL: str = Field(default="INFO")
    SETTLEMENT_SERVICE_PORT: int = Field(default=8001, ge=1024, le=65535)
    SETTLEMENT_WORKERS: int = Field(default=4, ge=1, le=32)
    SETTLEMENT_MAX_AMOUNT: float = Field(default=10_000_000.0, gt=0)

    POSTGRES_HOST: str = Field(...)
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DB: str = Field(...)
    POSTGRES_USER: str = Field(...)
    POSTGRES_PASSWORD: str = Field(...)

    @property
    def async_database_url(self) -> str:

        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    REDIS_URL: str = Field(...)

    KAFKA_BOOTSTRAP_SERVERS: str = Field(...)
    KAFKA_TOPIC_SETTLEMENTS: str = Field(default="nexus.settlements")
    KAFKA_TOPIC_NOTIFICATIONS: str = Field(default="nexus.notifications")
    KAFKA_CONSUMER_GROUP_ID: str = Field(default="nexus-consumer-group")
    KAFKA_PROCESSOR_GROUP_ID: str = Field(
        default="nexus-settlement-processor",
        description="Consumer group for the internal state-machine processor.",
    )
    KAFKA_AUTO_OFFSET_RESET: str = Field(
        default="latest",
        description="Where to start consuming when no committed offset exists. "
                    "Use 'earliest' only for initial backfill or development.",
    )

    KAFKA_TOPIC_SETTLEMENTS_DLQ: str = Field(default="nexus.settlements.dlq")
    KAFKA_TOPIC_FRAUD_DLQ: str = Field(default="nexus.fraud.dlq")
    KAFKA_DLQ_CONSUMER_GROUP_ID: str = Field(
        default="nexus-dlq-processor",
        description="Consumer group for the DLQ re-injection processor.",
    )
    KAFKA_DLQ_MAX_RETRIES: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max times a DLQ message is re-injected before permanent failure.",
    )

    JWT_PUBLIC_KEY_BASE64: str = Field(...)
    JWT_ALGORITHM: str = Field(default="RS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, ge=1, le=60)

    FRAUD_DETECTION_URL: str = Field(
        default="http://fraud-detection:8002",
    )
    FRAUD_CHECK_TIMEOUT_SECONDS: float = Field(
        default=3.0,
        gt=0,
        description="HTTP timeout in seconds for synchronous fraud-check calls.",
    )

    ALLOWED_HOSTS: List[str] = Field(default=["*"])
    CORS_ORIGINS: List[str] = Field(default=["*"])

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:

        allowed = {"development", "staging", "production", "testing"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}, got: {v!r}")
        return v

settings = Settings()
