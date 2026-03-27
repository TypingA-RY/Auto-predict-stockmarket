"""
gui/probability_page.py — 日维度涨跌概率分析页面
"""
import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
import numpy as np
import threading

from core.data import get_stock_hist
from core.indicators import calc_win_probability

plt.rcParams["font.family"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BG     = "#1a1a2e"
BLUE   = "#4D96FF"
GREEN  = "#4CAF50"
RED    = "#FF6B6B"
YELLOW = "#FFD93D"
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五"]
MONTH_NAMES   = [f"{i}月" for i in range(1, 13)]


class ProbabilityPage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._build()

    def _build(self):
        ctrl = ctk.CTkFrame(self, height=50, fg_color=("gray20", "gray15"))
        ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctrl.pack_propagate(False)

        ctk.CTkLabel(ctrl, text="股票代码:").pack(side="left", padx=(12, 4))
        self.symbol_var = tk.StringVar(value="000001")
        ctk.CTkEntry(ctrl, textvariable=self.symbol_var, width=90).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="回看:").pack(side="left", padx=(12, 4))
        self.period_var = tk.StringVar(value="3年")
        ctk.CTkOptionMenu(ctrl, variable=self.period_var,
                          values=["1年", "2年", "3年", "5年"],
                          width=80).pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="分析", width=70,
                      command=self._load).pack(side="left", padx=12)
        self.status = ctk.CTkLabel(ctrl, text="", text_color="gray")
        self.status.pack(side="left")

        self.chart_frame = ctk.CTkFrame(self, fg_color=("gray18", "gray12"))
        self.chart_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(self.chart_frame, text="输入股票代码后点击「分析」",
                     font=ctk.CTkFont(size=16), text_color="gray50").place(
            relx=0.5, rely=0.5, anchor="center")

    def _period_to_days(self):
        return {"1年": 365, "2年": 730, "3年": 1095, "5年": 1825}[self.period_var.get()]

    def _load(self):
        self.status.configure(text="计算中…", text_color="gray")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            symbol = self.symbol_var.get().strip()
            df = get_stock_hist(symbol, days=self._period_to_days())
            df = calc_win_probability(df)
            self.after(0, lambda: self._render(df, symbol))
        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"错误: {e}", text_color=RED))

    def _render(self, df: pd.DataFrame, symbol: str):
        for w in self.chart_frame.winfo_children():
            w.destroy()

        total      = len(df.dropna(subset=["is_up"]))
        overall_wr = df["is_up"].mean() * 100
        self.status.configure(
            text=f"{symbol}  |  样本 {total} 日  |  总体胜率 {overall_wr:.1f}%",
            text_color="white")

        fig = plt.Figure(figsize=(14, 11), facecolor=BG)
        gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.5, wspace=0.35)

        def _style(ax, title):
            ax.set_facecolor(BG)
            for spine in ax.spines.values():
                spine.set_color("#333355")
            ax.tick_params(colors="gray", labelsize=8)
            ax.set_title(title, color="white", fontsize=10, pad=6)

        # ── 1. 滚动胜率折线（全宽） ──
        ax1 = fig.add_subplot(gs[0, :])
        _style(ax1, "滚动胜率趋势 (20日 / 60日)")
        ax1.plot(df.index, df["win_rate_20"], color=BLUE,  linewidth=0.9,
                 label="20日胜率", alpha=0.9)
        ax1.plot(df.index, df["win_rate_60"], color=YELLOW, linewidth=1.2,
                 label="60日胜率", alpha=0.9)
        ax1.axhline(50, color="gray", linewidth=0.7, linestyle="--", alpha=0.6)
        ax1.fill_between(df.index, df["win_rate_20"], 50,
                         where=(df["win_rate_20"] > 50), alpha=0.08, color=GREEN)
        ax1.fill_between(df.index, df["win_rate_20"], 50,
                         where=(df["win_rate_20"] < 50), alpha=0.08, color=RED)
        ax1.set_ylabel("胜率 (%)", color="gray", fontsize=8)
        ax1.set_ylim(0, 100)
        ax1.legend(loc="upper right", fontsize=8,
                   facecolor=BG, labelcolor="white", framealpha=0.5)

        # ── 2. 星期胜率柱状图 ──
        ax2 = fig.add_subplot(gs[1, 0])
        _style(ax2, "各星期胜率")
        wd_wr = df.groupby("weekday")["is_up"].mean() * 100
        wd_wr = wd_wr.reindex(range(5)).fillna(50)
        colors_wd = [GREEN if v >= 50 else RED for v in wd_wr]
        bars = ax2.bar(range(5), wd_wr, color=colors_wd, width=0.6, alpha=0.85)
        ax2.axhline(50, color="gray", linewidth=0.7, linestyle="--")
        ax2.set_xticks(range(5))
        ax2.set_xticklabels(WEEKDAY_NAMES, color="white")
        ax2.set_ylabel("胜率 (%)", color="gray", fontsize=8)
        ax2.set_ylim(30, 70)
        for bar, val in zip(bars, wd_wr):
            ax2.text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + 0.3,
                     f"{val:.1f}%", ha="center", fontsize=8,
                     color=GREEN if val >= 50 else RED)

        # ── 3. 月份胜率柱状图 ──
        ax3 = fig.add_subplot(gs[1, 1])
        _style(ax3, "各月份胜率")
        mo_wr = df.groupby("month")["is_up"].mean() * 100
        mo_wr = mo_wr.reindex(range(1, 13)).fillna(50)
        colors_mo = [GREEN if v >= 50 else RED for v in mo_wr]
        bars2 = ax3.bar(range(12), mo_wr, color=colors_mo, width=0.7, alpha=0.85)
        ax3.axhline(50, color="gray", linewidth=0.7, linestyle="--")
        ax3.set_xticks(range(12))
        ax3.set_xticklabels(MONTH_NAMES, color="white", fontsize=7)
        ax3.set_ylabel("胜率 (%)", color="gray", fontsize=8)
        ax3.set_ylim(25, 75)
        for bar, val in zip(bars2, mo_wr):
            ax3.text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + 0.3,
                     f"{val:.0f}%", ha="center", fontsize=7,
                     color=GREEN if val >= 50 else RED)

        # ── 4. 日涨跌幅分布直方图 ──
        ax4 = fig.add_subplot(gs[2, 0])
        _style(ax4, "日涨跌幅分布")
        ret = df["return_pct"].dropna()
        ax4.hist(ret[ret >= 0], bins=40, color=RED,   alpha=0.7, label="上涨")
        ax4.hist(ret[ret < 0],  bins=40, color=GREEN, alpha=0.7, label="下跌")
        ax4.axvline(0, color="white", linewidth=0.8, linestyle="--")
        ax4.axvline(ret.mean(), color=YELLOW, linewidth=1.0,
                    linestyle="--", label=f"均值 {ret.mean():.2f}%")
        ax4.set_xlabel("涨跌幅 (%)", color="gray", fontsize=8)
        ax4.set_ylabel("频次", color="gray", fontsize=8)
        ax4.legend(fontsize=7, facecolor=BG, labelcolor="white", framealpha=0.5)

        # ── 5. 日历热力图（近1年胜率） ──
        ax5 = fig.add_subplot(gs[2, 1])
        _style(ax5, "近1年 日历热力图（红=涨 绿=跌）")
        recent = df.dropna(subset=["is_up"]).tail(252)
        cal_data = recent.groupby(["month", "weekday"])["is_up"].mean() * 100

        heatmap = np.full((12, 5), np.nan)
        for (mo, wd), val in cal_data.items():
            if 1 <= mo <= 12 and 0 <= wd <= 4:
                heatmap[mo - 1, wd] = val

        im = ax5.imshow(heatmap, cmap="RdYlGn", vmin=30, vmax=70,
                        aspect="auto")
        ax5.set_xticks(range(5))
        ax5.set_xticklabels(WEEKDAY_NAMES, color="white", fontsize=8)
        ax5.set_yticks(range(12))
        ax5.set_yticklabels(MONTH_NAMES, color="white", fontsize=7)
        for r in range(12):
            for c in range(5):
                v = heatmap[r, c]
                if not np.isnan(v):
                    ax5.text(c, r, f"{v:.0f}%", ha="center", va="center",
                             fontsize=7, color="white")
        fig.colorbar(im, ax=ax5, fraction=0.04,
                     label="胜率 %").ax.yaxis.label.set_color("gray")

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
