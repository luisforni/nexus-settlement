from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
import xgboost as xgb

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.models.feature_engineering import (
    FEATURE_NAMES,
    RawTransactionData,
    engineer_features,
)
from app.models.fraud_detector import ModelMetadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_model")

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "SGD"]
_HIGH_RISK = {"USD", "EUR", "GBP"}

_RNG = random.Random(42)
_NP_RNG = np.random.default_rng(42)

def _random_timestamp(days_back: int = 90) -> datetime:
    now = datetime.now(timezone.utc)
    delta = timedelta(
        days=_RNG.uniform(0, days_back),
        hours=_RNG.uniform(0, 24),
        minutes=_RNG.uniform(0, 60),
    )
    return now - delta

def _make_normal_transaction() -> tuple[RawTransactionData, int]:

    amount = Decimal(str(round(_NP_RNG.lognormal(mean=5.5, sigma=1.5), 2)))
    amount = max(Decimal("1.00"), min(amount, Decimal("50000.00")))
    currency = _RNG.choice(CURRENCIES)
    ts = _random_timestamp()

    return (
        RawTransactionData(
            settlement_id=str(uuid.uuid4()),
            amount=amount,
            currency=currency,
            payer_id=str(uuid.uuid4()),
            payee_id=str(uuid.uuid4()),
            timestamp=ts,
            payer_historical_mean=float(amount) * _NP_RNG.uniform(0.7, 1.3),
            payer_historical_std=float(amount) * _NP_RNG.uniform(0.1, 0.5),
            velocity_1m=_RNG.randint(0, 2),
            velocity_5m=_RNG.randint(0, 5),
            velocity_1h=_RNG.randint(0, 20),
            velocity_amount_1h=float(amount) * _RNG.uniform(0.5, 3.0),
            is_new_payee=_RNG.random() < 0.15,
            payer_amount_decile=_RNG.randint(3, 8),
        ),
        0,
    )

def _make_fraudulent_transaction() -> tuple[RawTransactionData, int]:

    fraud_type = _RNG.choice(["high_amount", "high_velocity", "new_payee", "combined"])

    base_amount = Decimal(str(round(_NP_RNG.lognormal(mean=5.5, sigma=1.5), 2)))

    if fraud_type == "high_amount":

        multiple = _RNG.choice([100, 500, 1000, 5000, 10000])
        amount = Decimal(str(multiple * _RNG.randint(10, 100)))
        velocity_1m = _RNG.randint(0, 1)
        velocity_5m = _RNG.randint(0, 3)
        velocity_1h = _RNG.randint(0, 10)
        is_new_payee = _RNG.random() < 0.30
        payer_mean = float(base_amount) * 0.2

    elif fraud_type == "high_velocity":

        amount = Decimal(str(round(float(base_amount) * _NP_RNG.uniform(0.8, 1.2), 2)))
        velocity_1m = _RNG.randint(5, 10)
        velocity_5m = _RNG.randint(15, 40)
        velocity_1h = _RNG.randint(50, 200)
        is_new_payee = _RNG.random() < 0.20
        payer_mean = float(amount) * _NP_RNG.uniform(0.9, 1.1)

    elif fraud_type == "new_payee":

        amount = Decimal(str(round(_NP_RNG.uniform(3000, 50000), 2)))
        velocity_1m = _RNG.randint(0, 2)
        velocity_5m = _RNG.randint(0, 5)
        velocity_1h = _RNG.randint(0, 15)
        is_new_payee = True
        payer_mean = float(amount) * 0.10

    else:
        multiple = _RNG.choice([500, 1000, 5000])
        amount = Decimal(str(multiple * _RNG.randint(5, 50)))
        velocity_1m = _RNG.randint(3, 8)
        velocity_5m = _RNG.randint(10, 30)
        velocity_1h = _RNG.randint(40, 150)
        is_new_payee = True
        payer_mean = float(amount) * 0.05

    ts = _random_timestamp()
    if _RNG.random() < 0.6:

        ts = ts.replace(hour=_RNG.randint(0, 6))

    currency = _RNG.choice(["USD", "EUR", "GBP"])

    return (
        RawTransactionData(
            settlement_id=str(uuid.uuid4()),
            amount=amount,
            currency=currency,
            payer_id=str(uuid.uuid4()),
            payee_id=str(uuid.uuid4()),
            timestamp=ts,
            payer_historical_mean=payer_mean,
            payer_historical_std=max(payer_mean * 0.1, 1.0),
            velocity_1m=velocity_1m,
            velocity_5m=velocity_5m,
            velocity_1h=velocity_1h,
            velocity_amount_1h=float(amount) * velocity_1h,
            is_new_payee=is_new_payee,
            payer_amount_decile=_RNG.randint(8, 10),
        ),
        1,
    )

def generate_dataset(
    n_samples: int = 10_000,
    fraud_rate: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a feature matrix X and label vector y."""
    n_fraud = int(n_samples * fraud_rate)
    n_normal = n_samples - n_fraud

    logger.info(
        "Generating dataset: %d normal + %d fraud = %d total",
        n_normal,
        n_fraud,
        n_samples,
    )

    rows: list[np.ndarray] = []
    labels: list[int] = []

    for _ in range(n_normal):
        txn, label = _make_normal_transaction()
        rows.append(engineer_features(txn))
        labels.append(label)

    for _ in range(n_fraud):
        txn, label = _make_fraudulent_transaction()
        rows.append(engineer_features(txn))
        labels.append(label)

    X = np.vstack(rows).astype(np.float32)
    y = np.array(labels, dtype=np.int32)

    idx = _NP_RNG.permutation(len(y))
    return X[idx], y[idx]

def train_xgboost(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> xgb.Booster:
    """Train an XGBoost binary classifier with early stopping."""
    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    logger.info("XGBoost scale_pos_weight=%.2f", scale_pos_weight)

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_NAMES)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_NAMES)

    params = {
        "objective": "binary:logistic",
        "eval_metric": ["logloss", "auc"],
        "max_depth": 6,
        "learning_rate": 0.05,
        "n_estimators": 500,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "scale_pos_weight": scale_pos_weight,
        "tree_method": "hist",
        "seed": 42,
    }

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=500,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=30,
        verbose_eval=50,
    )
    return model

def train_isolation_forest(X_normal: np.ndarray) -> IsolationForest:

    logger.info(
        "Training IsolationForest on %d normal samples", len(X_normal)
    )
    iso = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    iso.fit(X_normal)
    return iso

def evaluate(
    xgb_model: xgb.Booster,
    iso_model: IsolationForest,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> dict[str, float]:
    """Compute ensemble AUC-ROC on the held-out test set."""
    dtest = xgb.DMatrix(X_test, feature_names=FEATURE_NAMES)
    xgb_scores = xgb_model.predict(dtest).astype(float)

    iso_raw = -iso_model.score_samples(X_test)
    iso_scores = np.clip(iso_raw, 0.0, 1.0)

    ensemble = 0.70 * xgb_scores + 0.30 * iso_scores

    auc = float(roc_auc_score(y_test, ensemble))
    xgb_auc = float(roc_auc_score(y_test, xgb_scores))
    iso_auc = float(roc_auc_score(y_test, iso_scores))

    logger.info(
        "Test AUC — XGBoost: %.4f | IsolationForest: %.4f | Ensemble: %.4f",
        xgb_auc,
        iso_auc,
        auc,
    )
    return {"auc_roc": auc, "xgb_auc": xgb_auc, "iso_auc": iso_auc}

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--samples", type=int, default=10_000, help="Total dataset size")
    p.add_argument(
        "--fraud-rate",
        type=float,
        default=0.08,
        help="Fraction of samples that are fraudulent (default: 0.08)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent.parent / "artifacts" / "fraud_model.joblib",
        help="Output path for the joblib artifact",
    )
    return p.parse_args()

def main() -> None:
    args = parse_args()

    X, y = generate_dataset(n_samples=args.samples, fraud_rate=args.fraud_rate)

    X_train_val, X_test, y_train_val, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_val,
        y_train_val,
        test_size=0.15,
        random_state=42,
        stratify=y_train_val,
    )

    logger.info(
        "Split — train: %d | val: %d | test: %d",
        len(X_train),
        len(X_val),
        len(X_test),
    )

    xgb_model = train_xgboost(X_train, y_train, X_val, y_val)
    iso_model = train_isolation_forest(X_train[y_train == 0])

    metrics = evaluate(xgb_model, iso_model, X_test, y_test)

    if metrics["auc_roc"] < 0.80:
        logger.warning(
            "Ensemble AUC-ROC %.4f is below 0.80 — consider more samples or feature tuning.",
            metrics["auc_roc"],
        )

    output_path: Path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    artifact = {
        "xgb": xgb_model,
        "isolation_forest": iso_model,
        "metadata": ModelMetadata(
            version="1.0.0",
            training_date=datetime.now(timezone.utc).isoformat(),
            auc_roc=round(metrics["auc_roc"], 4),
            feature_names=FEATURE_NAMES,
            model_type="XGBoost+IsolationForest",
        ),
    }

    joblib.dump(artifact, output_path, compress=3)
    logger.info("Model artifact saved → %s", output_path)

    summary = {
        "artifact": str(output_path),
        "training_samples": int(len(X_train)),
        "feature_count": len(FEATURE_NAMES),
        **metrics,
    }
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
