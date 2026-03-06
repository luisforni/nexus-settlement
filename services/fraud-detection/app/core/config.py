from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: str = Field(default="development")
    DEBUG: bool = Field(default=False)
    FRAUD_LOG_LEVEL: str = Field(default="INFO")
    FRAUD_DETECTION_PORT: int = Field(default=8002, ge=1024, le=65535)
    FRAUD_WORKERS: int = Field(default=4, ge=1, le=32)

    FRAUD_MODEL_PATH: str = Field(
        default="/app/artifacts/fraud_model.joblib",
        description="Absolute path to the trained joblib model artifact.",
    )
    FRAUD_RISK_THRESHOLD: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Risk score threshold above which a transaction is flagged.",
    )

    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        default="localhost:9092",
        description="Kafka broker addresses. Unused by this service but kept for future consumer integration.",
    )
    KAFKA_TOPIC_SETTLEMENTS: str = Field(default="nexus.settlements")
    KAFKA_TOPIC_FRAUD_ALERTS: str = Field(default="nexus.fraud.alerts")
    KAFKA_CONSUMER_GROUP_ID: str = Field(default="nexus-consumer-group")

    CORS_ORIGINS: List[str] = Field(default=["*"])

settings = Settings()
