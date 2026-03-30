"""
gui/ccass_page.py — 港股 CCASS 机构持仓监控

通过 ccass-monitor CLI 获取香港交易所 CCASS 机构持仓数据，
分析大行增减持信号（短期 / 中期 / 异常检测）。
"""
import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import subprocess
import json
import threading
import os

plt.rcParams["font.family"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BG     = "#1a1a2e"
GREEN  = "#4CAF50"
RED    = "#FF6B6B"
YELLOW = "#FFD93D"
BLUE   = "#4D96FF"
GRAY   = "gray"

# NVM node 路径
NODE_BIN = os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin")
CCASS_BIN = os.path.join(NODE_BIN, "ccass")

# 预设港股（名称 → 代码）
PRESET_STOCKS = {
    "腾讯 00700":   "00700",
    "美团 03690":   "03690",
    "阿里巴巴 09988": "09988",
    "小米 01810":   "01810",
    "比亚迪 01211": "01211",
    "京东 09618":   "09618",
    "网易 09999":   "09999",
    "百度 09888":   "09888",
    "工商银行 01398": "01398",
    "中国银行 03988": "03988",
}

# 信号颜色与文字
SIGNAL_MAP = {
    "STRONG_BUY":  ("🔥 强力买入", GREEN),
    "BUY":         ("📈 买入",    GREEN),
    "HOLD":        ("⏸ 持有",    YELLOW),
    "SELL":        ("📉 卖出",    RED),
    "STRONG_SELL": ("💣 强力卖出", RED),
}

TREND_ZH = {
    "increasing": "↑ 上升",
    "decreasing": "↓ 下降",
    "neutral":    "→ 平稳",
    "insufficient_data": "数据不足",
}

MAGNITUDE_ZH = {
    "extreme":     "极端异常",
    "significant": "显著异常",
    "notable":     "轻微异常",
    "normal":      "正常",
}


class CCASSPage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._build()

    # ── UI ──────────────────────────────────────────────────────────────
    def _build(self):
        # 控制栏
        ctrl = ctk.CTkFrame(self, height=50, fg_color=("gray20", "gray15"))
        ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctrl.pack_propagate(False)

        ctk.CTkLabel(ctrl, text="CCASS 机构持仓",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=BLUE).pack(side="left", padx=(12, 12))

        # 预设下拉
        ctk.CTkLabel(ctrl, text="港股:").pack(side="left", padx=(0, 4))
        self.preset_var = tk.StringVar(value="腾讯 00700")
        ctk.CTkOptionMenu(ctrl, variable=self.preset_var,
                          values=list(PRESET_STOCKS.keys()),
                          width=150,
                          command=self._on_preset).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="或输入代码:").pack(side="left", padx=(12, 4))
        self.code_var = tk.StringVar(value="00700")
        entry = ctk.CTkEntry(ctrl, textvariable=self.code_var, width=80)
        entry.pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: self._start())

        ctk.CTkLabel(ctrl, text="参与者ID:").pack(side="left", padx=(12, 4))
        self.pid_var = tk.StringVar(value="C00019")
        ctk.CTkEntry(ctrl, textvariable=self.pid_var, width=80,
                     placeholder_text="C00019=汇丰").pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="查询", width=80,
                      command=self._start).pack(side="left", padx=12)

        self.status = ctk.CTkLabel(ctrl, text="首次查询需下载30日历史（约2-5分钟）",
                                   text_color=GRAY, font=ctk.CTkFont(size=11))
        self.status.pack(side="left", padx=4)

        self.progress = ctk.CTkProgressBar(ctrl, width=160, mode="indeterminate")

        # 主内容区：左信号面板 + 右图表
        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.pack(fill="both", expand=True, padx=10, pady=10)
        self.main.columnconfigure(0, weight=0, minsize=340)
        self.main.columnconfigure(1, weight=1)
        self.main.rowconfigure(0, weight=1)

        self.left_panel = ctk.CTkScrollableFrame(
            self.main, fg_color=("gray18", "gray12"), width=330)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.chart_panel = ctk.CTkFrame(self.main, fg_color=("gray18", "gray12"))
        self.chart_panel.grid(row=0, column=1, sticky="nsew")

        # 初始提示
        ctk.CTkLabel(self.left_panel,
                     text="选择港股后点击「查询」\n获取 CCASS 机构持仓信号",
                     text_color="gray50", font=ctk.CTkFont(size=13)).pack(
            expand=True, pady=60)
        ctk.CTkLabel(self.chart_panel,
                     text="持仓变化趋势图\n将在此显示",
                     text_color="gray50", font=ctk.CTkFont(size=13)).place(
            relx=0.5, rely=0.5, anchor="center")

    def _on_preset(self, selection):
        code = PRESET_STOCKS.get(selection, "")
        self.code_var.set(code)

    # ── 查询流程 ─────────────────────────────────────────────────────────
    def _start(self):
        code = self.code_var.get().strip().zfill(5)
        if not code:
            return
        self.status.configure(text=f"查询 {code}，首次约需2-5分钟…", text_color=YELLOW)
        self.progress.pack(side="left", padx=8)
        self.progress.start()
        threading.Thread(target=self._run, args=(code,), daemon=True).start()

    def _run(self, code):
        try:
            env = os.environ.copy()
            env["PATH"] = NODE_BIN + ":" + env.get("PATH", "")

            result = subprocess.run(
                [CCASS_BIN, "signal", code,
                 "--participant", self.pid_var.get().strip(),
                 "--json"],
                capture_output=True, text=True,
                env=env, timeout=600
            )
            # stdout = JSON, stderr = progress messages
            raw = result.stdout.strip()
            if not raw:
                raise ValueError(result.stderr or "无输出")
            data = json.loads(raw)
            self.after(0, lambda: self._render(data, code))
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self._set_err("查询超时（10分钟），请重试"))
        except json.JSONDecodeError as e:
            self.after(0, lambda: self._set_err(f"JSON解析失败: {e}"))
        except Exception as e:
            self.after(0, lambda: self._set_err(str(e)))

    def _set_err(self, msg):
        self.progress.stop()
        self.progress.pack_forget()
        self.status.configure(text=f"错误: {msg}", text_color=RED)

    # ── 渲染结果 ─────────────────────────────────────────────────────────
    def _render(self, data: dict, code: str):
        self.progress.stop()
        self.progress.pack_forget()
        self.status.configure(
            text=f"数据日期: {data.get('date', '—')}  参与者: {data.get('participantId', '—')}",
            text_color=GRAY)

        for w in self.left_panel.winfo_children():
            w.destroy()
        for w in self.chart_panel.winfo_children():
            w.destroy()

        self._render_left(data)
        self._render_chart(data)

    def _render_left(self, data: dict):
        p = self.left_panel

        # ── 综合信号大卡片 ──
        sig_str = data.get("signal", "HOLD")
        sig_label, sig_color = SIGNAL_MAP.get(sig_str, (sig_str, YELLOW))
        conf = data.get("confidence", 0)
        score = data.get("score", 0)

        sig_card = ctk.CTkFrame(p, fg_color=("gray22", "gray17"), corner_radius=10)
        sig_card.pack(fill="x", padx=8, pady=(12, 6))

        ctk.CTkLabel(sig_card, text=sig_label,
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=sig_color).pack(pady=(14, 4))
        ctk.CTkLabel(sig_card,
                     text=f"置信度 {conf*100:.0f}%   评分 {score:+.3f}",
                     text_color=GRAY, font=ctk.CTkFont(size=11)).pack(pady=(0, 6))

        # 摘要
        summary = data.get("summary", "")
        if summary:
            ctk.CTkLabel(sig_card, text=summary,
                         text_color="white", font=ctk.CTkFont(size=11),
                         wraplength=300, justify="left").pack(
                padx=10, pady=(0, 12))

        # ── 当前持仓 ──
        raw = data.get("rawData", {})
        cur = raw.get("current", {})
        stats = raw.get("stats", {})
        shareholding = cur.get("shareholding", 0)
        last_chg = stats.get("lastChange", {}).get("value", 0)
        pct = stats.get("percentileOfLastChange", 0)

        self._section(p, "📊 当前持仓")
        info_card = ctk.CTkFrame(p, fg_color=("gray22", "gray17"), corner_radius=8)
        info_card.pack(fill="x", padx=8, pady=(0, 6))
        rows = [
            ("持仓数量", f"{shareholding:,}"),
            ("昨日变化", f"{last_chg:+,}", GREEN if last_chg > 0 else (RED if last_chg < 0 else GRAY)),
            ("历史百分位", f"{pct}%"),
        ]
        for r in rows:
            self._kv_row(info_card, r[0], r[1], r[2] if len(r) > 2 else "white")

        # ── 短期信号 ──
        st = data.get("shortTerm", {})
        self._section(p, "⚡ 短期信号（1-5日）")
        st_card = ctk.CTkFrame(p, fg_color=("gray22", "gray17"), corner_radius=8)
        st_card.pack(fill="x", padx=8, pady=(0, 6))
        st_sig, st_color = SIGNAL_MAP.get(st.get("signal", "HOLD"), (st.get("signal"), YELLOW))
        st_rows = [
            ("信号",    st_sig, st_color),
            ("方向",    st.get("direction", "—"),
             GREEN if st.get("direction") == "增持" else RED if st.get("direction") == "减持" else YELLOW),
            ("连续天数", f"{st.get('consecutiveDays', 0)} 日"),
            ("3日动量",  f"{st.get('momentum3d', 0):+.2f}"),
        ]
        for r in st_rows:
            self._kv_row(st_card, r[0], r[1], r[2] if len(r) > 2 else "white")

        # 近5日明细
        deltas = st.get("deltas", [])
        if deltas:
            detail = ctk.CTkFrame(st_card, fg_color="transparent")
            detail.pack(fill="x", padx=10, pady=(4, 8))
            ctk.CTkLabel(detail, text="近5日变化:", text_color=GRAY,
                         font=ctk.CTkFont(size=10)).pack(anchor="w")
            for d in deltas:
                chg = d.get("change", 0)
                color = GREEN if chg > 0 else (RED if chg < 0 else GRAY)
                ctk.CTkLabel(detail,
                             text=f"  {d.get('date','')[:10]}  {chg:+,}",
                             text_color=color,
                             font=ctk.CTkFont(size=10)).pack(anchor="w")

        # ── 中期信号 ──
        mt = data.get("mediumTerm", {})
        self._section(p, "📅 中期信号（7-30日）")
        mt_card = ctk.CTkFrame(p, fg_color=("gray22", "gray17"), corner_radius=8)
        mt_card.pack(fill="x", padx=8, pady=(0, 6))
        mt_sig, mt_color = SIGNAL_MAP.get(mt.get("signal", "HOLD"), (mt.get("signal"), YELLOW))
        c7 = mt.get("change7dPct", 0)
        c30 = mt.get("change30dPct", 0)
        mt_rows = [
            ("信号",   mt_sig, mt_color),
            ("趋势",   TREND_ZH.get(mt.get("trend", "neutral"), mt.get("trend")),
             GREEN if mt.get("trend") == "increasing" else RED if mt.get("trend") == "decreasing" else YELLOW),
            ("7日变化",  f"{c7:+.2f}%", GREEN if c7 > 0 else RED),
            ("30日变化", f"{c30:+.2f}%", GREEN if c30 > 0 else RED),
            ("均线偏离", f"{mt.get('currentVsSma', 0):+.2f}%"),
        ]
        for r in mt_rows:
            self._kv_row(mt_card, r[0], r[1], r[2] if len(r) > 2 else "white")

        # ── 异常检测 ──
        ano = data.get("anomaly", {})
        self._section(p, "🚨 异常检测")
        ano_card = ctk.CTkFrame(p, fg_color=("gray22", "gray17"), corner_radius=8)
        ano_card.pack(fill="x", padx=8, pady=(0, 12))
        detected = ano.get("detected", False)
        z = ano.get("zScore", 0)
        mag = MAGNITUDE_ZH.get(ano.get("magnitude", "normal"), "正常")
        ano_rows = [
            ("检测结果", "⚠️ 已触发" if detected else "✅ 正常",
             RED if detected else GREEN),
            ("Z-Score",  f"{z:+.2f}",
             RED if abs(z) >= 2 else YELLOW if abs(z) >= 1.5 else GREEN),
            ("程度",     mag,
             RED if detected else GRAY),
            ("历史最大", "是 🔔" if ano.get("isHistoricalMax") else "否", "white"),
        ]
        for r in ano_rows:
            self._kv_row(ano_card, r[0], r[1], r[2])

    def _render_chart(self, data: dict):
        raw = data.get("rawData", {})
        deltas = raw.get("deltas", [])
        if not deltas:
            ctk.CTkLabel(self.chart_panel, text="暂无持仓变化数据",
                         text_color="gray50").place(relx=0.5, rely=0.5, anchor="center")
            return

        dates  = [d.get("date", "")[:10] for d in deltas]
        values = [d.get("change", 0) for d in deltas]
        holds  = [d.get("shareholding", 0) for d in deltas]

        # 最新在左 → 翻转
        dates  = dates[::-1]
        values = values[::-1]
        holds  = holds[::-1]

        fig = plt.Figure(figsize=(10, 7), facecolor=BG)

        # 上图：持仓总量
        ax1 = fig.add_subplot(211)
        ax1.set_facecolor(BG)
        ax1.plot(range(len(holds)), holds, color=BLUE, linewidth=1.5)
        ax1.fill_between(range(len(holds)), holds, min(holds), alpha=0.15, color=BLUE)
        ax1.set_title(
            f"{data.get('stockCode','')} 机构持仓总量（{data.get('participantId','')}）",
            color="white", fontsize=11)
        ax1.tick_params(colors="gray", labelsize=8)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M"))
        for sp in ax1.spines.values():
            sp.set_color("#333355")
        step = max(1, len(dates) // 8)
        ax1.set_xticks(range(0, len(dates), step))
        ax1.set_xticklabels(dates[::step], rotation=30, ha="right", fontsize=7, color="gray")

        # 下图：每日变化柱
        ax2 = fig.add_subplot(212)
        ax2.set_facecolor(BG)
        colors = [GREEN if v >= 0 else RED for v in values]
        ax2.bar(range(len(values)), values, color=colors, alpha=0.8)
        ax2.axhline(0, color="gray", linewidth=0.5)
        ax2.set_title("每日持仓变化量", color="white", fontsize=10)
        ax2.tick_params(colors="gray", labelsize=8)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1e6:.2f}M"))
        for sp in ax2.spines.values():
            sp.set_color("#333355")
        ax2.set_xticks(range(0, len(dates), step))
        ax2.set_xticklabels(dates[::step], rotation=30, ha="right", fontsize=7, color="gray")

        # 标注最大增/减
        stats = raw.get("stats", {})
        max_inc = stats.get("maxIncrease", {})
        max_dec = stats.get("maxDecrease", {})
        for stat, label, color in [
            (max_inc, "最大增持", GREEN),
            (max_dec, "最大减持", RED),
        ]:
            d = stat.get("date", "")[:10]
            if d in dates:
                idx = dates.index(d)
                ax2.annotate(label, xy=(idx, stat.get("value", 0)),
                             xytext=(idx, stat.get("value", 0) * 1.1),
                             color=color, fontsize=8,
                             arrowprops=dict(arrowstyle="->", color=color, lw=0.8))

        fig.tight_layout(pad=2)
        canvas = FigureCanvasTkAgg(fig, master=self.chart_panel)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ── 辅助 ─────────────────────────────────────────────────────────────
    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title,
                     text_color=BLUE, font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(10, 2))

    def _kv_row(self, parent, key, value, value_color="white"):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(row, text=key, text_color=GRAY,
                     font=ctk.CTkFont(size=11), width=70, anchor="w").pack(side="left")
        ctk.CTkLabel(row, text=str(value), text_color=value_color,
                     font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=4)
