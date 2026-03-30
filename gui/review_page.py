"""
gui/review_page.py — 复盘页面

选择历史某个交易日，重跑当天的预测信号，并展示之后实际涨跌结果。
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
from gui.predict_page import (
    PredictPage, BLUECHIP_POOL, STOP_PCT, TAKE_PCT, HOLD_DAYS,
    GREEN, RED, YELLOW, BLUE, GRAY,
)

# 复盘专用列
RCOLS   = ["排名", "代码",  "名称",  "评分", "所属板块",
           "入场价", "D+1",  "D+2",  "D+3",  "结果",  "触发信号"]
RWIDTHS = [40,     75,      95,     55,     100,
           75,     75,      75,     75,     70,     280]

INDEX_MAP = {
    "沪深300":  "sh000300",
    "上证指数":  "sh000001",
    "深证成指":  "sz399001",
    "创业板指":  "sz399006",
    "中证500":  "sh000905",
    "中证1000": "sh000852",
}


class ReviewPage(PredictPage):
    """
    复盘页：继承 PredictPage 的评分 / 候选池 / 新闻面板逻辑，
    额外加入「分析日期」选择和「实际结果」列。
    """

    def __init__(self, parent, app):
        self._trading_dates: list[str] = []   # ["2026-03-28", ...]
        super().__init__(parent, app)

    # ── 覆盖 UI 构建 ─────────────────────────────────────────────────────
    def _build(self):
        # ── 控制栏 ──
        ctrl = ctk.CTkFrame(self, height=50, fg_color=("gray20", "gray15"))
        ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctrl.pack_propagate(False)

        ctk.CTkLabel(ctrl, text="历史复盘",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=YELLOW).pack(side="left", padx=(12, 12))

        ctk.CTkLabel(ctrl, text="分析日期:").pack(side="left", padx=(0, 4))
        self.date_var = tk.StringVar(value="加载中…")
        self.date_menu = ctk.CTkOptionMenu(ctrl, variable=self.date_var,
                                           values=["加载中…"], width=140)
        self.date_menu.pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="↻", width=32,
                      command=self._refresh_dates).pack(side="left", padx=2)

        ctk.CTkLabel(ctrl, text="候选池:").pack(side="left", padx=(12, 4))
        self.pool_var = tk.StringVar(value="热门榜+蓝筹")
        ctk.CTkOptionMenu(ctrl, variable=self.pool_var,
                          values=["热门榜+蓝筹", "仅热门榜", "仅蓝筹"],
                          width=130).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="最低评分:").pack(side="left", padx=(12, 4))
        self.score_var = tk.StringVar(value="7")
        ctk.CTkOptionMenu(ctrl, variable=self.score_var,
                          values=["7", "8", "9", "10"],
                          width=60).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="大盘基准:").pack(side="left", padx=(12, 4))
        self.index_var = tk.StringVar(value="沪深300")
        ctk.CTkOptionMenu(ctrl, variable=self.index_var,
                          values=list(INDEX_MAP.keys()),
                          width=100).pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="开始复盘", width=90,
                      command=self._start).pack(side="left", padx=12)

        self.market_label = ctk.CTkLabel(ctrl, text="大盘: —",
                                         text_color=GRAY,
                                         font=ctk.CTkFont(size=11))
        self.market_label.pack(side="left", padx=(4, 12))

        self.status = ctk.CTkLabel(ctrl, text="先点 ↻ 加载交易日，再点「开始复盘」",
                                   text_color=GRAY)
        self.status.pack(side="left", padx=4)

        self.progress = ctk.CTkProgressBar(ctrl, width=180)
        self.progress.set(0)

        # ── 主内容区 ──
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=10)
        main.rowconfigure(0, weight=3)
        main.rowconfigure(1, weight=2)
        main.columnconfigure(0, weight=1)

        self.content = ctk.CTkFrame(main, fg_color=("gray18", "gray12"))
        self.content.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        ctk.CTkLabel(self.content,
                     text="选择分析日期后点击「开始复盘」\n重跑当日信号并对比实际涨跌",
                     font=ctk.CTkFont(size=15), text_color="gray50").place(
            relx=0.5, rely=0.5, anchor="center")

        # ── 新闻面板（继承父类逻辑） ──
        news_outer = ctk.CTkFrame(main, fg_color=("gray18", "gray12"))
        news_outer.grid(row=1, column=0, sticky="nsew")

        news_hdr = ctk.CTkFrame(news_outer, fg_color=("gray22", "gray18"), height=32)
        news_hdr.pack(fill="x")
        news_hdr.pack_propagate(False)
        self.news_title = ctk.CTkLabel(
            news_hdr, text="📰 信息面  （点击股票行加载新闻）",
            text_color=GRAY, font=ctk.CTkFont(size=11))
        self.news_title.pack(side="left", padx=12, pady=6)

        self.news_scroll = ctk.CTkScrollableFrame(news_outer, fg_color="transparent")
        self.news_scroll.pack(fill="both", expand=True, padx=4, pady=4)
        ctk.CTkLabel(self.news_scroll, text="点击上方股票查看最新资讯",
                     text_color="gray50").pack(pady=20)

        # 初始化加载交易日
        self._refresh_dates()

    # ── 加载最近交易日列表 ───────────────────────────────────────────────
    def _refresh_dates(self):
        self.status.configure(text="获取交易日历…", text_color=GRAY)
        threading.Thread(target=self._fetch_dates, daemon=True).start()

    def _fetch_dates(self):
        try:
            symbol = INDEX_MAP.get(self.index_var.get(), "sh000300")
            df = ak.stock_zh_index_daily(symbol=symbol).tail(12)
            df["date"] = pd.to_datetime(df["date"])
            dates = df["date"].sort_values(ascending=False).tolist()
            # 去掉今天（只保留已收盘的交易日，至少有 D+1 数据）
            today = pd.Timestamp(datetime.today().date())
            past  = [d for d in dates if d < today][:7]
            labels = []
            for i, d in enumerate(past):
                suffix = ["昨天", "前天", "3天前", "4天前", "5天前", "6天前", "7天前"][i]
                labels.append(f"{d.strftime('%Y-%m-%d')}（{suffix}）")
            self._trading_dates = [d.strftime("%Y%m%d") for d in past]
            self.after(0, lambda: self._update_date_menu(labels))
        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"交易日获取失败: {e}", text_color=RED))

    def _update_date_menu(self, labels):
        if not labels:
            return
        self.date_menu.configure(values=labels)
        self.date_var.set(labels[0])
        self.status.configure(text="选择日期后点击「开始复盘」", text_color=GRAY)

    # ── 主运行逻辑 ───────────────────────────────────────────────────────
    def _start(self):
        self.progress.set(0)
        self.progress.pack(side="left", padx=8)
        self.status.configure(text="检查大盘趋势…", text_color=YELLOW)
        threading.Thread(target=self._run_review, daemon=True).start()

    def _get_selected_date(self) -> str:
        label = self.date_var.get()
        idx   = self.date_menu.cget("values").index(label)
        return self._trading_dates[idx]

    def _run_review(self):
        try:
            end_date = self._get_selected_date()

            # 大盘趋势（以当日数据判断）
            uptrend, market_desc = self._get_market_trend_at(end_date)
            mc = GREEN if uptrend else YELLOW
            self.after(0, lambda: self.market_label.configure(
                text=market_desc, text_color=mc))

            self._set_prog("获取候选股列表…", 0.08)
            pool      = self.pool_var.get()
            min_score = int(self.score_var.get())
            candidates = self._get_candidates(pool)
            self._set_prog(f"共 {len(candidates)} 只候选股，开始复盘分析…", 0.15)

            results = []
            done    = [0]

            def analyze(code, name):
                res = self._score_and_outcome(code, name, uptrend, min_score, end_date)
                done[0] += 1
                self._set_prog(
                    f"分析 {done[0]}/{len(candidates)}…",
                    0.15 + 0.8 * done[0] / len(candidates))
                return res

            with ThreadPoolExecutor(max_workers=8) as ex:
                futs = [ex.submit(analyze, c, n) for c, n in candidates]
                for fut in as_completed(futs):
                    res = fut.result()
                    if res:
                        results.append(res)

            results.sort(key=lambda x: x["score"], reverse=True)
            top = results[:10]
            self.after(0, lambda: self._render_review(top, end_date, uptrend))

        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"错误: {e}", text_color=RED))
            self.after(0, lambda: self.progress.pack_forget())

    # ── 历史大盘趋势判断 ─────────────────────────────────────────────────
    def _get_market_trend_at(self, end_date: str):
        index_name = self.index_var.get()
        symbol     = INDEX_MAP.get(index_name, "sh000300")
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            df = df[df.index <= pd.Timestamp(end_date)].tail(120)
            close = df["close"].astype(float)
            ma5  = close.rolling(5).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            cur  = close.iloc[-1]
            chg  = (cur - close.iloc[-2]) / close.iloc[-2] * 100
            uptrend = (cur > ma20) and (ma5 > ma20)
            desc = (f"{index_name} {cur:.0f}  {chg:+.2f}%  "
                    f"{'✅ 上升趋势' if uptrend else '⚠️ 弱势行情'}")
            return uptrend, desc
        except Exception:
            return True, "大盘数据暂不可用"

    # ── 评分 + 实际结果 ──────────────────────────────────────────────────
    def _score_and_outcome(self, code, name, market_uptrend, min_score, end_date):
        try:
            # 截止 end_date 的历史数据（用于评分）
            end_dt    = datetime.strptime(end_date, "%Y%m%d")
            start_dt  = end_dt - timedelta(days=400)
            df_hist   = get_stock_hist(code,
                                       start=start_dt.strftime("%Y%m%d"),
                                       end=end_date)
            if len(df_hist) < 30:
                return None

            close  = df_hist["收盘"].astype(float)
            volume = df_hist["成交量"].astype(float)
            cur    = close.iloc[-1]   # end_date 的收盘价 = 入场价

            # ── 技术指标评分（同 predict_page） ──
            ma5  = close.rolling(5).mean()
            ma10 = close.rolling(10).mean()
            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(min(60, len(close))).mean()

            ema12  = close.ewm(span=12, adjust=False).mean()
            ema26  = close.ewm(span=26, adjust=False).mean()
            macd_l = ema12 - ema26
            sig_l  = macd_l.ewm(span=9, adjust=False).mean()
            hist_l = macd_l - sig_l

            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).iloc[-1]

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

            if macd_l.iloc[-2] < sig_l.iloc[-2] and macd_l.iloc[-1] > sig_l.iloc[-1]:
                score += 2; reasons.append("MACD金叉")
            elif macd_l.iloc[-1] > sig_l.iloc[-1] and hist_l.iloc[-1] > hist_l.iloc[-2] > 0:
                score += 2; reasons.append("MACD红柱扩张")
            elif macd_l.iloc[-1] > sig_l.iloc[-1]:
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

            # ── 实际结果：end_date 之后最多 3 个交易日 ──
            after_start = (end_dt + timedelta(days=1)).strftime("%Y%m%d")
            after_end   = (end_dt + timedelta(days=10)).strftime("%Y%m%d")
            try:
                df_after = get_stock_hist(code, start=after_start, end=after_end)
                after_closes = df_after["收盘"].astype(float).values[:3]
            except Exception:
                after_closes = []

            def day_ret(i):
                if i < len(after_closes):
                    return round((after_closes[i] - cur) / cur * 100, 2)
                return None

            d1, d2, d3 = day_ret(0), day_ret(1), day_ret(2)

            # 结果判断：3日内触碰止盈/止损
            stop = cur * (1 - STOP_PCT)
            take = cur * (1 + TAKE_PCT)
            outcome = "持有中"
            outcome_color = GRAY
            if after_closes is not None and len(after_closes) > 0:
                try:
                    df_high = df_after["最高"].astype(float).values[:3]
                    df_low  = df_after["最低"].astype(float).values[:3]
                    for i in range(min(3, len(df_high))):
                        if df_low[i] <= stop:
                            outcome = f"止损 {day_ret(i):+.1f}%"
                            outcome_color = RED
                            break
                        if df_high[i] >= take:
                            outcome = f"止盈 {day_ret(i):+.1f}%"
                            outcome_color = GREEN
                            break
                    else:
                        if d3 is not None:
                            outcome = f"到期 {d3:+.1f}%"
                            outcome_color = GREEN if d3 > 0 else RED
                except Exception:
                    pass

            # 所属板块
            try:
                info_df = ak.stock_individual_info_em(stock=code)
                info    = dict(zip(info_df.iloc[:, 0], info_df.iloc[:, 1]))
                sector  = str(info.get("行业", "—"))
            except Exception:
                sector = "—"

            return {
                "code":          code,
                "name":          name,
                "score":         score,
                "sector":        sector,
                "entry":         cur,
                "d1":            d1,
                "d2":            d2,
                "d3":            d3,
                "outcome":       outcome,
                "outcome_color": outcome_color,
                "reasons":       "；".join(reasons),
            }
        except Exception:
            return None

    # ── 渲染复盘结果 ─────────────────────────────────────────────────────
    def _render_review(self, items, end_date, market_uptrend):
        for w in self.content.winfo_children():
            w.destroy()

        self.progress.pack_forget()

        wins   = sum(1 for x in items if "止盈" in x["outcome"] or
                     ("到期" in x["outcome"] and x["d3"] and x["d3"] > 0))
        losses = sum(1 for x in items if "止损" in x["outcome"] or
                     ("到期" in x["outcome"] and x["d3"] and x["d3"] <= 0))
        wr_txt = f"胜率 {wins/(wins+losses)*100:.0f}%" if (wins + losses) > 0 else ""

        date_fmt = datetime.strptime(end_date, "%Y%m%d").strftime("%Y-%m-%d")
        self.status.configure(
            text=f"{date_fmt} 信号: {len(items)} 只   {wr_txt}",
            text_color=GREEN if wins >= losses else RED)

        if not items:
            ctk.CTkLabel(self.content, text="当日无符合条件的信号",
                         text_color="gray50").place(relx=0.5, rely=0.5, anchor="center")
            return

        # 统计摘要栏
        summary = ctk.CTkFrame(self.content, fg_color=("gray22", "gray17"), height=36)
        summary.pack(fill="x", padx=10, pady=(8, 4))
        summary.pack_propagate(False)

        avg_d1 = _avg([x["d1"] for x in items if x["d1"] is not None])
        avg_d3 = _avg([x["d3"] for x in items if x["d3"] is not None])
        ctk.CTkLabel(summary,
                     text=(f"分析日: {date_fmt}   信号数: {len(items)}   "
                           f"盈: {wins}  亏: {losses}  {wr_txt}   "
                           f"D+1均值: {avg_d1:+.2f}%   D+3均值: {avg_d3:+.2f}%"),
                     text_color=YELLOW, font=ctk.CTkFont(size=11)).pack(
            side="left", padx=12, pady=6)

        # 表格
        hdr, scroll = self._build_review_table(self.content)
        for rank, item in enumerate(items, 1):
            self._add_review_row(scroll, rank, item)

    def _build_review_table(self, parent):
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        hbar = tk.Scrollbar(outer, orient="horizontal")
        hbar.pack(side="bottom", fill="x")

        canvas = tk.Canvas(outer, bg="#1f1f2e", highlightthickness=0,
                           xscrollcommand=hbar.set)
        canvas.pack(fill="both", expand=True)
        hbar.config(command=canvas.xview)

        inner = ctk.CTkFrame(canvas, fg_color="transparent")
        win   = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(e=None):
            canvas.configure(scrollregion=(0, 0,
                                           inner.winfo_reqwidth(),
                                           max(canvas.winfo_height(),
                                               inner.winfo_reqheight())))
            canvas.itemconfig(win, height=max(canvas.winfo_height(),
                                              inner.winfo_reqheight()))
        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", lambda e: (
            canvas.itemconfig(win, height=e.height),
            canvas.configure(scrollregion=(0, 0, inner.winfo_reqwidth(),
                                           max(e.height, inner.winfo_reqheight())))
        ))
        canvas.bind("<MouseWheel>", lambda e: (
            canvas.xview_scroll(int(-1*(e.delta/120)), "units")
            if (e.state & 0x1) else None
        ))

        hdr = ctk.CTkFrame(inner, fg_color=("gray25", "gray20"), corner_radius=4)
        hdr.pack(fill="x", pady=(0, 1))
        for i, w in enumerate(RWIDTHS):
            hdr.columnconfigure(i, weight=0, minsize=w)
        for i, col in enumerate(RCOLS):
            ctk.CTkLabel(hdr, text=col, text_color=GRAY,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         anchor="w").grid(row=0, column=i, padx=6, pady=5, sticky="w")

        rows = ctk.CTkScrollableFrame(inner, fg_color="transparent")
        rows.pack(fill="both", expand=True)
        for i, w in enumerate(RWIDTHS):
            rows.columnconfigure(i, weight=0, minsize=w)

        return hdr, rows

    def _add_review_row(self, parent, rank, item):
        bg    = ("gray20", "gray16") if rank % 2 == 0 else ("gray18", "gray13")
        row_f = ctk.CTkFrame(parent, fg_color=bg, corner_radius=4, cursor="hand2")
        row_f.pack(fill="x", pady=2)
        for i, w in enumerate(RWIDTHS):
            row_f.columnconfigure(i, weight=0, minsize=w)

        s  = item["score"]
        sc = GREEN if s >= 7 else (YELLOW if s >= 5 else "white")

        def ret_fmt(v):
            if v is None: return "—", GRAY
            return f"{v:+.2f}%", (GREEN if v > 0 else RED if v < 0 else GRAY)

        d1t, d1c = ret_fmt(item["d1"])
        d2t, d2c = ret_fmt(item["d2"])
        d3t, d3c = ret_fmt(item["d3"])

        cells = [
            (str(rank),              "white"),
            (item["code"],           BLUE),
            (item["name"],           "white"),
            (f"{s} 分",              sc),
            (item.get("sector","—"), YELLOW),
            (f"¥{item['entry']:.2f}", "white"),
            (d1t,                    d1c),
            (d2t,                    d2c),
            (d3t,                    d3c),
            (item["outcome"],        item["outcome_color"]),
            (item["reasons"],        GRAY),
        ]
        for col, (text, color) in enumerate(cells):
            lbl = ctk.CTkLabel(row_f, text=text, text_color=color,
                               font=ctk.CTkFont(size=11), anchor="w")
            lbl.grid(row=0, column=col, padx=6, pady=7, sticky="w")
            lbl.bind("<Button-1>", lambda e, c=item["code"], n=item["name"]:
                     self._load_news(c, n))
        row_f.bind("<Button-1>", lambda e, c=item["code"], n=item["name"]:
                   self._load_news(c, n))


# ── 工具函数 ─────────────────────────────────────────────────────────────
def _avg(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0
