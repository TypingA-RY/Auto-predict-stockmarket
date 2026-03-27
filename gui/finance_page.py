"""
gui/finance_page.py — 财务数据分析页面
"""
import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
import threading

from core.data import get_financial_abstract, get_profit_sheet, get_stock_info

plt.rcParams["font.family"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BG = "#1a1a2e"
ACCENT = "#4D96FF"


class FinancePage(ctk.CTkFrame):

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
        ctk.CTkButton(ctrl, text="查询", width=70,
                      command=self._load).pack(side="left", padx=12)
        self.status_label = ctk.CTkLabel(ctrl, text="", text_color="gray")
        self.status_label.pack(side="left", padx=8)

        self.content = ctk.CTkFrame(self, fg_color=("gray18", "gray12"))
        self.content.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(self.content, text="输入股票代码后点击「查询」",
                     font=ctk.CTkFont(size=16), text_color="gray50").place(
            relx=0.5, rely=0.5, anchor="center")

    def _load(self):
        self.status_label.configure(text="加载中…", text_color="gray")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            symbol = self.symbol_var.get().strip()
            abstract = get_financial_abstract(symbol)
            profit   = get_profit_sheet(symbol)
            info     = get_stock_info(symbol)
            self.after(0, lambda: self._render(abstract, profit, info, symbol))
        except Exception as e:
            self.after(0, lambda: self.status_label.configure(
                text=f"错误: {e}", text_color="#FF6B6B"))

    def _render(self, abstract: pd.DataFrame, profit: pd.DataFrame,
              info: dict, symbol: str):
        for w in self.content.winfo_children():
            w.destroy()

        name = info.get("股票简称", symbol)
        self.status_label.configure(text=f"{name}", text_color="white")

        # 左边：关键指标卡片
        left = ctk.CTkFrame(self.content, fg_color=("gray22", "gray16"), width=260)
        left.pack(side="left", fill="y", padx=(6, 4), pady=6)
        left.pack_propagate(False)

        ctk.CTkLabel(left, text=f"📊 {name} 关键指标",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(10, 6), padx=10)

        key_fields = [
            ("总市值", "总市值"), ("市盈率TTM", "市盈率TTM"), ("市净率", "市净率"),
            ("ROE", "净资产收益率"), ("净利润率", "销售净利率"), ("毛利率", "销售毛利率"),
            ("资产负债率", "资产负债率"), ("每股收益", "每股收益"),
            ("每股净资产", "每股净资产"), ("每股现金流", "每股现金流量净额"),
        ]
        if not abstract.empty:
            latest = abstract.iloc[0]
            for label, col in key_fields:
                val = "—"
                for c in abstract.columns:
                    if col in str(c):
                        try:
                            val = f"{float(latest[c]):.4g}"
                        except Exception:
                            val = str(latest[c])
                        break
                row = ctk.CTkFrame(left, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=2)
                ctk.CTkLabel(row, text=label, text_color="gray",
                             font=ctk.CTkFont(size=11)).pack(side="left")
                ctk.CTkLabel(row, text=val,
                             font=ctk.CTkFont(size=11, weight="bold")).pack(side="right")

        # 右边：营收 & 净利润趋势图
        right = ctk.CTkFrame(self.content, fg_color=("gray18", "gray12"))
        right.pack(side="left", fill="both", expand=True, padx=(4, 6), pady=6)

        if profit.empty:
            ctk.CTkLabel(right, text="暂无利润表数据", text_color="gray50").place(
                relx=0.5, rely=0.5, anchor="center")
            return

        # 取最近8个报告期
        profit = profit.head(8).iloc[::-1].copy()

        # 找营收和净利润列
        rev_col = next((c for c in profit.columns if "营业总收入" in str(c) or "营业收入" in str(c)), None)
        net_col = next((c for c in profit.columns if "净利润" in str(c) and "归属" in str(c)), None)
        if net_col is None:
            net_col = next((c for c in profit.columns if "净利润" in str(c)), None)

        date_col = profit.columns[0]
        labels = profit[date_col].astype(str).str[:7].tolist()

        fig = plt.Figure(figsize=(9, 7), facecolor=BG)
        gs  = gridspec.GridSpec(2, 1, figure=fig, hspace=0.4)

        def _bar_chart(ax, col, title, color):
            ax.set_facecolor(BG)
            for spine in ax.spines.values():
                spine.set_color("#333355")
            ax.tick_params(colors="gray", labelsize=8)
            if col and col in profit.columns:
                vals = pd.to_numeric(profit[col], errors="coerce").fillna(0) / 1e8
                bars = ax.bar(range(len(vals)), vals, color=color, width=0.6, alpha=0.85)
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
                ax.set_ylabel("亿元", color="gray", fontsize=8)
                # 增长率标注
                for i, (bar, val) in enumerate(zip(bars, vals)):
                    if i > 0 and vals.iloc[i-1] != 0:
                        growth = (val / vals.iloc[i-1] - 1) * 100
                        ax.text(bar.get_x() + bar.get_width()/2,
                                bar.get_height() + abs(vals.max()) * 0.01,
                                f"{growth:+.1f}%", ha="center", va="bottom",
                                color=("#FF6B6B" if growth >= 0 else "#4CAF50"), fontsize=7)
            else:
                ax.text(0.5, 0.5, "数据不可用", transform=ax.transAxes,
                        ha="center", color="gray")
            ax.set_title(title, color="white", fontsize=10)

        _bar_chart(fig.add_subplot(gs[0]), rev_col, "营业收入（亿元）", ACCENT)
        _bar_chart(fig.add_subplot(gs[1]), net_col, "净利润（亿元）", "#FF6B6B")

        canvas = FigureCanvasTkAgg(fig, master=right)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
