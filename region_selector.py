# -*- coding: utf-8 -*-
"""
区域框选模块
打开一个半透明的全屏遮罩，让你用鼠标拖一个框，
框住游戏画面里的"掉落提示区域"。
按 Esc 取消，松开鼠标完成。

技术说明：
遮罩用主程序自己的 Toplevel 创建（同一个 Tcl 解释器），
避免"第二个解释器的 mainloop 销毁后不退出"的问题。
"""
import tkinter as tk
import mss

import theme
from fonts import FONT

# 颜色定义（Win11 深色）
MASK_COLOR = theme.BG      # 遮罩（用窗口背景色）
RECT_COLOR = theme.ACCENT  # 选框（强调色）


def select_region(parent=None):
    """
    弹出全屏框选界面，返回选中的区域字典
    {"x":.., "y":.., "w":.., "h":..}（屏幕绝对坐标）
    用户按 Esc 取消时返回 None
    """
    with mss.MSS() as sct:
        # 整个虚拟屏幕的范围（多显示器也适用）
        v = sct.monitors[1]
    vx, vy, vw, vh = v["left"], v["top"], v["width"], v["height"]

    result = {"done": False, "region": None}

    # 优先用主程序的 Toplevel（同一个 Tcl 解释器，稳定可靠）
    if parent is not None:
        root = tk.Toplevel(parent)
        root.withdraw()  # 先隐藏，配置好再显示
    else:
        root = tk.Tk()

    root.overrideredirect(True)            # 去掉标题栏
    root.attributes("-topmost", True)      # 永远在最前
    root.attributes("-alpha", 0.35)        # 半透明
    root.geometry(f"{vw}x{vh}+{vx}+{vy}")  # 覆盖整个虚拟屏幕
    root.configure(bg=MASK_COLOR)

    # 强制把遮罩置顶（确保不被其他窗口挡住）
    try:
        import ctypes
        hwnd = int(root.winfo_id())
        # HWND_TOPMOST = -1; SWP_NOSIZE|SWP_NOMOVE|SWP_SHOWWINDOW
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    except Exception:
        pass

    if parent is not None:
        root.deiconify()
    root.lift()

    canvas = tk.Canvas(root, bg=MASK_COLOR, highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)

    # 提示文字（显示在左上角）
    canvas.create_text(
        vx + 12, vy + 12, anchor="nw", fill="#ffffff",
        text="拖动鼠标框住【掉落提示区域】，松开完成。按 Esc 取消。\n"
             "看不到这个界面？游戏可能全屏独占，请按 Esc 后把游戏改成无边框窗口。",
        font=(FONT, 14, "bold"),
    )
    start = [0, 0]
    rect_id = [None]

    def finish(region):
        result["region"] = region
        result["done"] = True
        # 注意：不要调用 root.quit()！它会连带结束主程序的整个事件循环导致闪退。
        # wait_window/mainloop 会在窗口销毁后自动返回。
        try:
            root.destroy()   # 销毁遮罩窗口
        except Exception:
            pass

    def on_press(event):
        # 鼠标按下：记录起点，用窗口内坐标
        start[0] = event.x_root - vx
        start[1] = event.y_root - vy
        if rect_id[0] is not None:
            canvas.delete(rect_id[0])
        rect_id[0] = canvas.create_rectangle(
            start[0], start[1], start[0], start[1],
            outline=RECT_COLOR, width=3,
        )

    def on_drag(event):
        if rect_id[0] is None:
            return
        cx, cy = event.x_root - vx, event.y_root - vy
        canvas.coords(rect_id[0], start[0], start[1], cx, cy)

    def on_release(event):
        if rect_id[0] is None:
            return
        x1, y1, x2, y2 = canvas.coords(rect_id[0])
        left, top = int(min(x1, x2)) + vx, int(min(y1, y2)) + vy
        w, h = int(abs(x2 - x1)), int(abs(y2 - y1))
        # 太小就当没选
        if w >= 20 and h >= 20:
            finish({"x": left, "y": top, "w": w, "h": h})
        else:
            finish(None)

    def on_escape(event):
        finish(None)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.focus_force()
    if parent is not None:
        root.wait_window()
    else:
        root.mainloop()
    return result["region"]
