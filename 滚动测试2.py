# -*- coding: utf-8 -*-
"""
滚动方式对比测试（v3 —— 纯 tkinter，不用 CustomTkinter）

这一版专门用来区分：
    D  纯 tkinter 画布滚动           —— 基准
    E  纯 tkinter 的 Text 控件滚动   —— Tk 原生自带的滚动实现
    F  D 的做法 + 每次滚动后强制整窗重绘 —— 候选修复方案

用法（请用 3.13 跑，也就是 Tk 8.6）：
    py -3.13 滚动测试2.py

然后分别把鼠标放进 D / E / F 快速上下滚，看哪几个有拖影。
"""
import ctypes
import tkinter as tk

ROWS = 30
ROW_H = 46
BG = "#101010"
PANEL = "#1D1D1D"
COLORS = [
    "#E74C3C", "#E67E22", "#F1C40F", "#2ECC71", "#1ABC9C", "#3498DB",
    "#9B59B6", "#E84393", "#D35400", "#16A085", "#27AE60", "#2980B9",
]

u = ctypes.windll.user32


def force_repaint(widget):
    """强制让 Windows 重画整个控件（候选修复方案）"""
    try:
        hwnd = int(widget.winfo_id())
        u.InvalidateRect(ctypes.c_void_p(hwnd), None, False)
        u.UpdateWindow(ctypes.c_void_p(hwnd))
    except Exception:
        pass


def fill_rows(parent):
    for i in range(ROWS):
        c = COLORS[i % len(COLORS)]
        f = tk.Frame(parent, bg=c, height=ROW_H)
        f.pack(fill="x", pady=2)
        f.pack_propagate(False)
        tk.Label(f, text=f"第 {i+1} 行　快速滚动看残影", bg=c, fg="#FFFFFF",
                 font=("Microsoft YaHei UI", 12), anchor="w").pack(side="left", padx=12)


def bind_wheel(w, handler):
    w.bind("<MouseWheel>", handler)
    for ch in w.winfo_children():
        bind_wheel(ch, handler)


root = tk.Tk()
root.title("滚动对比测试 v3（纯 tkinter）")
root.geometry("1240x640")
root.configure(bg=BG)

tk.Label(root, text="分别把鼠标放进 D / E / F，用滚轮【快速上下滚动】，看哪几个留下残影",
         bg=BG, fg="#FFFFFF", font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(12, 8))

cols = tk.Frame(root, bg=BG)
cols.pack(fill="both", expand=True, padx=12, pady=(0, 12))
for i in range(3):
    cols.grid_columnconfigure(i, weight=1)
cols.grid_rowconfigure(0, weight=1)


def make_box(col, title, color):
    box = tk.Frame(cols, bg=PANEL)
    box.grid(row=0, column=col, sticky="nsew", padx=6)
    tk.Label(box, text=title, bg=PANEL, fg=color,
             font=("Microsoft YaHei UI", 13, "bold")).pack(pady=8)
    body = tk.Frame(box, bg=PANEL)
    body.pack(fill="both", expand=True, padx=6, pady=(0, 8))
    return body


# ---------------- D：纯 tkinter 画布滚动 ----------------
bodyD = make_box(0, "D　纯 tkinter 画布滚动", "#F1C40F")
cvD = tk.Canvas(bodyD, bg=PANEL, highlightthickness=0, bd=0)
sbD = tk.Scrollbar(bodyD, orient="vertical", command=cvD.yview)
cvD.configure(yscrollcommand=sbD.set)
sbD.pack(side="right", fill="y")
cvD.pack(side="left", fill="both", expand=True)
innerD = tk.Frame(cvD, bg=PANEL)
widD = cvD.create_window((0, 0), window=innerD, anchor="nw")
cvD.bind("<Configure>", lambda e: cvD.itemconfigure(widD, width=e.width))
innerD.bind("<Configure>", lambda e: cvD.configure(scrollregion=cvD.bbox("all")))
fill_rows(innerD)
bind_wheel(cvD, lambda e: cvD.yview_scroll(-1 if e.delta > 0 else 1, "units"))
bind_wheel(innerD, lambda e: cvD.yview_scroll(-1 if e.delta > 0 else 1, "units"))

# ---------------- E：纯 tkinter 的 Text 控件 ----------------
bodyE = make_box(1, "E　tkinter Text 控件滚动", "#3498DB")
wrapE = tk.Frame(bodyE, bg=PANEL)
wrapE.pack(fill="both", expand=True)
txt = tk.Text(wrapE, bg=PANEL, fg="#FFFFFF", bd=0, highlightthickness=0,
              font=("Microsoft YaHei UI", 12), wrap="none", cursor="arrow")
sbE = tk.Scrollbar(wrapE, orient="vertical", command=txt.yview)
txt.configure(yscrollcommand=sbE.set)
sbE.pack(side="right", fill="y")
txt.pack(side="left", fill="both", expand=True)
for i in range(ROWS):
    c = COLORS[i % len(COLORS)]
    tag = f"t{i}"
    txt.tag_configure(tag, background=c, foreground="#FFFFFF", spacing1=4, spacing3=4)
    txt.insert("end", f"第 {i+1} 行　快速滚动看残影\n", tag)
txt.configure(state="disabled")
txt.bind("<MouseWheel>", lambda e: txt.yview_scroll(-1 if e.delta > 0 else 1, "units"))

# ---------------- F：画布滚动 + 强制整窗重绘 ----------------
bodyF = make_box(2, "F　画布滚动 + 强制重绘（候选方案）", "#2ECC71")
cvF = tk.Canvas(bodyF, bg=PANEL, highlightthickness=0, bd=0)
sbF = tk.Scrollbar(bodyF, orient="vertical", command=cvF.yview)
cvF.configure(yscrollcommand=sbF.set)
sbF.pack(side="right", fill="y")
cvF.pack(side="left", fill="both", expand=True)
innerF = tk.Frame(cvF, bg=PANEL)
widF = cvF.create_window((0, 0), window=innerF, anchor="nw")
cvF.bind("<Configure>", lambda e: cvF.itemconfigure(widF, width=e.width))
innerF.bind("<Configure>", lambda e: cvF.configure(scrollregion=cvF.bbox("all")))
fill_rows(innerF)


def wheel_F(e):
    cvF.yview_scroll(-1 if e.delta > 0 else 1, "units")
    force_repaint(cvF)          # ★ 关键：每次滚动后强制整窗重画


bind_wheel(cvF, wheel_F)
bind_wheel(innerF, wheel_F)

root.mainloop()
