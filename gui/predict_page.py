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

COLS   = ["排名", "代码",  "名称",  "现价",  "评分",
          "胜率",  "预期收益", "止损价", "止盈价", "盈亏比", "触发信号"]
WIDTHS = [40,     75,      95,     75,     55,
          60,     75,      75,     75,     55,     1]


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

        ctk.CTkLabel(ctrl, text="候选池:").pack(side="left", padx=(0, 4))
        self.pool_var = tk.StringVar(value="热门榜+蓝筹")
        ctk.CTkOptionMenu(ctrl, variable=self.pool_var,
                          values=["热门榜+蓝筹", "仅热门榜", "仅蓝筹"],
                          width=130).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="最低评分:").pack(side="left", padx=(12, 4))
        self.score_var = tk.StringVar(value="7")
        ctk.CTkOptionMenu(ctrl, variable=self.score_var,
                          values=["7", "8", "9", "10"],
                          width=60).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="数据年数:").pack(side="left", padx=(12, 4))
        self.years_var = tk.StringVar(value="1")
        ctk.CTkOptionMenu(ctrl, variable=self.years_var,
                          values=["1", "2", "3"],
                          width=60).pack(side="left", padx=4)

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

    # ── 大盘趋势 ─────────────────────────────────────────────────────────
    def _get_market_trend(self):
        try:
            df    = ak.stock_zh_index_daily(symbol="sh000300")
            df["date"] = pd.to_datetime(df["date"])
            df    = df.set_index("date").sort_index().tail(120)
            close = df["close"].astype(float)
            ma5   = close.rolling(5).mean().iloc[-1]
            ma20  = close.rolling(20).mean().iloc[-1]
            cur   = close.iloc[-1]
            chg   = (cur - close.iloc[-2]) / close.iloc[-2] * 100
            uptrend = (cur > ma20) and (ma5 > ma20)
            desc  = (f"沪深300 {cur:.0f}  {chg:+.2f}%  "
                     f"{'✅ 上升趋势' if uptrend else '⚠️ 弱势行情'}")
            return uptrend, desc
        except Exception as e:
            return True, f"大盘数据暂不可用，不过滤"

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
            pool       = self.pool_var.get()
            min_score  = int(self.score_var.get())
            hist_days  = int(self.years_var.get()) * 365
            candidates = self._get_candidates(pool)
            self._set_prog(f"共 {len(candidates)} 只候选股，开始技术分析…", 0.15)

            results = []
            done    = [0]

            def analyze(code, name):
                res = self._score_stock(code, name, uptrend, min_score, hist_days)
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
    def _score_stock(self, code, name, market_uptrend, min_score=7, hist_days=365):
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

            score   = 0
            reasons = []

            m5, m10, m20, m60 = ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1], ma60.iloc[-1]
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

            return {
                "code":        code,
                "name":        name,
                "price":       cur,
                "score":       score,
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

        # 表头
        hdr = ctk.CTkFrame(self.content, fg_color=("gray25", "gray20"), corner_radius=4)
        hdr.pack(fill="x", padx=10, pady=(4, 0))
        for i, w in enumerate(WIDTHS):
            hdr.columnconfigure(i, weight=1 if w == 1 else 0, minsize=max(w, 10))
        for i, (col, w) in enumerate(zip(COLS, WIDTHS)):
            ctk.CTkLabel(hdr, text=col, text_color=GRAY,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         anchor="w").grid(row=0, column=i, padx=6, pady=5, sticky="w")

        scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=(2, 8))
        for i, w in enumerate(WIDTHS):
            scroll.columnconfigure(i, weight=1 if w == 1 else 0, minsize=max(w, 10))

        for rank, item in enumerate(top10, 1):
            self._add_row(scroll, rank, item)

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

        cells = [
            (str(rank),                     "white"),
            (item["code"],                  BLUE),
            (item["name"],                  "white"),
            (f"¥{item['price']:.2f}",       "white"),
            (f"{s} 分",                     sc),
            (wr_txt,                        wr_color),
            (er_txt,                        er_color),
            (f"¥{item['stop_loss']:.2f}",   RED),
            (f"¥{item['take_profit']:.2f}", GREEN),
            (f"{rr}:1",                     GREEN if rr >= 2.5 else YELLOW),
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
        title_col = next((c for c in df.columns if "标题" in str(c) or "title" in str(c).lower()), None)
        time_col  = next((c for c in df.columns if "时间" in str(c) or "date" in str(c).lower() or "发布" in str(c)), None)
        url_col   = next((c for c in df.columns
                          if "链接" in str(c) or "url" in str(c).lower()), None)

        shown = df.head(15)
        for _, row in shown.iterrows():
            title = str(row[title_col]) if title_col else str(row.iloc[0])
            ts    = str(row[time_col])[:16] if time_col else ""
            url   = str(row[url_col]) if url_col else None

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
                                     font=ctk.CTkFont(size=11),
                                     wraplength=700, justify="left", anchor="w")
            title_lbl.pack(fill="x", padx=10, pady=(0, 6))

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
