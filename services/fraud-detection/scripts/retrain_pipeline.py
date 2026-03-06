"""
Automated fraud model retraining pipeline.

This script:
  1. Generates fresh synthetic training data (same distribution as train_model.py)
  2. Trains a new XGBoost + IsolationForest ensemble
  3. Validates that the new model's AUC-ROC exceeds the configured threshold
  4. Atomically replaces the artifact if validation passes
  5. Optionally notifies the notification-service via Kafka that a new model
     is live (so the fraud-detection pod can be signalled to hot-reload)

Usage:
    # One-shot retraining (from repo root):
    python services/fraud-detection/scripts/retrain_pipeline.py

    # With custom options:
    python services/fraud-detection/scripts/retrain_pipeline.py \
        --n-samples 50000 \
        --min-auc 0.95 \
        --artifact /app/artifacts/fraud_model.joblib \
        --kafka-brokers kafka:29092

    # Scheduled via cron / Kubernetes CronJob — see infrastructure/k8s/retrain-cronjob.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SERVICE_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("retrain_pipeline")

DEFAULT_ARTIFACT = str(SERVICE_ROOT / "artifacts" / "fraud_model.joblib")
DEFAULT_MIN_AUC  = 0.90
DEFAULT_SAMPLES  = 20_000
DEFAULT_FRAUD_RATE = 0.08

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fraud model retraining pipeline")
    p.add_argument("--n-samples",     type=int,   default=DEFAULT_SAMPLES,  help="Training dataset size")
    p.add_argument("--fraud-rate",    type=float, default=DEFAULT_FRAUD_RATE, help="Fraction of fraudulent samples")
    p.add_argument("--min-auc",       type=float, default=DEFAULT_MIN_AUC,  help="Minimum AUC-ROC to accept new model")
    p.add_argument("--artifact",      type=str,   default=DEFAULT_ARTIFACT, help="Path to the model artifact")
    p.add_argument("--kafka-brokers", type=str,   default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", ""), help="Kafka brokers for model-ready notification")
    p.add_argument("--topic",         type=str,   default="nexus.notifications", help="Topic for model-ready events")
    p.add_argument("--dry-run",       action="store_true", help="Train and evaluate but do not replace the artifact")
    return p

def train(n_samples: int, fraud_rate: float) -> tuple:

    sys.path.insert(0, str(SCRIPT_DIR))
    from train_model import generate_dataset, train_model

    logger.info("Generating dataset (%d samples, %.0f%% fraud)...", n_samples, fraud_rate * 100)
    X, y = generate_dataset(n_samples=n_samples, fraud_rate=fraud_rate)

    logger.info("Training model...")
    detector, auc = train_model(X, y)

    tmp = tempfile.mktemp(suffix=".joblib")
    import joblib
    joblib.dump(
        {
            "xgb_model":        detector._xgb_model,
            "isolation_forest": detector._isolation_forest,
            "metadata": {
                "version":       datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
                "training_date": datetime.now(timezone.utc).isoformat(),
                "auc_roc":       auc,
                "feature_names": detector.metadata.feature_names,
                "model_type":    detector.metadata.model_type,
            },
        },
        tmp,
    )
    return tmp, auc

def publish_model_ready(brokers: str, topic: str, auc: float, version: str) -> None:

    try:
        from confluent_kafka import Producer
    except ImportError:
        try:
            from aiokafka import AIOKafkaProducer
        except ImportError:
            logger.warning("No Kafka client available — skipping model-ready notification")
            return

    event = {
        "event_id":  str(uuid.uuid4()),
        "event_type": "model.retrained",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "service":  "fraud-detection",
            "version":  version,
            "auc_roc":  auc,
            "artifact": DEFAULT_ARTIFACT,
        },
    }

    try:

        p = Producer({"bootstrap.servers": brokers, "socket.timeout.ms": 5000})
        p.produce(topic, json.dumps(event).encode())
        p.flush(timeout=5)
        logger.info("Published model.retrained event to %s", topic)
    except Exception as exc:
        logger.warning("Failed to publish model-ready event: %s", exc)

def run(args: argparse.Namespace) -> int:
    start = time.monotonic()

    logger.info("━━━ Fraud model retraining pipeline starting ━━━")
    logger.info("  artifact : %s", args.artifact)
    logger.info("  min AUC  : %.3f", args.min_auc)
    logger.info("  samples  : %d", args.n_samples)
    logger.info("  dry-run  : %s", args.dry_run)

    tmp_path, auc = train(n_samples=args.n_samples, fraud_rate=args.fraud_rate)

    logger.info("Training complete — AUC-ROC: %.4f (threshold: %.4f)", auc, args.min_auc)

    if auc < args.min_auc:
        logger.error(
            "Model REJECTED: AUC %.4f < threshold %.4f — keeping existing artifact",
            auc, args.min_auc,
        )
        Path(tmp_path).unlink(missing_ok=True)
        return 1

    logger.info("Model ACCEPTED (AUC %.4f >= %.4f)", auc, args.min_auc)

    if args.dry_run:
        logger.info("Dry-run mode — artifact NOT replaced")
        Path(tmp_path).unlink(missing_ok=True)
    else:
        artifact_path = Path(args.artifact)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(tmp_path, str(artifact_path))
        logger.info("Artifact updated: %s", artifact_path)

        import joblib
        meta = joblib.load(str(artifact_path)).get("metadata", {})
        version = meta.get("version", "unknown")

        if args.kafka_brokers:
            publish_model_ready(args.kafka_brokers, args.topic, auc, version)

    elapsed = time.monotonic() - start
    logger.info("━━━ Pipeline finished in %.1f s ━━━", elapsed)
    return 0

if __name__ == "__main__":
    parser = _build_parser()
    sys.exit(run(parser.parse_args()))
