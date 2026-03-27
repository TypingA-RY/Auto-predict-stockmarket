"""
core/indicators.py — 技术指标计算
"""
import pandas as pd
import numpy as np


def add_ma(df: pd.DataFrame, col: str = "收盘", periods=(5, 10, 20, 60)) -> pd.DataFrame:
    for p in periods:
        df[f"MA{p}"] = df[col].rolling(p).mean()
    return df


def add_macd(df: pd.DataFrame, col: str = "收盘",
             fast=12, slow=26, signal=9) -> pd.DataFrame:
    exp_fast   = df[col].ewm(span=fast,   adjust=False).mean()
    exp_slow   = df[col].ewm(span=slow,   adjust=False).mean()
    df["MACD"] = exp_fast - exp_slow
    df["Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["Hist"]   = df["MACD"] - df["Signal"]
    return df


def add_rsi(df: pd.DataFrame, col: str = "收盘", period: int = 14) -> pd.DataFrame:
    delta = df[col].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def add_bollinger(df: pd.DataFrame, col: str = "收盘",
                  period: int = 20, std: float = 2.0) -> pd.DataFrame:
    df["BB_mid"]   = df[col].rolling(period).mean()
    rolling_std    = df[col].rolling(period).std()
    df["BB_upper"] = df["BB_mid"] + std * rolling_std
    df["BB_lower"] = df["BB_mid"] - std * rolling_std
    return df


def calc_win_probability(df: pd.DataFrame, col: str = "收盘") -> pd.DataFrame:
    """
    计算每日涨跌概率相关指标
    返回包含以下列的 DataFrame：
      - return_pct   : 日涨跌幅
      - is_up        : 当日上涨 (bool)
      - win_rate_20  : 近20日胜率
      - win_rate_60  : 近60日胜率
      - weekday      : 星期 (0=Mon)
      - month        : 月份
    """
    df = df.copy()
    df["return_pct"] = df[col].pct_change() * 100
    df["is_up"]      = df["return_pct"] > 0
    df["win_rate_20"] = df["is_up"].rolling(20).mean() * 100
    df["win_rate_60"] = df["is_up"].rolling(60).mean() * 100
    df["weekday"]    = df.index.dayofweek
    df["month"]      = df.index.month
    return df
