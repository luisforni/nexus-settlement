import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    import joblib
    import xgboost as xgb
    from sklearn.ensemble import IsolationForest

    _ML_AVAILABLE = True
except ImportError:
    _ML_AVAILABLE = False

logger = logging.getLogger(__name__)

@dataclass
class FraudExplanation:

    settlement_id: str
    risk_score: float
    top_features: list[tuple[str, float]]
    decision: str

@dataclass
class ModelMetadata:

    version: str = "untrained"
    training_date: Optional[str] = None
    auc_roc: Optional[float] = None
    feature_names: list[str] = field(default_factory=list)
    model_type: str = "XGBoost+IsolationForest"

class FraudDetector:

    _DECISION_THRESHOLDS = {
        "APPROVE": 0.40,
        "REVIEW": 0.75,
        "BLOCK": 1.01,
    }

    def __init__(
        self,
        xgb_model: Any,
        isolation_forest: Any,
        metadata: ModelMetadata,
    ) -> None:
        self._xgb_model = xgb_model
        self._isolation_forest = isolation_forest
        self.metadata = metadata

    @classmethod
    def load(cls, model_path: str) -> "FraudDetector":

        if not _ML_AVAILABLE:
            raise RuntimeError(
                "ML dependencies (xgboost, scikit-learn, joblib) are not installed."
            )

        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Fraud model artifact not found at {model_path!r}"
            )

        logger.info("Loading fraud model artifact", extra={"path": model_path})
        artifact: dict[str, Any] = joblib.load(path)

        return cls(
            xgb_model=artifact["xgb"],
            isolation_forest=artifact["isolation_forest"],
            metadata=artifact.get("metadata", ModelMetadata()),
        )

    @classmethod
    def untrained(cls) -> "FraudDetector":

        logger.warning(
            "Using UNTRAINED fraud detector — rule-based fallback only"
        )
        return cls(
            xgb_model=None,
            isolation_forest=None,
            metadata=ModelMetadata(version="untrained-v0"),
        )

    @property
    def version(self) -> str:

        return self.metadata.version

    def predict_risk_score(
        self,
        feature_vector: np.ndarray,
        amount: float = 0.0,
    ) -> float:
        """Predict fraud risk score for a feature vector.

        Args:
            feature_vector: 1-D numpy array of engineered features.
            amount: Raw transaction amount (used for rule-based fallback).

        Returns:
            Risk score in [0.0, 1.0]. Higher = more likely fraudulent.
        """
        if self._xgb_model is None:

            return self._rule_based_score(amount)

        dmatrix = xgb.DMatrix(feature_vector.reshape(1, -1))
        xgb_score: float = float(self._xgb_model.predict(dmatrix)[0])

        iso_score_raw: float = float(
            -self._isolation_forest.score_samples(feature_vector.reshape(1, -1))[0]
        )

        iso_score = max(0.0, min(1.0, iso_score_raw))

        ensemble_score = 0.70 * xgb_score + 0.30 * iso_score
        return round(max(0.0, min(1.0, ensemble_score)), 4)

    def explain(
        self,
        settlement_id: str,
        feature_vector: np.ndarray,
        feature_names: list[str],
        amount: float = 0.0,
    ) -> FraudExplanation:
        """Generate a SHAP-based explanation for the fraud score.

        Args:
            settlement_id: Settlement being explained.
            feature_vector: Feature vector passed to the model.
            feature_names: Names corresponding to each feature dimension.
            amount: Raw amount (used in fallback mode).

        Returns:
            FraudExplanation with top contributing features.
        """
        score = self.predict_risk_score(feature_vector, amount=amount)
        decision = self._score_to_decision(score)

        top_features: list[tuple[str, float]] = []

        if self._xgb_model is not None:
            try:
                import shap

                explainer = shap.TreeExplainer(self._xgb_model)
                shap_values: np.ndarray = explainer.shap_values(
                    feature_vector.reshape(1, -1)
                )[0]

                pairs = list(zip(feature_names, shap_values.tolist()))
                pairs.sort(key=lambda x: abs(x[1]), reverse=True)
                top_features = pairs[:10]
            except ImportError:
                logger.debug("SHAP not installed — skipping feature explanation")
        else:
            top_features = [("amount", amount)]

        return FraudExplanation(
            settlement_id=settlement_id,
            risk_score=score,
            top_features=top_features,
            decision=decision,
        )

    def _score_to_decision(self, score: float) -> str:

        if score < self._DECISION_THRESHOLDS["APPROVE"]:
            return "APPROVE"
        if score < self._DECISION_THRESHOLDS["REVIEW"]:
            return "REVIEW"
        return "BLOCK"

    @staticmethod
    def _rule_based_score(amount: float) -> float:

        if amount > 500_000:
            return 0.80
        if amount > 100_000:
            return 0.50
        if amount > 50_000:
            return 0.30
        return 0.10
