"""
gui/detail_page.py — 个股详情页
左侧：K线 + MA + 成交量 + MACD（含标注） + RSI（含标注）
右侧：基本面指标卡片 + 近期新闻
"""
import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
import numpy as np
import threading
import webbrowser

import akshare as ak
from core.data import get_stock_hist
from core.indicators import add_ma, add_macd, add_rsi

plt.rcParams["font.family"] = ["Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BG     = "#1a1a2e"
BLUE   = "#4D96FF"
GREEN  = "#4CAF50"
RED    = "#FF6B6B"
YELLOW = "#FFD93D"
GRAY   = "#333355"
MA_COLORS = {"MA5": "#FF6B6B", "MA10": "#FFD93D", "MA20": "#6BCB77", "MA60": "#4D96FF"}


class DetailPage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._canvas = None
        self._build()

    # ── UI ──────────────────────────────────────────────────────────────
    def _build(self):
        ctrl = ctk.CTkFrame(self, height=50, fg_color=("gray20", "gray15"))
        ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctrl.pack_propagate(False)

        ctk.CTkLabel(ctrl, text="个股详情",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=BLUE).pack(side="left", padx=(12, 16))

        ctk.CTkLabel(ctrl, text="股票代码:").pack(side="left", padx=(0, 4))
        self.symbol_var = tk.StringVar(value="000001")
        entry = ctk.CTkEntry(ctrl, textvariable=self.symbol_var, width=90)
        entry.pack(side="left", padx=4)
        entry.bind("<Return>", lambda _: self._load())

        ctk.CTkLabel(ctrl, text="周期:").pack(side="left", padx=(12, 4))
        self.period_var = tk.StringVar(value="1年")
        ctk.CTkOptionMenu(ctrl, variable=self.period_var,
                          values=["3月", "6月", "1年", "2年", "3年"],
                          width=80).pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="查询", width=70,
                      command=self._load).pack(side="left", padx=12)

        self.status = ctk.CTkLabel(ctrl, text="输入代码后点击查询或按回车",
                                   text_color="gray")
        self.status.pack(side="left", padx=8)

        # 主体：左图 + 右侧信息
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=10)

        self.chart_frame = ctk.CTkFrame(body, fg_color=(BG, BG))
        self.chart_frame.pack(side="left", fill="both", expand=True)

        self.info_frame = ctk.CTkFrame(body, fg_color=("gray18", "gray13"), width=280)
        self.info_frame.pack(side="right", fill="y", padx=(8, 0))
        self.info_frame.pack_propagate(False)

        ctk.CTkLabel(self.info_frame, text="输入代码后查询",
                     text_color="gray50").place(relx=0.5, rely=0.5, anchor="center")

    def _period_days(self):
        return {"3月": 90, "6月": 180, "1年": 365, "2年": 730, "3年": 1095}[self.period_var.get()]

    # ── 加载 ─────────────────────────────────────────────────────────────
    def _load(self):
        self.status.configure(text="加载中…", text_color="gray")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            symbol = self.symbol_var.get().strip().zfill(6)
            days   = self._period_days()

            # 行情
            df = get_stock_hist(symbol, days=days)
            df = add_ma(df); df = add_macd(df); df = add_rsi(df)

            # 股票基本信息
            info = {}
            try:
                info_df = ak.stock_individual_info_em(symbol=symbol)
                info = dict(zip(info_df["item"], info_df["value"]))
            except Exception:
                pass

            # 财务摘要
            fin = pd.DataFrame()
            try:
                fin = ak.stock_financial_abstract(symbol=symbol)
            except Exception:
                pass

            # 新闻
            news = pd.DataFrame()
            try:
                news = ak.stock_news_em(symbol=symbol)
            except Exception:
                pass

            self.after(0, lambda: self._render(df, info, fin, news, symbol))
        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"错误: {e}", text_color=RED))

    # ── 渲染图表 ─────────────────────────────────────────────────────────
    def _render(self, df, info, fin, news, symbol):
        # 清旧图
        for w in self.chart_frame.winfo_children():
            w.destroy()
        for w in self.info_frame.winfo_children():
            w.destroy()

        name = info.get("股票简称", symbol)
        cur  = df["收盘"].iloc[-1]
        chg  = df["涨跌幅"].iloc[-1]
        chg_color = RED if chg >= 0 else GREEN
        self.status.configure(
            text=f"{name}  ¥{cur:.2f}  {chg:+.2f}%",
            text_color=chg_color)

        self._draw_chart(df, name, symbol)
        self._draw_info(info, fin, news, name)

    def _draw_chart(self, df, name, symbol):
        fig = plt.Figure(figsize=(13, 11), facecolor=BG)
        gs  = gridspec.GridSpec(4, 1, figure=fig,
                                height_ratios=[4, 1, 1.5, 1],
                                hspace=0.06)
        ax_k   = fig.add_subplot(gs[0])
        ax_vol = fig.add_subplot(gs[1], sharex=ax_k)
        ax_mac = fig.add_subplot(gs[2], sharex=ax_k)
        ax_rsi = fig.add_subplot(gs[3], sharex=ax_k)

        for ax in [ax_k, ax_vol, ax_mac, ax_rsi]:
            ax.set_facecolor(BG)
            ax.tick_params(colors="gray", labelsize=8)
            for sp in ax.spines.values():
                sp.set_color(GRAY)

        x    = np.arange(len(df))
        up   = df["收盘"] >= df["开盘"]
        down = ~up

        # ── K线 ──
        w = 0.6
        ax_k.bar(x[up],  df["收盘"][up]  - df["开盘"][up],
                 bottom=df["开盘"][up],   width=w, color=RED,   zorder=2)
        ax_k.bar(x[down], df["开盘"][down] - df["收盘"][down],
                 bottom=df["收盘"][down], width=w, color=GREEN, zorder=2)
        ax_k.vlines(x,
                    [df["最低"].iloc[i]  for i in x],
                    [df["最高"].iloc[i] for i in x],
                    color=[RED if u else GREEN for u in up],
                    linewidth=0.6, zorder=2)

        # MA 线（图例带当前值）
        for ma, color in MA_COLORS.items():
            if ma in df.columns:
                cur_val = df[ma].iloc[-1]
                ax_k.plot(x, df[ma], color=color, linewidth=0.9, alpha=0.85,
                          label=f"{ma}: {cur_val:.2f}")

        # 最新收盘价标注
        last_x   = len(df) - 1
        last_cls = df["收盘"].iloc[-1]
        ax_k.annotate(
            f"  {last_cls:.2f}",
            xy=(last_x, last_cls),
            xytext=(last_x + 0.5, last_cls),
            color=RED if up.iloc[-1] else GREEN,
            fontsize=9, fontweight="bold",
            arrowprops=dict(arrowstyle="-", color="gray", lw=0.5)
        )
        ax_k.legend(loc="upper left", fontsize=8,
                    facecolor=BG, labelcolor="white", framealpha=0.4)
        ax_k.set_title(f"{name}（{symbol}）", color="white", fontsize=11, pad=6)
        ax_k.set_ylabel("价格", color="gray", fontsize=8)

        # ── 成交量 ──
        ax_vol.bar(x, df["成交量"],
                   color=[RED if u else GREEN for u in up],
                   width=w, alpha=0.7)
        ax_vol.set_ylabel("成交量", color="gray", fontsize=7)

        # ── MACD ──
        dif  = df["MACD"].iloc[-1]
        dea  = df["Signal"].iloc[-1]
        hist = df["Hist"].iloc[-1]
        h_colors = [RED if v >= 0 else GREEN for v in df["Hist"]]
        ax_mac.bar(x, df["Hist"], color=h_colors, width=w, alpha=0.8)
        ax_mac.plot(x, df["MACD"],   color="#FFD700", linewidth=0.9)
        ax_mac.plot(x, df["Signal"], color="#FF69B4", linewidth=0.9)
        ax_mac.axhline(0, color="gray", linewidth=0.5, linestyle="--")
        ax_mac.set_ylabel("MACD", color="gray", fontsize=7)
        # 当前值文本框
        ax_mac.text(
            0.01, 0.95,
            f"DIF: {dif:.3f}   DEA: {dea:.3f}   HIST: {hist:.3f}",
            transform=ax_mac.transAxes,
            color="white", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#222244", alpha=0.8),
            va="top"
        )
        # 金叉/死叉标注
        for i in range(1, len(df)):
            prev_cross = df["MACD"].iloc[i-1] - df["Signal"].iloc[i-1]
            curr_cross = df["MACD"].iloc[i]   - df["Signal"].iloc[i]
            if prev_cross < 0 and curr_cross >= 0:
                ax_mac.annotate("金叉", xy=(i, df["Hist"].iloc[i]),
                                fontsize=6, color="#FFD700",
                                xytext=(0, 8), textcoords="offset points",
                                ha="center")
            elif prev_cross > 0 and curr_cross <= 0:
                ax_mac.annotate("死叉", xy=(i, df["Hist"].iloc[i]),
                                fontsize=6, color="#FF69B4",
                                xytext=(0, -12), textcoords="offset points",
                                ha="center")

        # ── RSI ──
        rsi_val = df["RSI"].iloc[-1]
        rsi_color = RED if rsi_val >= 70 else (GREEN if rsi_val <= 30 else "white")
        ax_rsi.plot(x, df["RSI"], color="#9C6FFF", linewidth=1.0)
        ax_rsi.axhline(70, color=RED,   linewidth=0.6, linestyle="--", alpha=0.7)
        ax_rsi.axhline(30, color=GREEN, linewidth=0.6, linestyle="--", alpha=0.7)
        ax_rsi.axhline(50, color="gray",linewidth=0.4, linestyle=":", alpha=0.5)
        ax_rsi.fill_between(x, 70, 100, alpha=0.05, color=RED)
        ax_rsi.fill_between(x, 0,  30,  alpha=0.05, color=GREEN)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI(14)", color="gray", fontsize=7)
        # 当前 RSI 值标注
        ax_rsi.axhline(rsi_val, color=rsi_color, linewidth=0.8, linestyle="--", alpha=0.8)
        ax_rsi.text(
            0.01, 0.88,
            f"RSI(14): {rsi_val:.1f}  {'超买' if rsi_val>=70 else ('超卖' if rsi_val<=30 else '中性')}",
            transform=ax_rsi.transAxes,
            color=rsi_color, fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#222244", alpha=0.8),
            va="top"
        )

        # X 轴日期
        step   = max(1, len(df) // 8)
        ticks  = list(range(0, len(df), step))
        labels = [df.index[i].strftime("%y/%m") for i in ticks]
        ax_rsi.set_xticks(ticks)
        ax_rsi.set_xticklabels(labels, color="gray", fontsize=7)
        plt.setp(ax_k.get_xticklabels(),   visible=False)
        plt.setp(ax_vol.get_xticklabels(), visible=False)
        plt.setp(ax_mac.get_xticklabels(), visible=False)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas = canvas

    # ── 右侧信息面板 ─────────────────────────────────────────────────────
    def _draw_info(self, info, fin, news, name):
        frame = self.info_frame

        # 标题
        ctk.CTkLabel(frame, text=f"📊 {name}",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="white").pack(pady=(10, 4), padx=10)

        # ── 基本面 ──
        ctk.CTkLabel(frame, text="─── 基本面 ───",
                     text_color=BLUE, font=ctk.CTkFont(size=11)).pack(pady=(4, 2))

        def _metric(label, val, color="white"):
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=1)
            ctk.CTkLabel(row, text=label, text_color="gray",
                         font=ctk.CTkFont(size=11)).pack(side="left")
            ctk.CTkLabel(row, text=str(val), text_color=color,
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="right")

        # 股票基本信息
        _metric("行业", info.get("行业", "—"))
        mktcap = info.get("总市值", 0)
        try:
            mktcap_str = f"{float(mktcap)/1e8:.1f}亿"
        except Exception:
            mktcap_str = str(mktcap)
        _metric("总市值", mktcap_str)
        _metric("上市时间", str(info.get("上市时间", "—"))[:8])

        # 财务指标
        if not fin.empty:
            latest_col = fin.columns[2]  # 最新报告期

            def _get_fin(keyword):
                row = fin[fin["指标"].str.contains(keyword, na=False) &
                          ~fin["指标"].str.contains("扣非|平均|摊薄|增长", na=False)]
                if not row.empty:
                    try:
                        return float(row.iloc[0][latest_col])
                    except Exception:
                        pass
                return None

            def _get_fin_growth(keyword):
                row = fin[fin["指标"].str.contains(keyword, na=False)]
                if not row.empty:
                    try:
                        return float(row.iloc[0][latest_col])
                    except Exception:
                        pass
                return None

            roe = _get_fin("净资产收益率.ROE")
            if roe is not None:
                _metric("ROE", f"{roe:.2f}%",
                        GREEN if roe > 15 else (YELLOW if roe > 8 else RED))

            eps = _get_fin("基本每股收益")
            if eps is not None:
                _metric("每股收益", f"{eps:.3f}元")

            debt = _get_fin("资产负债率")
            if debt is not None:
                _metric("资产负债率", f"{debt:.1f}%",
                        RED if debt > 70 else (YELLOW if debt > 50 else GREEN))

            rev_gr = _get_fin_growth("营业总收入增长率")
            if rev_gr is not None:
                _metric("营收增长率", f"{rev_gr:.1f}%",
                        GREEN if rev_gr > 10 else (YELLOW if rev_gr > 0 else RED))

            net_gr = _get_fin_growth("归属母公司净利润增长率")
            if net_gr is not None:
                _metric("净利增长率", f"{net_gr:.1f}%",
                        GREEN if net_gr > 10 else (YELLOW if net_gr > 0 else RED))

            _metric("数据期", latest_col[:10] if len(latest_col) >= 8 else latest_col,
                    color="gray")

        ctk.CTkFrame(frame, height=1, fg_color=GRAY).pack(fill="x", padx=10, pady=8)

        # ── 近期新闻 ──
        ctk.CTkLabel(frame, text="─── 近期新闻 ───",
                     text_color=BLUE, font=ctk.CTkFont(size=11)).pack(pady=(0, 4))

        if news.empty:
            ctk.CTkLabel(frame, text="暂无新闻", text_color="gray50",
                         font=ctk.CTkFont(size=10)).pack(pady=4)
        else:
            scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent",
                                            height=300)
            scroll.pack(fill="both", expand=True, padx=6, pady=(0, 8))

            for _, row in news.head(10).iterrows():
                title = str(row.get("新闻标题", ""))[:30]
                date  = str(row.get("发布时间", ""))[:10]
                link  = str(row.get("新闻链接", ""))

                item = ctk.CTkFrame(scroll, fg_color=("gray20","gray16"),
                                    corner_radius=4)
                item.pack(fill="x", pady=2, padx=2)

                ctk.CTkLabel(item, text=title, text_color="white",
                             font=ctk.CTkFont(size=10),
                             wraplength=220, justify="left",
                             anchor="w").pack(fill="x", padx=6, pady=(4, 0))

                bottom = ctk.CTkFrame(item, fg_color="transparent")
                bottom.pack(fill="x", padx=6, pady=(0, 4))
                ctk.CTkLabel(bottom, text=date, text_color="gray",
                             font=ctk.CTkFont(size=9)).pack(side="left")
                if link and link != "nan":
                    ctk.CTkButton(bottom, text="↗", width=24, height=18,
                                  fg_color="transparent", text_color=BLUE,
                                  font=ctk.CTkFont(size=10),
                                  command=lambda u=link: webbrowser.open(u)
                                  ).pack(side="right")
