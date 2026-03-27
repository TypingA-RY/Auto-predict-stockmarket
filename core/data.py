"""
core/data.py — AkShare 数据层，带简单内存缓存
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta


def _default_dates(days=365):
    end   = datetime.today().strftime("%Y%m%d")
    start = (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")
    return start, end


def get_stock_hist(symbol: str, start: str = None, end: str = None,
                   adjust: str = "qfq", days: int = 365) -> pd.DataFrame:
    """A股/ETF 日线历史行情，返回标准化列名 DataFrame"""
    if not start or not end:
        start, end = _default_dates(days)

    # 先尝试个股接口
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start, end_date=end, adjust=adjust
    )

    # 个股接口返回空时，回退到 ETF 接口（如 588000/510xxx 等）
    if df.empty:
        df = ak.fund_etf_hist_em(
            symbol=symbol, period="daily",
            start_date=start, end_date=end, adjust=adjust
        )

    if df.empty:
        raise ValueError(f"未找到 {symbol} 的行情数据，请确认代码是否正确")

    df["日期"] = pd.to_datetime(df["日期"])
    df = df.set_index("日期").sort_index()
    return df


def get_stock_info(symbol: str) -> dict:
    """股票基本信息"""
    try:
        df = ak.stock_individual_info_em(stock=symbol)
        return dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
    except Exception:
        return {}


def get_financial_abstract(symbol: str) -> pd.DataFrame:
    """财务摘要（每股指标、盈利能力等）"""
    try:
        return ak.stock_financial_abstract(stock=symbol)
    except Exception:
        return pd.DataFrame()


def get_profit_sheet(symbol: str) -> pd.DataFrame:
    """利润表"""
    try:
        return ak.stock_profit_sheet_by_report_em(stock=symbol)
    except Exception:
        return pd.DataFrame()


def get_balance_sheet(symbol: str) -> pd.DataFrame:
    """资产负债表"""
    try:
        return ak.stock_balance_sheet_by_report_em(stock=symbol)
    except Exception:
        return pd.DataFrame()


def get_industry_list() -> pd.DataFrame:
    """东方财富行业板块列表"""
    try:
        return ak.stock_board_industry_name_em()
    except Exception:
        return pd.DataFrame()


def get_industry_hist(name: str, days: int = 90) -> pd.DataFrame:
    """行业板块历史行情"""
    start, end = _default_dates(days)
    try:
        df = ak.stock_board_industry_hist_em(
            symbol=name, period="日k",
            start_date=start, end_date=end, adjust=""
        )
        df["日期"] = pd.to_datetime(df["日期"])
        return df.set_index("日期").sort_index()
    except Exception:
        return pd.DataFrame()


def get_industry_spot() -> pd.DataFrame:
    """行业板块实时行情（涨跌幅排行）"""
    try:
        return ak.stock_board_industry_name_em()
    except Exception:
        return pd.DataFrame()


def get_concept_spot() -> pd.DataFrame:
    """概念板块实时行情"""
    try:
        return ak.stock_board_concept_name_em()
    except Exception:
        return pd.DataFrame()
