"""
backtest.py — 改进版回测（v2）

改进点：
  1. 大盘趋势过滤  —— 沪深300 收盘 > MA20 且 MA5 > MA20 时才允许信号
  2. 3日持仓期    —— 衡量持股3日（而非纯次日）的收益，模拟止损止盈
  3. 更优盈亏比   —— 止损 3%，止盈 9%（3:1）；若3日内触达则提前出场

运行：  python3 backtest.py
输出：  backtest_v2_result.csv  /  backtest_v2_report.png
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import akshare as ak
import warnings
warnings.filterwarnings("ignore")

plt.rcParams["font.family"] = ["Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# ── 配置 ────────────────────────────────────────────────────────────────
BACKTEST_YEARS = 3
WARMUP_DAYS    = 80
SCORE_THRESH   = 7
UNIVERSE_SIZE  = 80
MAX_WORKERS    = 8
HOLD_DAYS      = 3      # 持仓天数
STOP_PCT       = 0.10   # 止损 10%
TAKE_PCT       = 0.20   # 止盈 20%（2:1）
OUTPUT_CSV     = "backtest_v2_result.csv"
OUTPUT_PNG     = "backtest_v2_report.png"
BG             = "#1a1a2e"


# ── 1. 大盘趋势过滤 ──────────────────────────────────────────────────────
def get_market_filter(total_days: int) -> pd.Series:
    """
    返回 Series(index=date, value=True/False)
    True  = 大盘处于上升趋势，允许信号
    False = 大盘弱势，过滤信号
    """
    try:
        df = ak.stock_zh_index_daily(symbol="sh000300")
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        cutoff = datetime.today() - timedelta(days=total_days + 30)
        df = df[df.index >= pd.Timestamp(cutoff)]
        close = df["close"].astype(float)
        ma5   = close.rolling(5).mean()
        ma20  = close.rolling(20).mean()
        ma60  = close.rolling(60).mean()
        # 上升趋势：收盘 > MA20 且 MA5 > MA20（至少短期趋势向上）
        uptrend = (close > ma20) & (ma5 > ma20)
        # 强趋势加分：同时满足 > MA60
        strong  = uptrend & (close > ma60)
        print(f"  大盘过滤：上升趋势交易日 {uptrend.sum()} 天 / "
              f"强趋势 {strong.sum()} 天 / 共 {len(uptrend)} 天")
        return uptrend
    except Exception as e:
        print(f"  ⚠ 获取大盘数据失败: {e}，跳过市场过滤")
        return None


# ── 2. 指标计算（向量化）────────────────────────────────────────────────
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close  = df["收盘"].astype(float)
    high   = df["最高"].astype(float)
    low    = df["最低"].astype(float)
    volume = df["成交量"].astype(float)

    df["ma5"]  = close.rolling(5).mean()
    df["ma10"] = close.rolling(10).mean()
    df["ma20"] = close.rolling(20).mean()
    df["ma60"] = close.rolling(60).mean()

    ema12      = close.ewm(span=12, adjust=False).mean()
    ema26      = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["sig"]  = df["macd"].ewm(span=9, adjust=False).mean()
    df["hist"] = df["macd"] - df["sig"]

    delta      = close.diff()
    gain       = delta.clip(lower=0).rolling(14).mean()
    loss       = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"]  = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    df["vr"]   = volume / volume.rolling(20).mean()

    # ── 预先计算止损止盈模拟收益（HOLD_DAYS 天，有止损止盈） ──
    returns = []
    closes  = close.values
    highs   = high.values
    lows    = low.values
    n       = len(closes)
    for i in range(n):
        if i + HOLD_DAYS >= n:
            returns.append(np.nan)
            continue
        entry = closes[i]
        stop  = entry * (1 - STOP_PCT)
        take  = entry * (1 + TAKE_PCT)
        ret   = (closes[i + HOLD_DAYS] - entry) / entry  # 默认持满
        for j in range(1, HOLD_DAYS + 1):
            if lows[i + j] <= stop:
                ret = -STOP_PCT
                break
            if highs[i + j] >= take:
                ret = TAKE_PCT
                break
        returns.append(ret)
    df["sim_ret"] = returns
    return df


# ── 3. 向量化评分 ────────────────────────────────────────────────────────
def vectorize_score(df: pd.DataFrame) -> pd.Series:
    c = df["收盘"].astype(float)

    ma_score = np.where(
        (c > df["ma5"]) & (df["ma5"] > df["ma10"]) &
        (df["ma10"] > df["ma20"]) & (df["ma20"] > df["ma60"]), 3,
        np.where(
            (c > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma10"] > df["ma20"]), 2,
            np.where(c > df["ma20"], 1, 0)
        )
    )
    cross      = (df["macd"].shift(1) < df["sig"].shift(1)) & (df["macd"] > df["sig"])
    expanding  = (df["macd"] > df["sig"]) & (df["hist"] > df["hist"].shift(1)) & (df["hist"] > 0)
    above      = df["macd"] > df["sig"]
    macd_score = np.where(cross, 2, np.where(expanding, 2, np.where(above, 1, 0)))

    rsi = df["rsi"]
    rsi_score = np.where(
        (rsi >= 45) & (rsi <= 65), 2,
        np.where((rsi >= 35) & (rsi < 45), 1,
                 np.where((rsi > 65) & (rsi <= 75), 1, 0))
    )
    vr_score  = np.where(df["vr"] >= 2.0, 2, np.where(df["vr"] >= 1.4, 1, 0))
    up5       = (c.pct_change() > 0).rolling(5).sum()
    mom_score = np.where(up5 >= 3, 1, 0)

    return (pd.Series(ma_score,   index=df.index)
          + pd.Series(macd_score, index=df.index)
          + pd.Series(rsi_score,  index=df.index)
          + pd.Series(vr_score,   index=df.index)
          + pd.Series(mom_score,  index=df.index))


# ── 4. 单股回测 ──────────────────────────────────────────────────────────
def backtest_stock(code, name, total_days, market_filter):
    try:
        end   = datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=total_days)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date=start, end_date=end, adjust="qfq")
        if df.empty:
            df = ak.fund_etf_hist_em(symbol=code, period="daily",
                                     start_date=start, end_date=end, adjust="qfq")
        if df.empty or len(df) < WARMUP_DAYS + HOLD_DAYS + 5:
            return pd.DataFrame()

        df["日期"] = pd.to_datetime(df["日期"])
        df = df.set_index("日期").sort_index()
        df = add_indicators(df)
        df["score"] = vectorize_score(df)

        # 预热期后的数据（留 HOLD_DAYS 不计入，无次日数据）
        result = df.iloc[WARMUP_DAYS: -HOLD_DAYS].copy()
        result = result[result["score"] >= SCORE_THRESH].dropna(subset=["sim_ret"])

        # ── 改进1：大盘趋势过滤 ──
        if market_filter is not None:
            valid_dates = market_filter[market_filter].index
            result = result[result.index.isin(valid_dates)]

        if result.empty:
            return pd.DataFrame()

        result["code"] = code
        result["name"] = name
        cols = ["code", "name", "收盘", "score", "sim_ret"]
        return result[cols].reset_index()

    except Exception:
        return pd.DataFrame()


# ── 5. 主程序 ─────────────────────────────────────────────────────────────
def main():
    total_days = BACKTEST_YEARS * 365 + WARMUP_DAYS + 60

    print("=" * 65)
    print(f"  A股预测逻辑回测 v2  |  {BACKTEST_YEARS}年  |  "
          f"阈值≥{SCORE_THRESH}分  |  持仓{HOLD_DAYS}日  |  止损-{STOP_PCT*100:.0f}%/止盈+{TAKE_PCT*100:.0f}%")
    print("=" * 65)

    # 大盘过滤
    print("\n[1/4] 获取沪深300大盘趋势…")
    market_filter = get_market_filter(total_days)

    # 股票池
    print("\n[2/4] 获取沪深300成分股…")
    try:
        cons  = ak.index_stock_cons(symbol="000300")
        codes = cons["品种代码"].astype(str).str.zfill(6).tolist()
        names = cons["品种名称"].tolist()
        if len(codes) < 20:
            raise ValueError("成分股数量不足")
    except Exception:
        # 扩充备用池：沪深300核心80只
        fallback = [
            ("600519","贵州茅台"),("000858","五粮液"),("600036","招商银行"),
            ("601318","中国平安"),("000651","格力电器"),("600900","长江电力"),
            ("601988","中国银行"),("600276","恒瑞医药"),("000333","美的集团"),
            ("002415","海康威视"),("600887","伊利股份"),("601166","兴业银行"),
            ("000568","泸州老窖"),("002594","比亚迪"),("600031","三一重工"),
            ("601728","中国电信"),("000002","万科A"),("002714","牧原股份"),
            ("600309","万华化学"),("601601","中国太保"),("600030","中信证券"),
            ("000725","京东方A"),("002352","顺丰控股"),("600438","通威股份"),
            ("601888","中国中免"),("000001","平安银行"),("600009","上海机场"),
            ("601328","交通银行"),("601398","工商银行"),("601288","农业银行"),
            ("601857","中国石油"),("600028","中国石化"),("601006","大秦铁路"),
            ("600048","保利发展"),("601390","中国中铁"),("601186","中国铁建"),
            ("000100","TCL科技"),("600886","国投电力"),("601985","中国核电"),
            ("600025","华能水电"),("601618","中国中冶"),("601898","中煤能源"),
            ("002466","天齐锂业"),("688223","晶科能源"),("300274","阳光电源"),
            ("601021","春秋航空"),("600760","中航沈飞"),("002252","上海莱士"),
            ("601995","中金公司"),("300866","戎美股份"),("601901","方正证券"),
            ("000776","广发证券"),("000538","云南白药"),("600023","浙能电力"),
            ("600026","中远海能"),("601878","浙商证券"),("601229","上海银行"),
            ("600161","天坛生物"),("600010","包钢股份"),("002709","天赐材料"),
            ("000425","徐工机械"),("600346","吉林化纤"),("600588","用友网络"),
            ("601336","新华保险"),("600522","中天科技"),("600918","中泰证券"),
            ("601360","三六零"),("300896","爱美客"),("300832","新兴装备"),
            ("601916","浙商银行"),("600029","南方航空"),("605117","德业股份"),
            ("601618","中国中冶"),("600219","南山铝业"),("688012","中微公司"),
            ("002920","德赛西威"),("000661","长春高新"),("300394","天孚通信"),
            ("000975","银泰黄金"),("600919","江苏银行"),("000792","盐湖股份"),
            ("601319","中国人保"),("300502","新易盛"),("601985","中国核电"),
        ]
        codes = [c for c, _ in fallback]
        names = [n for _, n in fallback]
        print(f"  (备用池 {len(codes)} 只)")

    np.random.seed(42)
    idx   = np.random.choice(len(codes), min(UNIVERSE_SIZE, len(codes)), replace=False)
    codes = [codes[i] for i in idx]
    names = [names[i] for i in idx]
    print(f"  股票池: {len(codes)} 只")

    # 并发回测
    print(f"\n[3/4] 数据拉取 + 技术评分（{MAX_WORKERS}线程并发）…")
    all_signals, done = [], [0]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(backtest_stock, c, n, total_days, market_filter): c
                for c, n in zip(codes, names)}
        for fut in as_completed(futs):
            done[0] += 1
            df = fut.result()
            bar = "█" * int(done[0] / len(codes) * 30)
            n   = len(df) if not df.empty else 0
            print(f"\r  [{bar:<30}] {done[0]}/{len(codes)}  信号: {n}",
                  end="", flush=True)
            if not df.empty:
                all_signals.append(df)

    print()
    if not all_signals:
        print("  ❌ 无信号"); return

    signals = pd.concat(all_signals, ignore_index=True)
    signals.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    # ── 统计 ──────────────────────────────────────────────────────────
    print(f"\n[4/4] 统计分析…\n")
    signals["is_up"]   = signals["sim_ret"] > 0
    signals["ret_pct"] = signals["sim_ret"] * 100

    wr  = signals["is_up"].mean() * 100
    avg = signals["ret_pct"].mean()
    med = signals["ret_pct"].median()
    n   = len(signals)

    print(f"  总信号数    : {n:,}")
    print(f"  整体胜率    : {wr:.1f}%")
    print(f"  平均模拟收益 : {avg:+.2f}%  (止损{STOP_PCT*100:.0f}%/止盈{TAKE_PCT*100:.0f}%，持{HOLD_DAYS}日)")
    print(f"  中位模拟收益 : {med:+.2f}%")

    # 止损/止盈触达统计
    stop_hit = (signals["ret_pct"] <= -STOP_PCT * 100 + 0.01).sum()
    take_hit = (signals["ret_pct"] >= TAKE_PCT * 100 - 0.01).sum()
    print(f"  止损触达    : {stop_hit:,} 次 ({stop_hit/n*100:.1f}%)")
    print(f"  止盈触达    : {take_hit:,} 次 ({take_hit/n*100:.1f}%)")
    print()

    print(f"  {'评分':<6} {'信号数':>7} {'胜率':>8} {'均收益':>10} {'中位收益':>10}")
    print("  " + "-" * 48)
    score_stats = []
    for s in sorted(signals["score"].unique()):
        sub = signals[signals["score"] == s]
        w   = sub["is_up"].mean() * 100
        a   = sub["ret_pct"].mean()
        m   = sub["ret_pct"].median()
        nn  = len(sub)
        print(f"  {s}分    {nn:>7,}   {w:>7.1f}%   {a:>+8.2f}%   {m:>+8.2f}%")
        score_stats.append({"score": s, "n": nn, "wr": w, "avg": a, "med": m})
    print()

    # ── 可视化 ─────────────────────────────────────────────────────────
    print(f"  绘制报告图…")
    score_df = pd.DataFrame(score_stats)
    fig = plt.Figure(figsize=(18, 11), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.48, wspace=0.35)

    def style(ax, title):
        ax.set_facecolor(BG)
        for sp in ax.spines.values(): sp.set_color("#333355")
        ax.tick_params(colors="gray", labelsize=9)
        ax.set_title(title, color="white", fontsize=11, pad=8)

    # 1. 胜率 by 评分
    ax1 = fig.add_subplot(gs[0, 0])
    style(ax1, "各评分段胜率")
    colors = ["#4CAF50" if w >= 50 else "#FF6B6B" for w in score_df["wr"]]
    bars = ax1.bar(score_df["score"].astype(str) + "分", score_df["wr"],
                   color=colors, alpha=0.85)
    ax1.axhline(50, color="gray", linewidth=0.8, linestyle="--")
    ax1.set_ylim(25, 80); ax1.set_ylabel("胜率 (%)", color="gray", fontsize=9)
    for bar, val in zip(bars, score_df["wr"]):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                 f"{val:.1f}%", ha="center", fontsize=9,
                 color="#4CAF50" if val >= 50 else "#FF6B6B")

    # 2. 均收益 by 评分
    ax2 = fig.add_subplot(gs[0, 1])
    style(ax2, "各评分段平均收益（含止损止盈）")
    colors2 = ["#4CAF50" if v >= 0 else "#FF6B6B" for v in score_df["avg"]]
    bars2 = ax2.bar(score_df["score"].astype(str) + "分", score_df["avg"],
                    color=colors2, alpha=0.85)
    ax2.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax2.set_ylabel("平均收益 (%)", color="gray", fontsize=9)
    for bar, val in zip(bars2, score_df["avg"]):
        ax2.text(bar.get_x() + bar.get_width()/2,
                 bar.get_height() + (0.05 if val >= 0 else -0.2),
                 f"{val:+.2f}%", ha="center", fontsize=9,
                 color="#4CAF50" if val >= 0 else "#FF6B6B")

    # 3. 信号数量
    ax3 = fig.add_subplot(gs[0, 2])
    style(ax3, "各评分段信号数量（大盘过滤后）")
    ax3.bar(score_df["score"].astype(str) + "分", score_df["n"],
            color="#4D96FF", alpha=0.8)
    ax3.set_ylabel("信号条数", color="gray", fontsize=9)
    for i, row in score_df.iterrows():
        ax3.text(i, row["n"] + 2, str(int(row["n"])),
                 ha="center", fontsize=9, color="white")

    # 4. 收益分布
    ax4 = fig.add_subplot(gs[1, 0])
    style(ax4, f"模拟收益分布（持{HOLD_DAYS}日，止损{STOP_PCT*100:.0f}%/止盈{TAKE_PCT*100:.0f}%）")
    ret = signals["ret_pct"]
    ax4.hist(ret[ret > -STOP_PCT*100], bins=40, color="#4CAF50", alpha=0.7, label="盈利/未触损")
    ax4.hist(ret[ret <= -STOP_PCT*100+0.01], bins=5, color="#FF6B6B", alpha=0.8, label="触发止损")
    ax4.axvline(TAKE_PCT*100, color="#FFD93D", linewidth=1.2, linestyle="--",
                label=f"止盈线 +{TAKE_PCT*100:.0f}%")
    ax4.axvline(ret.mean(), color="cyan", linewidth=1.0,
                linestyle=":", label=f"均值 {ret.mean():+.2f}%")
    ax4.set_xlabel("收益率 (%)", color="gray", fontsize=9)
    ax4.set_ylabel("频次", color="gray", fontsize=9)
    ax4.legend(fontsize=7, facecolor=BG, labelcolor="white", framealpha=0.5)

    # 5. 月度胜率
    ax5 = fig.add_subplot(gs[1, 1])
    style(ax5, "月度胜率趋势（大盘过滤后）")
    signals["ym"] = signals["日期"].dt.to_period("M")
    monthly = signals.groupby("ym").agg(wr=("is_up","mean"), n=("is_up","count"))
    monthly = monthly[monthly["n"] >= 5]
    ym_str  = monthly.index.astype(str)
    wr_vals = monthly["wr"] * 100
    colors_m = ["#4CAF50" if v >= 50 else "#FF6B6B" for v in wr_vals]
    ax5.bar(range(len(ym_str)), wr_vals, color=colors_m, alpha=0.8)
    ax5.axhline(50, color="gray", linewidth=0.8, linestyle="--")
    ax5.set_ylabel("胜率 (%)", color="gray", fontsize=9)
    step = max(1, len(ym_str) // 8)
    ax5.set_xticks(range(0, len(ym_str), step))
    ax5.set_xticklabels(list(ym_str)[::step], rotation=30, ha="right", fontsize=7)
    ax5.set_ylim(20, 85)

    # 6. 累计收益曲线（等权持每信号）
    ax6 = fig.add_subplot(gs[1, 2])
    style(ax6, "等权累计收益曲线")
    sorted_sigs = signals.sort_values("日期")
    cum = (1 + sorted_sigs["sim_ret"]).cumprod() - 1
    ax6.plot(range(len(cum)), cum * 100, color="#4D96FF", linewidth=1.0)
    ax6.axhline(0, color="gray", linewidth=0.6, linestyle="--")
    ax6.fill_between(range(len(cum)), cum*100, 0,
                     where=(cum >= 0), alpha=0.12, color="#4CAF50")
    ax6.fill_between(range(len(cum)), cum*100, 0,
                     where=(cum < 0),  alpha=0.12, color="#FF6B6B")
    ax6.set_ylabel("累计收益 (%)", color="gray", fontsize=9)
    ax6.set_xlabel("信号序号", color="gray", fontsize=9)
    final = cum.iloc[-1] * 100
    ax6.text(0.97, 0.05, f"终值: {final:+.1f}%",
             transform=ax6.transAxes, ha="right", fontsize=11,
             color="#4CAF50" if final >= 0 else "#FF6B6B")

    # 添加大盘过滤说明
    mf_note = "✓ 已启用大盘趋势过滤（沪深300 MA5>MA20）" if market_filter is not None \
              else "✗ 大盘过滤未启用"
    fig.suptitle(
        f"回测报告 v2  |  {BACKTEST_YEARS}年  |  {len(codes)}只股票  |  "
        f"{n:,}条信号  |  胜率 {wr:.1f}%  |  均收益 {avg:+.2f}%\n"
        f"{mf_note}  |  持仓{HOLD_DAYS}日  |  止损{STOP_PCT*100:.0f}% / 止盈{TAKE_PCT*100:.0f}%（3:1盈亏比）",
        color="white", fontsize=12, y=0.99)

    fig.savefig(OUTPUT_PNG, dpi=120, bbox_inches="tight", facecolor=BG)
    print(f"  已保存: {OUTPUT_PNG}")

    import subprocess
    subprocess.Popen(["open", OUTPUT_PNG])
    print(f"\n  ✅ 回测 v2 完成！明细: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
