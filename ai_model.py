import logging
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


def create_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.sort_values("timestamp")
    df["return_1"] = df["close"].pct_change()
    df["ma_5"] = df["close"].rolling(5).mean()
    df["ma_10"] = df["close"].rolling(10).mean()
    df["momentum"] = df["close"] - df["close"].shift(5)
    df["volatility"] = df["return_1"].rolling(10).std()
    df["volume_change"] = df["volume"].pct_change()
    df = df.dropna().reset_index(drop=True)
    return df


def create_target(df: pd.DataFrame, threshold: float = 0.002) -> pd.Series:
    future_return = df["close"].shift(-1) / df["close"] - 1
    signal = (future_return > threshold).astype(int)
    return signal[:-1]


class PredictionModel:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, solver="liblinear")),
        ])

    def train(self, df: pd.DataFrame) -> None:
        df = create_features(df)
        target = create_target(df)
        features = df.loc[:-2, ["return_1", "ma_5", "ma_10", "momentum", "volatility", "volume_change"]]
        self.pipeline.fit(features, target)
        logger.info("Model training complete")

    def save(self) -> None:
        if not self.model_path:
            raise ValueError("Model path is not configured")
        joblib.dump(self.pipeline, self.model_path)
        logger.info("Saved model to %s", self.model_path)

    def load(self) -> None:
        if not self.model_path:
            raise ValueError("Model path is not configured")
        self.pipeline = joblib.load(self.model_path)
        logger.info("Loaded model from %s", self.model_path)

    def predict(self, df: pd.DataFrame) -> int:
        df = create_features(df)
        features = df.iloc[[-1]][["return_1", "ma_5", "ma_10", "momentum", "volatility", "volume_change"]]
        signal = int(self.pipeline.predict(features)[0])
        return signal

    def predict_label(self, df: pd.DataFrame) -> str:
        signal = self.predict(df)
        return "LONG" if signal == 1 else "HOLD"
