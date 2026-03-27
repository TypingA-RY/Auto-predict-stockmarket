"""
gui/weak_page.py — 弱势股预警（分数最低前10）

复用 PredictPage 全部逻辑，仅改变排序方向和标题。
"""
import tkinter as tk
import customtkinter as ctk

from gui.predict_page import PredictPage, GREEN, RED, YELLOW, BLUE, GRAY, STOP_PCT, TAKE_PCT, HOLD_DAYS, COLS, WIDTHS


class WeakPage(PredictPage):

    def __init__(self, parent, app):
        # 直接调用父类 __init__，它会调用 _build()
        super().__init__(parent, app)

    # ── 覆盖标题标签 ─────────────────────────────────────────────────────
    def _build(self):
        super()._build()
        # 修改页面标题
        for w in self.winfo_children():
            if isinstance(w, ctk.CTkFrame):
                for child in w.winfo_children():
                    if isinstance(child, ctk.CTkLabel) and "次日强势股预测" in str(child.cget("text")):
                        child.configure(text="弱势股预警", text_color=RED)
                        break

    # ── 覆盖主运行逻辑：取分数最低前10 ──────────────────────────────────
    def _run(self):
        import threading
        import akshare as ak
        import pandas as pd
        from concurrent.futures import ThreadPoolExecutor, as_completed

        try:
            uptrend, market_desc = self._get_market_trend()
            mc = GREEN if uptrend else YELLOW
            self.after(0, lambda: self.market_label.configure(
                text=market_desc, text_color=mc))

            self._set_prog("获取候选股列表…", 0.08)
            pool      = self.pool_var.get()
            hist_days = int(self.years_var.get()) * 365
            candidates = self._get_candidates(pool)
            self._set_prog(f"共 {len(candidates)} 只候选股，开始技术分析…", 0.15)

            results = []
            done    = [0]

            def analyze(code, name):
                # 弱势股：min_score=0，收集所有股票的评分
                res = self._score_stock_weak(code, name, uptrend, hist_days)
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

            # 按分数升序，取最低10只
            results.sort(key=lambda x: x["score"])
            bottom10 = results[:10]
            self.after(0, lambda: self._render_weak(bottom10, uptrend))

        except Exception as e:
            self.after(0, lambda: self.status.configure(
                text=f"错误: {e}", text_color=RED))
            self.after(0, lambda: self.progress.pack_forget())

    def _score_stock_weak(self, code, name, market_uptrend, hist_days=365):
        """同父类评分，但不设阈值过滤，全量返回"""
        import numpy as np
        from core.data import get_stock_hist

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
            else:
                reasons.append("跌破MA20")

            if macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1]:
                score += 2; reasons.append("MACD金叉")
            elif macd.iloc[-1] > signal.iloc[-1] and hist.iloc[-1] > hist.iloc[-2] > 0:
                score += 2; reasons.append("MACD红柱扩张")
            elif macd.iloc[-1] > signal.iloc[-1]:
                score += 1; reasons.append("MACD多头")
            else:
                reasons.append("MACD空头")

            if 45 <= rsi <= 65:
                score += 2; reasons.append(f"RSI健康 {rsi:.0f}")
            elif 35 <= rsi < 45:
                score += 1; reasons.append(f"RSI回升 {rsi:.0f}")
            elif 65 < rsi <= 75:
                score += 1; reasons.append(f"RSI强势 {rsi:.0f}")
            elif rsi < 35:
                reasons.append(f"RSI超卖 {rsi:.0f}")
            else:
                reasons.append(f"RSI超买 {rsi:.0f}")

            if vr >= 2.0:
                score += 2; reasons.append(f"大幅放量 {vr:.1f}x")
            elif vr >= 1.4:
                score += 1; reasons.append(f"温和放量 {vr:.1f}x")
            else:
                reasons.append(f"量能萎缩 {vr:.1f}x")

            up_days = int((close.pct_change().iloc[-5:] > 0).sum())
            if up_days >= 3:
                score += 1; reasons.append(f"近5日{up_days}涨")
            else:
                reasons.append(f"近5日仅{up_days}涨")

            stop_loss   = round(cur * (1 - STOP_PCT), 2)
            take_profit = round(cur * (1 + TAKE_PCT), 2)
            rr_risk     = cur - stop_loss
            rr          = round((take_profit - cur) / rr_risk, 1) if rr_risk > 0 else 0

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

    # ── 渲染（弱势版本，红色主题） ────────────────────────────────────────
    def _render_weak(self, bottom10, market_uptrend):
        for w in self.content.winfo_children():
            w.destroy()

        self.progress.pack_forget()
        self.status.configure(text=f"筛选完成，显示最弱 {len(bottom10)} 只", text_color=RED)

        if not bottom10:
            ctk.CTkLabel(self.content, text="暂无数据",
                         text_color="gray50").place(relx=0.5, rely=0.5, anchor="center")
            return

        ctk.CTkLabel(
            self.content,
            text="⚠️ 弱势预警仅供参考，不构成做空或卖出建议   数字越低越弱",
            text_color=RED, font=ctk.CTkFont(size=11)
        ).pack(pady=(8, 2))

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

        for rank, item in enumerate(bottom10, 1):
            self._add_row_weak(scroll, rank, item)

    def _add_row_weak(self, parent, rank, item):
        bg    = ("gray20", "gray16") if rank % 2 == 0 else ("gray18", "gray13")
        row_f = ctk.CTkFrame(parent, fg_color=bg, corner_radius=4, cursor="hand2")
        row_f.pack(fill="x", pady=2)
        for i, w in enumerate(WIDTHS):
            row_f.columnconfigure(i, weight=1 if w == 1 else 0, minsize=max(w, 10))

        s  = item["score"]
        # 弱势股：分越低越红
        sc = RED if s <= 3 else (YELLOW if s <= 5 else "white")
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
