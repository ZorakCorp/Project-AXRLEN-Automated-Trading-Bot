import pandas as pd


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV must include columns: {required}")
    return df


def normalize_market_data(raw_data: dict) -> pd.DataFrame:
    candles = raw_data.get("candles") or []
    return pd.DataFrame(candles)
