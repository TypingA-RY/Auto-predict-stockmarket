"""
gui/predict_page.py — 次日强势股预测（v4）

新增：
  - 胜率 / 预期收益列（个股历史回测）
  - 信息面分析面板（点击行 → 异步加载近期新闻）
"""
import tkinter as tk
import customtkinter as ctk
import pandas as pd
import numpy as np
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import webbrowser

import akshare as ak
from core.data import get_stock_hist

BG     = "#1a1a2e"
GREEN  = "#4CAF50"
RED    = "#FF6B6B"
YELLOW = "#FFD93D"
BLUE   = "#4D96FF"
GRAY   = "gray"

STOP_PCT = 0.10
TAKE_PCT = 0.20
HOLD_DAYS = 3

# 蓝筹备用池（沪深300核心成分）
BLUECHIP_POOL = [
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
]

COLS   = ["排名", "代码",  "名称",  "现价",  "D-1",  "D-2",  "D-3",  "评分",
          "胜率",  "预期收益", "止损价", "止盈价", "盈亏比", "所属板块", "触发信号"]
WIDTHS = [40,     75,      95,     75,     60,     60,     60,     55,
          60,     75,      75,     75,     55,     100,    280]


class PredictPage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._selected_code = None
        self._build()

    # ── UI ──────────────────────────────────────────────────────────────
    def _build(self):
        ctrl = ctk.CTkFrame(self, height=50, fg_color=("gray20", "gray15"))
        ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctrl.pack_propagate(False)

        ctk.CTkLabel(ctrl, text="次日强势股预测",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=BLUE).pack(side="left", padx=(12, 12))

        ctk.CTkLabel(ctrl, text="策略:").pack(side="left", padx=(0, 4))
        self.strategy_var = tk.StringVar(value="追势")
        ctk.CTkOptionMenu(ctrl, variable=self.strategy_var,
                          values=["追势", "蓝筹过滤超涨", "均值回归", "板块轮动"],
                          width=120,
                          command=self._on_strategy).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="候选池:").pack(side="left", padx=(8, 4))
        self.pool_var = tk.StringVar(value="热门榜+蓝筹")
        ctk.CTkOptionMenu(ctrl, variable=self.pool_var,
                          values=["热门榜+蓝筹", "仅热门榜", "仅蓝筹"],
                          width=130).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="最低评分:").pack(side="left", padx=(8, 4))
        self.score_var = tk.StringVar(value="7")
        ctk.CTkOptionMenu(ctrl, variable=self.score_var,
                          values=["5", "6", "7", "8", "9", "10"],
                          width=60).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="数据年数:").pack(side="left", padx=(12, 4))
        self.years_var = tk.StringVar(value="1")
        ctk.CTkOptionMenu(ctrl, variable=self.years_var,
                          values=["1", "2", "3"],
                          width=60).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="大盘基准:").pack(side="left", padx=(12, 4))
        self.index_var = tk.StringVar(value="沪深300")
        ctk.CTkOptionMenu(ctrl, variable=self.index_var,
                          values=["沪深300", "上证指数", "深证成指", "创业板指", "中证500", "中证1000"],
                          width=100).pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="开始预测", width=90,
                      command=self._start).pack(side="left", padx=12)

        self.market_label = ctk.CTkLabel(ctrl, text="大盘: —",
                                         text_color=GRAY,
                                         font=ctk.CTkFont(size=11))
        self.market_label.pack(side="left", padx=(4, 12))

        self.status = ctk.CTkLabel(ctrl, text="点击「开始预测」开始筛选",
                                   text_color=GRAY)
        self.status.pack(side="left", padx=4)

        self.progress = ctk.CTkProgressBar(ctrl, width=180)
        self.progress.set(0)

        # 主内容区：上方表格 + 下方新闻面板
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=10)
        main.rowconfigure(0, weight=3)
        main.rowconfigure(1, weight=2)
        main.columnconfigure(0, weight=1)

        self.content = ctk.CTkFrame(main, fg_color=("gray18", "gray12"))
        self.content.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        ctk.CTkLabel(self.content,
                     text="基于均线趋势 · MACD · RSI · 量能突破 · 大盘环境多因子评分",
                     font=ctk.CTkFont(size=15), text_color="gray50").place(
            relx=0.5, rely=0.5, anchor="center")

        # 信息面板
        news_outer = ctk.CTkFrame(main, fg_color=("gray18", "gray12"))
        news_outer.grid(row=1, column=0, sticky="nsew")

        news_hdr = ctk.CTkFrame(news_outer, fg_color=("gray22", "gray18"), height=32)
        news_hdr.pack(fill="x")
        news_hdr.pack_propagate(False)
        self.news_title = ctk.CTkLabel(
            news_hdr, text="📰 信息面分析  （点击上方股票行加载新闻）",
            text_color="gray", font=ctk.CTkFont(size=11))
        self.news_title.pack(side="left", padx=12, pady=6)

        self.news_scroll = ctk.CTkScrollableFrame(news_outer, fg_color="transparent")
        self.news_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        ctk.CTkLabel(self.news_scroll, text="点击上方股票查看最新资讯",
                     text_color="gray50").pack(pady=20)

    # 指数名称 → AkShare symbol 映射
    _INDEX_MAP = {
        "沪深300":  "sh000300",
        "上证指数":  "sh000001",
        "深证成指":  "sz399001",
        "创业板指":  "sz399006",
        "中证500":  "sh000905",
        "中证1000": "sh000852",
    }

    def _on_strategy(self, strategy):
        """切换策略时自动调整候选池和评分默认值"""
        defaults = {
            "追势":       ("热门榜+蓝筹", "7"),
            "蓝筹过滤超涨": ("仅蓝筹",      "6"),
            "均值回归":    ("热门榜+蓝筹", "5"),
            "板块轮动":    ("热门榜+蓝筹", "6"),
        }
        pool, score = defaults.get(strategy, ("热门榜+蓝筹", "7"))
        self.pool_var.set(pool)
        self.score_var.set(score)

    # ── 大盘趋势 ─────────────────────────────────────────────────────────
    def _get_market_trend(self):
        index_name = self.index_var.get()
        symbol     = self._INDEX_MAP.get(index_name, "sh000300")
        try:
            df    = ak.stock_zh_index_daily(symbol=symbol)
            df["date"] = pd.to_datetime(df["date"])
            df    = df.set_index("date").sort_index().tail(120)
            close = df["close"].astype(float)
            ma5   = close.rolling(5).mean().iloc[-1]
            ma20  = close.rolling(20).mean().iloc[-1]
            cur   = close.iloc[-1]
            chg   = (cur - close.iloc[-2]) / close.iloc[-2] * 100
            uptrend = (cur > ma20) and (ma5 > ma20)
            desc  = (f"{index_name} {cur:.0f}  {chg:+.2f}%  "
                     f"{'✅ 上升趋势' if uptrend else '⚠️ 弱势行情'}")
            return uptrend, desc
        except Exception:
            return True, "大盘数据暂不可用，不过滤"

    # ── 候选池 ───────────────────────────────────────────────────────────
    def _get_candidates(self, pool: str):
        candidates = []
        if pool in ("热门榜+蓝筹", "仅热门榜"):
            try:
                df = ak.stock_hot_rank_em()
                df["code"] = df["代码"].str.replace(r"^(SH|SZ)", "", regex=True)
                for _, row in df.iterrows():
                    candidates.append((row["code"], row["股票名称"]))
            except Exception as e:
                self._set_prog(f"热门榜获取失败: {e}，使用蓝筹池", 0.1)

        if pool in ("热门榜+蓝筹", "仅蓝筹"):
            existing = {c for c, _ in candidates}
            for code, name in BLUECHIP_POOL:
                if code not in existing:
                    candidates.append((code, name))

        return candidates

    # ── 主流程 ───────────────────────────────────────────────────────────
    def _start(self):
        self.progress.set(0)
        self.progress.pack(side="left", padx=8)
        self.status.configure(text="检查大盘趋势…", text_color=YELLOW)
        threading.Thread(target=self._run, daemon=True).start()

    def _set_prog(self, text, val):
        self.after(0, lambda: self.status.configure(text=text, text_color=GRAY))
        self.after(0, lambda: self.progress.set(val))

    def _run(self):
        try:
            uptrend, market_desc = self._get_market_trend()
            mc = GREEN if uptrend else YELLOW
            self.after(0, lambda: self.market_label.configure(
                text=market_desc, text_color=mc))

            self._set_prog("获取候选股列表…", 0.08)
            pool      = self.pool_var.get()
            min_score = int(self.score_var.get())
            hist_days = int(self.years_var.get()) * 365
            strategy  = self.strategy_var.get()
            candidates = self._get_candidates(pool)

            # 板块轮动：预先获取行业涨跌幅字典
            sector_perf = {}
            if strategy == "板块轮动":
                self._set_prog("获取板块行情…", 0.12)
                try:
                    sdf = ak.stock_board_industry_name_em()
                    chg_col  = next((c for c in sdf.columns if "涨跌幅" in str(c)), None)
                    name_col = next((c for c in sdf.columns if "名称" in str(c)), sdf.columns[1])
                    if chg_col:
                        sdf[chg_col] = pd.to_numeric(sdf[chg_col], errors="coerce").fillna(0)
                        sector_perf = dict(zip(sdf[name_col], sdf[chg_col]))
                except Exception:
                    pass

            self._set_prog(f"共 {len(candidates)} 只候选股，策略「{strategy}」开始分析…", 0.15)

            results = []
            done    = [0]

            def analyze(code, name):
                res = self._score_stock(code, name, uptrend, min_score, hist_days,
                                        strategy=strategy, sector_perf=sector_perf)
                done[0] += 1
                self._set_prog(
                    f"技术分析 {done[0]}/{len(candidates)}…",
                    0.15 + 0.8 * done[0] / len(candidates))
                return res

            with ThreadPoolExecutor(max_workers=8) as ex:
                futs = [ex.submit(analyze, c, n) for c, n in candidates]
                for fut in as_completed(futs):
                    res = fut.result()
                    if res:
                        results.append(res)

            results.sort(key=lambda x: x["score"], reverse=True)
            top10 = results[:10]
            self.after(0, lambda: self._render(top10, uptrend))

        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"错误: {e}", text_color=RED))
            self.after(0, lambda: self.progress.pack_forget())

    # ── 个股历史胜率 ─────────────────────────────────────────────────────
    @staticmethod
    def _calc_winrate(df):
        """
        简化历史回测：以「收盘>MA5>MA20 且量比≥1.4」为信号，
        模拟3日持仓（-10%止损/+20%止盈），返回 (win_rate, avg_return)
        """
        try:
            close  = df["收盘"].astype(float).values
            high   = df["最高"].astype(float).values if "最高" in df.columns else close
            low    = df["最低"].astype(float).values if "最低" in df.columns else close
            volume = df["成交量"].astype(float).values
            n = len(close)
            if n < 60:
                return None, None

            ma5_arr  = pd.Series(close).rolling(5).mean().values
            ma20_arr = pd.Series(close).rolling(20).mean().values
            vol_m20  = pd.Series(volume).rolling(20).mean().values

            returns = []
            for i in range(40, n - HOLD_DAYS - 1):
                if not (close[i] > ma5_arr[i] > ma20_arr[i]):
                    continue
                if vol_m20[i] <= 0 or volume[i] / vol_m20[i] < 1.4:
                    continue
                entry = close[i]
                stop  = entry * (1 - STOP_PCT)
                take  = entry * (1 + TAKE_PCT)
                ret   = (close[min(i + HOLD_DAYS, n - 1)] - entry) / entry
                for j in range(i + 1, min(i + HOLD_DAYS + 1, n)):
                    if low[j] <= stop:
                        ret = -STOP_PCT; break
                    if high[j] >= take:
                        ret = TAKE_PCT;  break
                returns.append(ret)

            if len(returns) < 5:
                return None, None
            win_rate   = sum(1 for r in returns if r > 0) / len(returns)
            avg_return = sum(returns) / len(returns)
            return win_rate, avg_return
        except Exception:
            return None, None

    # ── 单股评分 ─────────────────────────────────────────────────────────
    def _score_stock(self, code, name, market_uptrend, min_score=7, hist_days=365,
                     strategy="追势", sector_perf=None):
        try:
            df = get_stock_hist(code, days=max(hist_days, 90))
            if len(df) < 30:
                return None

            close  = df["收盘"].astype(float)
            volume = df["成交量"].astype(float)
            cur    = close.iloc[-1]

            ma5  = close.rolling(5).mean()
            ma10 = close.rolling(10).mean()
            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(min(60, len(close))).mean()

            ema12  = close.ewm(span=12, adjust=False).mean()
            ema26  = close.ewm(span=26, adjust=False).mean()
            macd   = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            hist   = macd - signal

            delta  = close.diff()
            gain   = delta.clip(lower=0).rolling(14).mean()
            loss   = (-delta.clip(upper=0)).rolling(14).mean()
            rsi    = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).iloc[-1]

            vol_ma20 = volume.rolling(20).mean().iloc[-1]
            vr       = volume.iloc[-1] / vol_ma20 if vol_ma20 > 0 else 1
            m5, m10, m20, m60 = ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1], ma60.iloc[-1]

            score   = 0
            reasons = []

            # ── 策略 A: 追势（原始逻辑） ─────────────────────────────────
            if strategy == "追势":
                if cur > m5 > m10 > m20 > m60:
                    score += 3; reasons.append("均线完全多头")
                elif cur > m5 > m10 > m20:
                    score += 2; reasons.append("均线多头排列")
                elif cur > m20:
                    score += 1; reasons.append("站上MA20")

                if macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1]:
                    score += 2; reasons.append("MACD金叉")
                elif macd.iloc[-1] > signal.iloc[-1] and hist.iloc[-1] > hist.iloc[-2] > 0:
                    score += 2; reasons.append("MACD红柱扩张")
                elif macd.iloc[-1] > signal.iloc[-1]:
                    score += 1; reasons.append("MACD多头")

                if 45 <= rsi <= 65:
                    score += 2; reasons.append(f"RSI健康 {rsi:.0f}")
                elif 35 <= rsi < 45:
                    score += 1; reasons.append(f"RSI回升 {rsi:.0f}")
                elif 65 < rsi <= 75:
                    score += 1; reasons.append(f"RSI强势 {rsi:.0f}")

                if vr >= 2.0:
                    score += 2; reasons.append(f"大幅放量 {vr:.1f}x")
                elif vr >= 1.4:
                    score += 1; reasons.append(f"温和放量 {vr:.1f}x")

                up_days = int((close.pct_change().iloc[-5:] > 0).sum())
                if up_days >= 3:
                    score += 1; reasons.append(f"近5日{up_days}涨")

            # ── 策略 B: 蓝筹过滤超涨 ────────────────────────────────────
            elif strategy == "蓝筹过滤超涨":
                # 过滤已飞涨的股票
                gain_5d = (cur - close.iloc[-6]) / close.iloc[-6] * 100 if len(close) > 5 else 0
                if gain_5d > 15:
                    return None
                if rsi > 72:
                    return None

                if cur > m5 > m10 > m20 > m60:
                    score += 3; reasons.append("均线完全多头")
                elif cur > m5 > m10 > m20:
                    score += 2; reasons.append("均线多头排列")
                elif cur > m20:
                    score += 1; reasons.append("站上MA20")

                if macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1]:
                    score += 2; reasons.append("MACD金叉")
                elif macd.iloc[-1] > signal.iloc[-1] and hist.iloc[-1] > hist.iloc[-2] > 0:
                    score += 2; reasons.append("MACD红柱扩张")
                elif macd.iloc[-1] > signal.iloc[-1]:
                    score += 1; reasons.append("MACD多头")

                # RSI 上限更严格，不奖励强势区
                if 45 <= rsi <= 62:
                    score += 2; reasons.append(f"RSI健康 {rsi:.0f}")
                elif 35 <= rsi < 45:
                    score += 1; reasons.append(f"RSI回升 {rsi:.0f}")

                # 量能：偏好适度放量，不追极端
                if 1.4 <= vr < 3.0:
                    score += 2; reasons.append(f"适度放量 {vr:.1f}x")
                elif vr >= 3.0:
                    score += 1; reasons.append(f"放量(偏高) {vr:.1f}x")

                up_days = int((close.pct_change().iloc[-5:] > 0).sum())
                if up_days >= 3:
                    score += 1; reasons.append(f"近5日{up_days}涨")

                reasons.append(f"5日涨幅 {gain_5d:+.1f}%")

            # ── 策略 C: 均值回归 ─────────────────────────────────────────
            elif strategy == "均值回归":
                # 要求中期趋势完好
                if m20 <= m60:
                    return None  # 中期下跌，不做回归

                # 短期回调幅度判断
                pullback = (cur - m20) / m20 * 100  # 负值 = 在MA20下方
                if -8 <= pullback <= -1:
                    score += 3; reasons.append(f"健康回调 {pullback:.1f}%")
                elif -15 <= pullback < -8:
                    score += 2; reasons.append(f"深度回调 {pullback:.1f}%")
                elif 0 < pullback <= 3:
                    score += 1; reasons.append("刚回到MA20上方")
                else:
                    return None  # 离MA20太远（过远超涨或深度下跌）

                # RSI 超卖回升 — 核心信号
                if 32 <= rsi <= 48:
                    score += 3; reasons.append(f"RSI超卖回升 {rsi:.0f}")
                elif 48 < rsi <= 55:
                    score += 2; reasons.append(f"RSI中性偏低 {rsi:.0f}")
                elif rsi < 32:
                    score += 1; reasons.append(f"RSI极度超卖 {rsi:.0f}")
                else:
                    return None  # RSI 已过高，回归机会消失

                # MACD 底部反转信号
                if macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1]:
                    score += 2; reasons.append("MACD金叉（底部）")
                elif macd.iloc[-1] < 0 and hist.iloc[-1] > hist.iloc[-2]:
                    score += 2; reasons.append("MACD零轴下方反弹")
                elif hist.iloc[-1] > hist.iloc[-2] > hist.iloc[-3]:
                    score += 1; reasons.append("MACD柱连续缩空")

                # 量能萎缩（回调健康的标志）
                if vr < 0.8:
                    score += 1; reasons.append(f"缩量回调 {vr:.1f}x")

                # 近期触底反弹形态（先跌后涨）
                pct5 = close.pct_change().iloc[-5:].values
                if len(pct5) >= 3 and pct5[-1] > 0 and pct5[-2] > 0 and pct5[-3] < 0:
                    score += 1; reasons.append("止跌反弹形态")

            # ── 策略 D: 板块轮动 ─────────────────────────────────────────
            elif strategy == "板块轮动":
                # 先获取该股所属板块的近期涨幅
                try:
                    info_df  = ak.stock_individual_info_em(stock=code)
                    info_map = dict(zip(info_df.iloc[:, 0], info_df.iloc[:, 1]))
                    stk_sector = str(info_map.get("行业", ""))
                except Exception:
                    stk_sector = ""

                s_chg = sector_perf.get(stk_sector, None) if sector_perf else None
                if s_chg is not None:
                    if s_chg > 8:
                        return None  # 板块已经大涨，追高风险高
                    elif s_chg < 2:
                        score += 2; reasons.append(f"冷门板块待启动 {s_chg:+.1f}%")
                    elif 2 <= s_chg <= 5:
                        score += 1; reasons.append(f"板块温和上行 {s_chg:+.1f}%")

                # 个股本身要有基本的多头结构
                if cur > m10 > m20:
                    score += 2; reasons.append("均线多头")
                elif cur > m20:
                    score += 1; reasons.append("站上MA20")
                else:
                    return None  # 个股本身趋势不行

                if macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1]:
                    score += 2; reasons.append("MACD金叉")
                elif macd.iloc[-1] > signal.iloc[-1]:
                    score += 1; reasons.append("MACD多头")

                if 40 <= rsi <= 65:
                    score += 2; reasons.append(f"RSI适中 {rsi:.0f}")
                elif rsi > 65:
                    return None  # 个股已超买

                if 1.2 <= vr <= 3.0:
                    score += 1; reasons.append(f"量能配合 {vr:.1f}x")

                up_days = int((close.pct_change().iloc[-5:] > 0).sum())
                if up_days >= 2:
                    score += 1; reasons.append(f"近5日{up_days}涨")

            threshold = min_score if market_uptrend else min(min_score + 1, 10)
            if score < threshold:
                return None

            stop_loss = round(max(m20 * 0.99, cur * (1 - STOP_PCT)), 2)
            rr_risk   = cur - stop_loss
            if rr_risk <= 0:
                stop_loss = round(cur * (1 - STOP_PCT), 2)
                rr_risk   = cur - stop_loss
            take_profit = round(cur + 3 * rr_risk, 2)

            if not market_uptrend:
                take_profit = round(cur * 1.05, 2)
                reasons.append("⚠️弱市保守")

            rr = round((take_profit - cur) / rr_risk, 1) if rr_risk > 0 else 0

            # 历史胜率
            win_rate, avg_ret = self._calc_winrate(df)

            # 近3个交易日涨跌幅
            pct = close.pct_change() * 100
            chg3 = [round(pct.iloc[-i], 2) if len(pct) >= i else None for i in range(1, 4)]

            # 所属板块
            try:
                info_df = ak.stock_individual_info_em(stock=code)
                info    = dict(zip(info_df.iloc[:, 0], info_df.iloc[:, 1]))
                sector  = str(info.get("行业", "—"))
            except Exception:
                sector = "—"

            return {
                "code":        code,
                "name":        name,
                "price":       cur,
                "score":       score,
                "chg3":        chg3,
                "sector":      sector,
                "win_rate":    win_rate,
                "exp_return":  avg_ret,
                "stop_loss":   stop_loss,
                "take_profit": take_profit,
                "rr":          rr,
                "reasons":     "；".join(reasons),
            }
        except Exception:
            return None

    # ── 渲染表格 ─────────────────────────────────────────────────────────
    def _render(self, top10, market_uptrend):
        for w in self.content.winfo_children():
            w.destroy()

        self.progress.pack_forget()
        self.status.configure(text=f"筛选完成，推荐 {len(top10)} 只", text_color=GREEN)

        if not top10:
            msg = "暂无符合条件的股票" + ("（弱市门槛已提至6分）" if not market_uptrend else "")
            ctk.CTkLabel(self.content, text=msg,
                         text_color="gray50").place(relx=0.5, rely=0.5, anchor="center")
            return

        ctk.CTkLabel(
            self.content,
            text=(f"⚠️ 仅技术指标参考，不构成投资建议   "
                  f"止损 -{STOP_PCT*100:.0f}%   止盈 +{TAKE_PCT*100:.0f}%   建议持仓 {HOLD_DAYS}日内"),
            text_color=YELLOW, font=ctk.CTkFont(size=11)
        ).pack(pady=(8, 2))

        hdr, scroll = self._build_scroll_table(self.content)
        for rank, item in enumerate(top10, 1):
            self._add_row(scroll, rank, item)

    # ── 可横向滚动的表格容器 ──────────────────────────────────────────────
    def _build_scroll_table(self, parent):
        """返回 (header_frame, rows_scrollable_frame)，支持横向+纵向滚动"""
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=10, pady=(4, 8))

        # 横向滚动条（底部）
        hbar = tk.Scrollbar(outer, orient="horizontal")
        hbar.pack(side="bottom", fill="x")

        # Canvas 负责横向平移
        canvas = tk.Canvas(outer, bg="#1f1f2e", highlightthickness=0,
                           xscrollcommand=hbar.set)
        canvas.pack(fill="both", expand=True)
        hbar.config(command=canvas.xview)

        # 内部大框架（随内容宽度自动展开）
        inner = ctk.CTkFrame(canvas, fg_color="transparent")
        win   = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(e=None):
            rw = inner.winfo_reqwidth()
            rh = inner.winfo_reqheight()
            canvas.configure(scrollregion=(0, 0, rw, rh))
            canvas.itemconfig(win, height=max(canvas.winfo_height(), rh))

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", lambda e: (
            canvas.itemconfig(win, height=e.height),
            canvas.configure(scrollregion=(0, 0,
                                           inner.winfo_reqwidth(),
                                           max(e.height, inner.winfo_reqheight())))
        ))

        # Shift+滚轮 → 横向；普通滚轮 → 纵向（由内部 CTkScrollableFrame 处理）
        canvas.bind("<MouseWheel>", lambda e: (
            canvas.xview_scroll(int(-1 * (e.delta / 120)), "units")
            if (e.state & 0x1) else None
        ))

        # 表头
        hdr = ctk.CTkFrame(inner, fg_color=("gray25", "gray20"), corner_radius=4)
        hdr.pack(fill="x", pady=(0, 1))
        for i, w in enumerate(WIDTHS):
            hdr.columnconfigure(i, weight=0, minsize=w)
        for i, col in enumerate(COLS):
            ctk.CTkLabel(hdr, text=col, text_color=GRAY,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         anchor="w").grid(row=0, column=i, padx=6, pady=5, sticky="w")

        # 行区域（纵向可滚动）
        rows = ctk.CTkScrollableFrame(inner, fg_color="transparent")
        rows.pack(fill="both", expand=True)
        for i, w in enumerate(WIDTHS):
            rows.columnconfigure(i, weight=0, minsize=w)

        return hdr, rows

    def _add_row(self, parent, rank, item):
        bg    = ("gray20", "gray16") if rank % 2 == 0 else ("gray18", "gray13")
        row_f = ctk.CTkFrame(parent, fg_color=bg, corner_radius=4, cursor="hand2")
        row_f.pack(fill="x", pady=2)
        for i, w in enumerate(WIDTHS):
            row_f.columnconfigure(i, weight=1 if w == 1 else 0, minsize=max(w, 10))

        s  = item["score"]
        sc = GREEN if s >= 7 else (YELLOW if s >= 5 else "white")
        rr = item["rr"]

        wr  = item.get("win_rate")
        er  = item.get("exp_return")
        wr_txt = f"{wr*100:.1f}%" if wr is not None else "—"
        er_txt = f"{er*100:+.2f}%" if er is not None else "—"
        wr_color = (GREEN if wr and wr >= 0.45 else
                    YELLOW if wr and wr >= 0.35 else
                    RED if wr else GRAY)
        er_color = GREEN if er and er > 0 else (RED if er and er < 0 else GRAY)

        def chg_fmt(v):
            if v is None: return "—", GRAY
            return f"{v:+.2f}%", (GREEN if v > 0 else RED if v < 0 else GRAY)

        c1, c1c = chg_fmt(item.get("chg3", [None, None, None])[0])
        c2, c2c = chg_fmt(item.get("chg3", [None, None, None])[1])
        c3, c3c = chg_fmt(item.get("chg3", [None, None, None])[2])

        cells = [
            (str(rank),                     "white"),
            (item["code"],                  BLUE),
            (item["name"],                  "white"),
            (f"¥{item['price']:.2f}",       "white"),
            (c1,                            c1c),
            (c2,                            c2c),
            (c3,                            c3c),
            (f"{s} 分",                     sc),
            (wr_txt,                        wr_color),
            (er_txt,                        er_color),
            (f"¥{item['stop_loss']:.2f}",   RED),
            (f"¥{item['take_profit']:.2f}", GREEN),
            (f"{rr}:1",                     GREEN if rr >= 2.5 else YELLOW),
            (item.get("sector", "—"),       YELLOW),
            (item["reasons"],               GRAY),
        ]
        for col, (text, color) in enumerate(cells):
            lbl = ctk.CTkLabel(row_f, text=text, text_color=color,
                               font=ctk.CTkFont(size=11), anchor="w")
            lbl.grid(row=0, column=col, padx=6, pady=7, sticky="w")
            lbl.bind("<Button-1>", lambda e, c=item["code"], n=item["name"]:
                     self._load_news(c, n))

        row_f.bind("<Button-1>", lambda e, c=item["code"], n=item["name"]:
                   self._load_news(c, n))

    # ── 信息面（新闻）面板 ───────────────────────────────────────────────
    def _load_news(self, code, name):
        self.news_title.configure(
            text=f"📰 {name}（{code}）最新资讯  加载中…", text_color=YELLOW)
        for w in self.news_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.news_scroll, text="正在获取新闻…",
                     text_color="gray60").pack(pady=20)
        threading.Thread(target=self._fetch_news, args=(code, name), daemon=True).start()

    def _fetch_news(self, code, name):
        try:
            df = ak.stock_news_em(symbol=code)
            self.after(0, lambda: self._render_news(df, code, name))
        except Exception as e:
            self.after(0, lambda: self._render_news(pd.DataFrame(), code, name,
                                                     error=str(e)))

    def _render_news(self, df, code, name, error=None):
        self.news_title.configure(
            text=f"📰 {name}（{code}）最新资讯", text_color="white")
        for w in self.news_scroll.winfo_children():
            w.destroy()

        if error:
            ctk.CTkLabel(self.news_scroll, text=f"新闻获取失败: {error}",
                         text_color=RED).pack(pady=10)
            return

        if df is None or df.empty:
            ctk.CTkLabel(self.news_scroll, text="暂无相关新闻",
                         text_color="gray60").pack(pady=20)
            return

        # 列名适配
        title_col   = next((c for c in df.columns if "标题" in str(c) or "title" in str(c).lower()), None)
        time_col    = next((c for c in df.columns if "时间" in str(c) or "date" in str(c).lower() or "发布" in str(c)), None)
        url_col     = next((c for c in df.columns if "链接" in str(c) or "url" in str(c).lower()), None)
        content_col = next((c for c in df.columns if "内容" in str(c) or "摘要" in str(c) or "content" in str(c).lower() or "summary" in str(c).lower()), None)

        shown = df.head(15)
        for _, row in shown.iterrows():
            title   = str(row[title_col])   if title_col   else str(row.iloc[0])
            ts      = str(row[time_col])[:16] if time_col  else ""
            url     = str(row[url_col])     if url_col     else None
            content = str(row[content_col]) if content_col else ""
            # 清理摘要：去掉与标题重复的开头、截断到合理长度
            if content and content not in ("nan", "None", ""):
                if content.startswith(title[:20]):
                    content = content[len(title):].lstrip("。，、 ")
                summary = content[:200] + ("…" if len(content) > 200 else "")
            else:
                summary = ""

            card = ctk.CTkFrame(self.news_scroll,
                                fg_color=("gray22", "gray17"), corner_radius=6)
            card.pack(fill="x", padx=4, pady=3)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=10, pady=(6, 2))

            if ts:
                ctk.CTkLabel(top_row, text=ts, text_color="gray60",
                             font=ctk.CTkFont(size=10)).pack(side="left")

            # 情绪标签（关键词匹配）
            sentiment, s_color = self._sentiment(title)
            if sentiment:
                ctk.CTkLabel(top_row, text=sentiment, text_color=s_color,
                             font=ctk.CTkFont(size=10),
                             fg_color=(s_color.replace("F", "4").replace("C", "2"),
                                       s_color.replace("F", "3").replace("C", "1")),
                             corner_radius=4).pack(side="right", padx=4)

            title_lbl = ctk.CTkLabel(card, text=title, text_color="white",
                                     font=ctk.CTkFont(size=11, weight="bold"),
                                     wraplength=700, justify="left", anchor="w")
            title_lbl.pack(fill="x", padx=10, pady=(0, 2))

            if summary:
                ctk.CTkLabel(card, text=summary, text_color="gray70",
                             font=ctk.CTkFont(size=10),
                             wraplength=700, justify="left", anchor="w").pack(
                    fill="x", padx=10, pady=(0, 8))
            else:
                card.pack_configure()  # no extra padding needed
                title_lbl.pack_configure(pady=(0, 8))

            if url and url.startswith("http"):
                card.configure(cursor="hand2")
                title_lbl.configure(cursor="hand2", text_color="#88BBFF")
                for w in (card, title_lbl):
                    w.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

    @staticmethod
    def _sentiment(text: str):
        """根据关键词判断新闻情绪"""
        pos_kw = ["涨停", "大涨", "利好", "增长", "盈利", "突破", "获批", "合同",
                  "订单", "扩产", "上调", "战略", "合作", "回购", "分红"]
        neg_kw = ["跌停", "大跌", "利空", "亏损", "下滑", "处罚", "违规", "风险",
                  "减持", "下调", "诉讼", "监管", "警示", "退市"]
        for kw in pos_kw:
            if kw in text:
                return "📈 利好", GREEN
        for kw in neg_kw:
            if kw in text:
                return "📉 利空", RED
        return "", ""
