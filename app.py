"""
app.py — 股市分析桌面应用主入口
"""
import customtkinter as ctk

from gui.kline_page import KlinePage
from gui.finance_page import FinancePage
from gui.sector_page import SectorPage
from gui.probability_page import ProbabilityPage
from gui.predict_page import PredictPage
from gui.weak_page import WeakPage
from gui.review_page import ReviewPage
from gui.detail_page import DetailPage
from gui.ccass_page import CCASSPage

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

NAV_ITEMS = [
    ("K线分析",  KlinePage),
    ("财务分析",  FinancePage),
    ("板块分析",  SectorPage),
    ("涨跌概率",  ProbabilityPage),
    ("次日预测",  PredictPage),
    ("弱势预警",  WeakPage),
    ("历史复盘",  ReviewPage),
    ("个股详情",  DetailPage),
    ("CCASS持仓", CCASSPage),
]


class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("A股分析工具")
        self.geometry("1280x800")
        self.minsize(900, 600)

        self._pages = {}
        self._build()
        self._switch("K线分析")

    def _build(self):
        # ── 侧边栏 ──
        sidebar = ctk.CTkFrame(self, width=140, corner_radius=0,
                               fg_color=("gray15", "gray10"))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="股市分析",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#4D96FF").pack(pady=(24, 20), padx=10)

        self._nav_btns = {}
        for name, PageClass in NAV_ITEMS:
            btn = ctk.CTkButton(
                sidebar, text=name, width=120, height=36,
                corner_radius=8, anchor="w",
                fg_color="transparent",
                hover_color=("gray25", "gray20"),
                text_color="white",
                command=lambda n=name: self._switch(n),
            )
            btn.pack(pady=4, padx=10)
            self._nav_btns[name] = btn

        # ── 内容区 ──
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True)

        for name, PageClass in NAV_ITEMS:
            page = PageClass(content, self)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._pages[name] = page

    def _switch(self, name: str):
        # 高亮选中按钮
        for n, btn in self._nav_btns.items():
            btn.configure(
                fg_color=("#2B5EA7", "#1a3a6b") if n == name else "transparent"
            )
        self._pages[name].lift()


if __name__ == "__main__":
    App().mainloop()
