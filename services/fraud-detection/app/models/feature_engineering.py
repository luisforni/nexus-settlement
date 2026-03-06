import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import numpy as np

FEATURE_NAMES: list[str] = [
    "amount_log",
    "amount_z_score",
    "hour_of_day_sin",
    "hour_of_day_cos",
    "day_of_week_sin",
    "day_of_week_cos",
    "is_weekend",
    "is_round_amount",
    "velocity_1m",
    "velocity_5m",
    "velocity_1h",
    "velocity_amount_1h",
    "is_new_payee",
    "is_high_risk_currency",
    "amount_decile",
]

@dataclass
class RawTransactionData:

    settlement_id: str
    amount: Decimal
    currency: str
    payer_id: str
    payee_id: str
    timestamp: datetime

    payer_historical_mean: float = 0.0
    payer_historical_std: float = 1.0
    velocity_1m: int = 0
    velocity_5m: int = 0
    velocity_1h: int = 0
    velocity_amount_1h: float = 0.0
    is_new_payee: bool = False
    payer_amount_decile: int = 5

    _HIGH_RISK_CURRENCIES: frozenset[str] = frozenset(
        {"USD", "EUR", "GBP"}
    )

def engineer_features(data: RawTransactionData) -> np.ndarray:

    amount_float = float(data.amount)
    ts = data.timestamp.astimezone(timezone.utc)

    hour = ts.hour
    dow = ts.weekday()
    hour_sin = math.sin(2 * math.pi * hour / 24)
    hour_cos = math.cos(2 * math.pi * hour / 24)
    dow_sin = math.sin(2 * math.pi * dow / 7)
    dow_cos = math.cos(2 * math.pi * dow / 7)
    is_weekend = 1.0 if dow >= 5 else 0.0

    amount_log = math.log1p(amount_float)

    std = max(data.payer_historical_std, 1e-6)
    amount_z_score = (amount_float - data.payer_historical_mean) / std

    is_round = (
        1.0 if amount_float >= 100 and amount_float % 10 == 0 else 0.0
    )

    is_high_risk = (
        1.0 if data.currency.upper() in data._HIGH_RISK_CURRENCIES else 0.0
    )

    feature_vector = np.array(
        [
            amount_log,
            amount_z_score,
            hour_sin,
            hour_cos,
            dow_sin,
            dow_cos,
            is_weekend,
            is_round,
            float(data.velocity_1m),
            float(data.velocity_5m),
            float(data.velocity_1h),
            data.velocity_amount_1h,
            float(int(data.is_new_payee)),
            is_high_risk,
            float(data.payer_amount_decile),
        ],
        dtype=np.float32,
    )

    assert len(feature_vector) == len(FEATURE_NAMES), (
        f"Feature vector length {len(feature_vector)} != "
        f"expected {len(FEATURE_NAMES)}"
    )
    return feature_vector
