# -*- coding: utf-8 -*-
"""
滚动方式对比测试

目的：找出哪种滚动方式在你这台电脑上不会出现"拖影"。

用法：双击本文件（或 python 滚动测试.py），会弹出三个并排的滚动区域：
    左边 A：CustomTkinter 自带滚动（现在正式程序用的就是这个）
    中间 B：原生 tkinter 画布滚动
    右边 C：不用画布，直接移动面板

请分别把鼠标放到 A / B / C 三个区域里，用滚轮【快速上下滚动】，
看哪几个会留下文字/色块的残影。
然后把结果告诉我（比如"A 和 B 有拖影，C 没有"）。
"""
import tkinter as tk

import customtkinter as ctk

ROWS = 24
ROW_H = 46
TEXT_COLOR = "#FFFFFF"

# 高对比色，拖影一眼就能看出来
COLORS = [
    "#E74C3C", "#E67E22", "#F1C40F", "#2ECC71", "#1ABC9C", "#3498DB",
    "#9B59B6", "#E84393", "#D35400", "#16A085", "#27AE60", "#2980B9",
]

ctk.set_appearance_mode("dark")
BG = "#111111"
PANEL = "#1D1D1D"


def make_rows(parent, row_h=ROW_H, rows=ROWS, bg=PANEL):
    """造 N 行彩色条目"""
    for i in range(rows):
        c = COLORS[i % len(COLORS)]
        f = tk.Frame(parent, bg=c, height=row_h)
        f.pack(fill="x", pady=2)
        f.pack_propagate(False)
        tk.Label(f, text=f"第 {i+1} 行  ——  快速滚动看看有没有残影",
                 bg=c, fg=TEXT_COLOR, font=("Microsoft YaHei UI", 12),
                 anchor="w").pack(side="left", padx=12)
    return parent


def add_wheel(widget, canvas_or_none, holder=None, inner=None, state=None):
    """给某个区域绑滚轮"""
    def _wheel(e):
        step = -1 if e.delta > 0 else 1
        px = 60 * step
        if canvas_or_none is not None:
            canvas_or_none.yview_scroll(step * 3, "units")
        elif inner is not None and state is not None:
            total = inner.winfo_reqheight()
            view = holder.winfo_height()
            state["y"] = max(0, min(max(0, total - view), state["y"] + px))
            inner.place_configure(y=-state["y"])
    widget.bind("<MouseWheel>", _wheel)
    for ch in widget.winfo_children():
        ch.bind("<MouseWheel>", _wheel)


root = ctk.CTk()
root.title("滚动方式对比测试")
root.geometry("1240x640")
root.configure(fg_color=BG)

head = ctk.CTkLabel(root, text="分别把鼠标放进下面三个区域，用滚轮【快速上下滚动】，看哪几个有拖影",
                    font=("Microsoft YaHei UI", 15, "bold"), text_color="#FFFFFF")
head.pack(pady=(12, 8))

cols = ctk.CTkFrame(root, fg_color="transparent")
cols.pack(fill="both", expand=True, padx=12, pady=(0, 12))
for i in range(3):
    cols.grid_columnconfigure(i, weight=1)
cols.grid_rowconfigure(0, weight=1)

# ---------------- A：CustomTkinter 自带滚动 ----------------
boxA = ctk.CTkFrame(cols, fg_color=PANEL, corner_radius=10)
boxA.grid(row=0, column=0, sticky="nsew", padx=6)
ctk.CTkLabel(boxA, text="A  CustomTkinter 滚动（正式程序用的）",
             font=("Microsoft YaHei UI", 13, "bold"), text_color="#F1C40F").pack(pady=8)
sfA = ctk.CTkScrollableFrame(boxA, fg_color=PANEL, corner_radius=0)
sfA.pack(fill="both", expand=True, padx=6, pady=(0, 8))
make_rows(sfA)

# ---------------- B：原生 tkinter 画布 ----------------
boxB = ctk.CTkFrame(cols, fg_color=PANEL, corner_radius=10)
boxB.grid(row=0, column=1, sticky="nsew", padx=6)
ctk.CTkLabel(boxB, text="B  原生 tkinter 画布滚动",
             font=("Microsoft YaHei UI", 13, "bold"), text_color="#3498DB").pack(pady=8)
wrapB = tk.Frame(boxB, bg=PANEL)
wrapB.pack(fill="both", expand=True, padx=6, pady=(0, 8))
cvB = tk.Canvas(wrapB, bg=PANEL, highlightthickness=0, bd=0)
sbB = tk.Scrollbar(wrapB, orient="vertical", command=cvB.yview)
cvB.configure(yscrollcommand=sbB.set)
sbB.pack(side="right", fill="y")
cvB.pack(side="left", fill="both", expand=True)
innerB = tk.Frame(cvB, bg=PANEL)
cvB.create_window((0, 0), window=innerB, anchor="nw")
innerB.bind("<Configure>", lambda e: cvB.configure(scrollregion=cvB.bbox("all")))
make_rows(innerB)
add_wheel(cvB, cvB)
add_wheel(innerB, cvB)

# ---------------- C：不用画布，直接移动面板 ----------------
boxC = ctk.CTkFrame(cols, fg_color=PANEL, corner_radius=10)
boxC.grid(row=0, column=2, sticky="nsew", padx=6)
ctk.CTkLabel(boxC, text="C  不用画布（直接移动面板）",
             font=("Microsoft YaHei UI", 13, "bold"), text_color="#2ECC71").pack(pady=8)
wrapC = tk.Frame(boxC, bg=PANEL)
wrapC.pack(fill="both", expand=True, padx=6, pady=(0, 8))
holderC = tk.Frame(wrapC, bg=PANEL)
holderC.pack(fill="both", expand=True)
holderC.pack_propagate(False)
innerC = tk.Frame(holderC, bg=PANEL)
innerC.place(x=0, y=0, relwidth=1)
make_rows(innerC)
stateC = {"y": 0}
# 先让 inner 有正确宽度
holderC.update_idletasks()
add_wheel(holderC, None, holderC, innerC, stateC)
add_wheel(innerC, None, holderC, innerC, stateC)

root.mainloop()
