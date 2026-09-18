# -*- coding: utf-8 -*-
"""
滚动方式对比测试（v2）

三种滚动方式并排，用滚轮快速上下滚动，看哪个会留下"拖影"。

    A  CustomTkinter 自带滚动   —— 现在正式程序用的就是这个
    B  原生 tkinter 画布滚动
    C  不用画布（直接移动面板）  —— 带滚动条

用法：双击本文件，分别把鼠标放进 A / B / C 里快速上下滚动，
然后告诉我哪几个有拖影。
"""
import tkinter as tk

import customtkinter as ctk

ROWS = 30
ROW_H = 46
BG = "#111111"
PANEL = "#1D1D1D"

COLORS = [
    "#E74C3C", "#E67E22", "#F1C40F", "#2ECC71", "#1ABC9C", "#3498DB",
    "#9B59B6", "#E84393", "#D35400", "#16A085", "#27AE60", "#2980B9",
]

ctk.set_appearance_mode("dark")


def fill_rows(parent, rows=ROWS, row_h=ROW_H):
    for i in range(rows):
        c = COLORS[i % len(COLORS)]
        f = tk.Frame(parent, bg=c, height=row_h)
        f.pack(fill="x", pady=2)
        f.pack_propagate(False)
        tk.Label(f, text=f"第 {i+1} 行　快速滚动看残影", bg=c, fg="#FFFFFF",
                 font=("Microsoft YaHei UI", 12), anchor="w").pack(side="left", padx=12)


def bind_wheel(w, handler):
    """给控件及其所有子控件绑滚轮"""
    w.bind("<MouseWheel>", handler)
    for ch in w.winfo_children():
        bind_wheel(ch, handler)


# ==================== C：不用画布，直接移动面板 ====================
class PlaceScroller:
    """把内容面板用 place 定位，滚动时只改 y 偏移（完全不使用画布滚动）"""

    def __init__(self, parent, bg=PANEL):
        self.wrap = tk.Frame(parent, bg=bg)
        self.sb = tk.Scrollbar(self.wrap, orient="vertical", command=self._on_scrollbar)
        self.sb.pack(side="right", fill="y")
        self.holder = tk.Frame(self.wrap, bg=bg)
        self.holder.pack(side="left", fill="both", expand=True)
        self.holder.pack_propagate(False)          # 固定视口大小
        self.inner = tk.Frame(self.holder, bg=bg)
        self.inner.place(x=0, y=0, relwidth=1)     # 内容面板
        self.offset = 0
        self.holder.bind("<Configure>", lambda e: self._apply())
        self.inner.bind("<Configure>", lambda e: self._apply())

    def _content_h(self):
        return max(self.inner.winfo_reqheight(), self.holder.winfo_height())

    def _max_offset(self):
        return max(0, self.inner.winfo_reqheight() - self.holder.winfo_height())

    def _apply(self):
        m = self._max_offset()
        self.offset = max(0, min(m, self.offset))
        self.inner.place_configure(y=-self.offset)
        ch = self._content_h()
        if m <= 0:
            self.sb.set(0, 1)
        else:
            self.sb.set(self.offset / ch, (self.offset + self.holder.winfo_height()) / ch)

    def _on_scrollbar(self, *args):
        if not args:
            return
        if args[0] == "moveto":
            self.offset = int(float(args[1]) * self._content_h())
        elif args[0] == "scroll":
            self.offset += int(args[1]) * 40
        self._apply()

    def wheel(self, e):
        self.offset += (-1 if e.delta > 0 else 1) * 120
        self._apply()


root = ctk.CTk()
root.title("滚动方式对比测试 v2")
root.geometry("1240x660")
root.configure(fg_color=BG)

ctk.CTkLabel(
    root, text="分别把鼠标放进 A / B / C，用滚轮【快速上下滚动】，看哪几个留下残影",
    font=("Microsoft YaHei UI", 15, "bold"), text_color="#FFFFFF",
).pack(pady=(12, 8))

cols = ctk.CTkFrame(root, fg_color="transparent")
cols.pack(fill="both", expand=True, padx=12, pady=(0, 12))
for i in range(3):
    cols.grid_columnconfigure(i, weight=1)
cols.grid_rowconfigure(0, weight=1)

# ---------- A ----------
boxA = ctk.CTkFrame(cols, fg_color=PANEL, corner_radius=10)
boxA.grid(row=0, column=0, sticky="nsew", padx=6)
ctk.CTkLabel(boxA, text="A　CustomTkinter 滚动（现在用的）",
             font=("Microsoft YaHei UI", 13, "bold"), text_color="#F1C40F").pack(pady=8)
sfA = ctk.CTkScrollableFrame(boxA, fg_color=PANEL, corner_radius=0)
sfA.pack(fill="both", expand=True, padx=6, pady=(0, 8))
fill_rows(sfA)

# ---------- B ----------
boxB = ctk.CTkFrame(cols, fg_color=PANEL, corner_radius=10)
boxB.grid(row=0, column=1, sticky="nsew", padx=6)
ctk.CTkLabel(boxB, text="B　原生 tkinter 画布滚动",
             font=("Microsoft YaHei UI", 13, "bold"), text_color="#3498DB").pack(pady=8)
wrapB = tk.Frame(boxB, bg=PANEL)
wrapB.pack(fill="both", expand=True, padx=6, pady=(0, 8))
cvB = tk.Canvas(wrapB, bg=PANEL, highlightthickness=0, bd=0)
sbB = tk.Scrollbar(wrapB, orient="vertical", command=cvB.yview)
cvB.configure(yscrollcommand=sbB.set)
sbB.pack(side="right", fill="y")
cvB.pack(side="left", fill="both", expand=True)
innerB = tk.Frame(cvB, bg=PANEL)
widB = cvB.create_window((0, 0), window=innerB, anchor="nw")
# 关键修复：把内层面板宽度同步成画布宽度，否则宽度只有 1px（内容看不见）
cvB.bind("<Configure>", lambda e: cvB.itemconfigure(widB, width=e.width))
innerB.bind("<Configure>", lambda e: cvB.configure(scrollregion=cvB.bbox("all")))
fill_rows(innerB)


def wheel_B(e):
    cvB.yview_scroll(-1 if e.delta > 0 else 1, "units")


bind_wheel(cvB, wheel_B)
bind_wheel(innerB, wheel_B)

# ---------- C ----------
boxC = ctk.CTkFrame(cols, fg_color=PANEL, corner_radius=10)
boxC.grid(row=0, column=2, sticky="nsew", padx=6)
ctk.CTkLabel(boxC, text="C　不用画布（直接移动面板）",
             font=("Microsoft YaHei UI", 13, "bold"), text_color="#2ECC71").pack(pady=8)
wrapC = tk.Frame(boxC, bg=PANEL)
wrapC.pack(fill="both", expand=True, padx=6, pady=(0, 8))
scrollerC = PlaceScroller(wrapC)
scrollerC.wrap.pack(fill="both", expand=True)
fill_rows(scrollerC.inner)
bind_wheel(scrollerC.holder, scrollerC.wheel)
bind_wheel(scrollerC.inner, scrollerC.wheel)

root.mainloop()
