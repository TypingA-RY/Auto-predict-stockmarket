"""
gui/kline_page.py — K线分析页面
"""
import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import mplfinance as mpf
import pandas as pd
import threading

from core.data import get_stock_hist, get_stock_info
from core.indicators import add_ma, add_macd, add_rsi

plt.rcParams["font.family"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

MA_COLORS = {"MA5": "#FF6B6B", "MA10": "#FFD93D", "MA20": "#6BCB77", "MA60": "#4D96FF"}


class KlinePage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._build()

    def _build(self):
        # ── 顶部控制栏 ──
        ctrl = ctk.CTkFrame(self, height=50, fg_color=("gray20", "gray15"))
        ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctrl.pack_propagate(False)

        ctk.CTkLabel(ctrl, text="股票代码:").pack(side="left", padx=(12, 4))
        self.symbol_var = tk.StringVar(value="000001")
        ctk.CTkEntry(ctrl, textvariable=self.symbol_var, width=90).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="周期:").pack(side="left", padx=(12, 4))
        self.period_var = tk.StringVar(value="1年")
        ctk.CTkOptionMenu(ctrl, variable=self.period_var,
                          values=["3月", "6月", "1年", "2年", "3年"],
                          width=80).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="复权:").pack(side="left", padx=(12, 4))
        self.adjust_var = tk.StringVar(value="前复权")
        ctk.CTkOptionMenu(ctrl, variable=self.adjust_var,
                          values=["前复权", "后复权", "不复权"],
                          width=80).pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="查询", width=70,
                      command=self._load).pack(side="left", padx=12)

        self.info_label = ctk.CTkLabel(ctrl, text="", text_color="gray")
        self.info_label.pack(side="left", padx=8)

        # ── 图表区域 ──
        self.chart_frame = ctk.CTkFrame(self, fg_color=("gray18", "gray12"))
        self.chart_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.canvas = None
        self._show_placeholder()

    def _show_placeholder(self):
        lbl = ctk.CTkLabel(self.chart_frame, text="输入股票代码后点击「查询」",
                           font=ctk.CTkFont(size=16), text_color="gray50")
        lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _period_to_days(self):
        return {"3月": 90, "6月": 180, "1年": 365, "2年": 730, "3年": 1095}[self.period_var.get()]

    def _adjust_map(self):
        return {"前复权": "qfq", "后复权": "hfq", "不复权": ""}[self.adjust_var.get()]

    def _load(self):
        self.info_label.configure(text="加载中…", text_color="gray")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            symbol = self.symbol_var.get().strip()
            df = get_stock_hist(symbol, days=self._period_to_days(),
                                adjust=self._adjust_map())
            df = add_ma(df)
            df = add_macd(df)
            df = add_rsi(df)
            info = get_stock_info(symbol)
            self.after(0, lambda: self._render(df, info, symbol))
        except Exception as e:
            self.after(0, lambda: self.info_label.configure(
                text=f"错误: {e}", text_color="#FF6B6B"))

    def _render(self, df: pd.DataFrame, info: dict, symbol: str):
        # 清除旧 canvas
        for w in self.chart_frame.winfo_children():
            w.destroy()

        name = info.get("股票简称", symbol)
        self.info_label.configure(
            text=f"{name}  |  最新: {df['收盘'].iloc[-1]:.2f}  "
                 f"涨跌: {df['涨跌幅'].iloc[-1]:+.2f}%",
            text_color=("#FF6B6B" if df['涨跌幅'].iloc[-1] >= 0 else "#4CAF50"))

        fig = plt.Figure(figsize=(14, 10), facecolor="#1a1a2e")
        gs  = gridspec.GridSpec(4, 1, figure=fig,
                                height_ratios=[4, 1, 1.2, 1],
                                hspace=0.08)

        ax_k    = fig.add_subplot(gs[0])
        ax_vol  = fig.add_subplot(gs[1], sharex=ax_k)
        ax_macd = fig.add_subplot(gs[2], sharex=ax_k)
        ax_rsi  = fig.add_subplot(gs[3], sharex=ax_k)

        for ax in [ax_k, ax_vol, ax_macd, ax_rsi]:
            ax.set_facecolor("#1a1a2e")
            ax.tick_params(colors="gray", labelsize=8)
            for spine in ax.spines.values():
                spine.set_color("#333355")

        # K线
        x = range(len(df))
        up   = df["收盘"] >= df["开盘"]
        down = ~up
        w = 0.6
        ax_k.bar([i for i, u in zip(x, up)   if u],
                 [df["收盘"].iloc[i] - df["开盘"].iloc[i] for i, u in enumerate(up)   if u],
                 bottom=[df["开盘"].iloc[i] for i, u in enumerate(up)   if u],
                 width=w, color="#FF6B6B", zorder=2)
        ax_k.bar([i for i, d in zip(x, down) if d],
                 [df["开盘"].iloc[i] - df["收盘"].iloc[i] for i, d in enumerate(down) if d],
                 bottom=[df["收盘"].iloc[i] for i, d in enumerate(down) if d],
                 width=w, color="#4CAF50", zorder=2)
        ax_k.vlines(x,
                    [df["最低"].iloc[i]  for i in x],
                    [df["最高"].iloc[i] for i in x],
                    color=["#FF6B6B" if u else "#4CAF50" for u in up],
                    linewidth=0.6, zorder=2)

        for ma, color in MA_COLORS.items():
            if ma in df.columns:
                ax_k.plot(x, df[ma], color=color, linewidth=0.9,
                          label=ma, alpha=0.85)
        ax_k.legend(loc="upper left", fontsize=7,
                    facecolor="#1a1a2e", labelcolor="white",
                    framealpha=0.5)
        ax_k.set_title(f"{name} ({symbol})  K线", color="white", fontsize=11, pad=6)
        ax_k.set_ylabel("价格", color="gray", fontsize=8)

        # 成交量
        colors_vol = ["#FF6B6B" if u else "#4CAF50" for u in up]
        ax_vol.bar(x, df["成交量"], color=colors_vol, width=w, alpha=0.7)
        ax_vol.set_ylabel("成交量", color="gray", fontsize=8)

        # MACD
        hist_colors = ["#FF6B6B" if v >= 0 else "#4CAF50" for v in df["Hist"]]
        ax_macd.bar(x, df["Hist"], color=hist_colors, width=w, alpha=0.8)
        ax_macd.plot(x, df["MACD"],   color="#FFD700", linewidth=0.9, label="MACD")
        ax_macd.plot(x, df["Signal"], color="#FF69B4", linewidth=0.9, label="Signal")
        ax_macd.axhline(0, color="gray", linewidth=0.5, linestyle="--")
        ax_macd.legend(loc="upper left", fontsize=7,
                       facecolor="#1a1a2e", labelcolor="white", framealpha=0.5)
        ax_macd.set_ylabel("MACD", color="gray", fontsize=8)

        # RSI
        ax_rsi.plot(x, df["RSI"], color="#9C6FFF", linewidth=1.0)
        ax_rsi.axhline(70, color="#FF6B6B", linewidth=0.6, linestyle="--", alpha=0.6)
        ax_rsi.axhline(30, color="#4CAF50", linewidth=0.6, linestyle="--", alpha=0.6)
        ax_rsi.fill_between(x, 70, 100, alpha=0.05, color="#FF6B6B")
        ax_rsi.fill_between(x, 0,  30,  alpha=0.05, color="#4CAF50")
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI(14)", color="gray", fontsize=8)

        # X轴日期
        step = max(1, len(df) // 8)
        ticks = list(range(0, len(df), step))
        labels = [df.index[i].strftime("%y/%m") for i in ticks]
        ax_rsi.set_xticks(ticks)
        ax_rsi.set_xticklabels(labels, color="gray", fontsize=7)
        plt.setp(ax_k.get_xticklabels(), visible=False)
        plt.setp(ax_vol.get_xticklabels(), visible=False)
        plt.setp(ax_macd.get_xticklabels(), visible=False)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas = canvas
