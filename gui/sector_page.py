"""
gui/sector_page.py — 板块/行业分析页面
"""
import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
import numpy as np
import threading

from core.data import get_industry_list, get_industry_hist, get_concept_spot

plt.rcParams["font.family"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BG = "#1a1a2e"


class SectorPage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._industry_df = None
        self._build()

    def _build(self):
        ctrl = ctk.CTkFrame(self, height=50, fg_color=("gray20", "gray15"))
        ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctrl.pack_propagate(False)

        ctk.CTkLabel(ctrl, text="视图:").pack(side="left", padx=(12, 4))
        self.view_var = tk.StringVar(value="行业热力图")
        ctk.CTkOptionMenu(ctrl, variable=self.view_var,
                          values=["行业热力图", "行业涨跌榜", "概念板块"],
                          width=120, command=lambda _: self._load()).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="行业走势 →").pack(side="left", padx=(20, 4))
        self.ind_var = tk.StringVar(value="")
        self.ind_menu = ctk.CTkOptionMenu(ctrl, variable=self.ind_var,
                                          values=["—"], width=160,
                                          command=lambda _: self._load_industry_hist())
        self.ind_menu.pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="刷新", width=70,
                      command=self._load).pack(side="left", padx=12)
        self.status = ctk.CTkLabel(ctrl, text="", text_color="gray")
        self.status.pack(side="left")

        self.chart_frame = ctk.CTkFrame(self, fg_color=("gray18", "gray12"))
        self.chart_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(self.chart_frame, text="点击「刷新」加载板块数据",
                     font=ctk.CTkFont(size=16), text_color="gray50").place(
            relx=0.5, rely=0.5, anchor="center")

    def _load(self):
        self.status.configure(text="加载中…", text_color="gray")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            view = self.view_var.get()
            if view == "概念板块":
                df = get_concept_spot()
            else:
                df = get_industry_list()
            self._industry_df = df
            self.after(0, lambda: self._render(df, view))
        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"错误: {e}", text_color="#FF6B6B"))

    def _render(self, df: pd.DataFrame, view: str):
        for w in self.chart_frame.winfo_children():
            w.destroy()

        if df.empty:
            ctk.CTkLabel(self.chart_frame, text="暂无数据", text_color="gray50").pack(expand=True)
            return

        # 找涨跌幅列和名称列
        chg_col  = next((c for c in df.columns if "涨跌幅" in str(c)), None)
        name_col = next((c for c in df.columns if "名称" in str(c)), df.columns[1])

        if chg_col:
            df = df.copy()
            df[chg_col] = pd.to_numeric(df[chg_col], errors="coerce").fillna(0)

        # 更新行业下拉菜单
        if view != "概念板块" and name_col in df.columns:
            names = df[name_col].tolist()[:30]
            self.ind_menu.configure(values=names)
            if not self.ind_var.get() or self.ind_var.get() == "—":
                self.ind_var.set(names[0])

        self.status.configure(text=f"共 {len(df)} 个板块", text_color="gray")

        if view == "行业热力图" and chg_col:
            self._render_heatmap(df, name_col, chg_col)
        else:
            self._render_bar(df, name_col, chg_col)

    def _render_heatmap(self, df, name_col, chg_col):
        top = df.nlargest(40, chg_col) if len(df) > 40 else df
        top = top.copy()

        n = len(top)
        cols = 5
        rows = (n + cols - 1) // cols

        fig = plt.Figure(figsize=(13, max(6, rows * 1.4)), facecolor=BG)
        ax  = fig.add_subplot(111)
        ax.set_facecolor(BG)
        ax.axis("off")
        ax.set_title("行业板块热力图（涨跌幅）", color="white", fontsize=12, pad=8)

        cmap = plt.cm.RdYlGn
        vals = top[chg_col].values
        vmax = max(abs(vals.min()), abs(vals.max()), 1)
        norm = mcolors.TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

        for i, (_, row) in enumerate(top.iterrows()):
            r, c = divmod(i, cols)
            val  = row[chg_col]
            color = cmap(norm(val))
            rect = plt.Rectangle([c, rows - r - 1], 0.92, 0.88,
                                  color=color, transform=ax.transData)
            ax.add_patch(rect)
            ax.text(c + 0.46, rows - r - 0.44,
                    f"{str(row[name_col])[:6]}\n{val:+.2f}%",
                    ha="center", va="center", fontsize=8,
                    color="white" if abs(val) > 1 else "black",
                    fontweight="bold")

        ax.set_xlim(-0.1, cols + 0.1)
        ax.set_ylim(-0.1, rows + 0.1)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _render_bar(self, df, name_col, chg_col):
        show = df.head(30) if chg_col is None else \
               pd.concat([df.nlargest(15, chg_col), df.nsmallest(15, chg_col)])
        show = show.drop_duplicates(subset=[name_col])

        fig = plt.Figure(figsize=(13, 8), facecolor=BG)
        ax  = fig.add_subplot(111)
        ax.set_facecolor(BG)
        for spine in ax.spines.values():
            spine.set_color("#333355")
        ax.tick_params(colors="gray", labelsize=8)

        if chg_col:
            show = show.sort_values(chg_col)
            vals  = show[chg_col]
            colors = ["#FF6B6B" if v >= 0 else "#4CAF50" for v in vals]
            ax.barh(range(len(show)), vals, color=colors, alpha=0.85)
            ax.axvline(0, color="gray", linewidth=0.5)
            ax.set_xlabel("涨跌幅 (%)", color="gray")
        ax.set_yticks(range(len(show)))
        ax.set_yticklabels(show[name_col].astype(str).str[:8].tolist(),
                           fontsize=8, color="white")
        title = self.view_var.get() + " 涨跌榜"
        ax.set_title(title, color="white", fontsize=11)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _load_industry_hist(self):
        name = self.ind_var.get()
        if not name or name == "—":
            return
        threading.Thread(target=self._fetch_hist, args=(name,), daemon=True).start()

    def _fetch_hist(self, name):
        try:
            df = get_industry_hist(name, days=180)
            self.after(0, lambda: self._render_ind_hist(df, name))
        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"行业走势错误: {e}", text_color="#FF6B6B"))

    def _render_ind_hist(self, df: pd.DataFrame, name: str):
        if df.empty:
            return
        for w in self.chart_frame.winfo_children():
            w.destroy()

        chg_col   = next((c for c in df.columns if "涨跌幅" in str(c)), None)
        close_col = next((c for c in df.columns if "收盘" in str(c)), None)

        fig = plt.Figure(figsize=(13, 6), facecolor=BG)
        ax  = fig.add_subplot(111)
        ax.set_facecolor(BG)
        for spine in ax.spines.values():
            spine.set_color("#333355")
        ax.tick_params(colors="gray", labelsize=8)

        col = close_col or (chg_col if chg_col else df.columns[1])
        vals = pd.to_numeric(df[col], errors="coerce")
        ax.plot(df.index, vals, color="#4D96FF", linewidth=1.2)
        ax.fill_between(df.index, vals, vals.min(), alpha=0.15, color="#4D96FF")
        ax.set_title(f"{name} 近6月走势", color="white", fontsize=11)
        ax.set_ylabel(col, color="gray", fontsize=8)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
