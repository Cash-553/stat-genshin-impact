# -*- coding: utf-8 -*-
"""自定义 UI 组件（两种完全不同类型的控件）

1) FloatingDropdown —— 浮动选择下拉（第 1 种）
   点一下 -> 在旁边弹出一个【独立浮层】选项列表
   - 浮层悬浮在其它内容之上，不把下面顶开、不改变页面布局
   - 选项可逐项点击，当前项有明确的选中标记（✓ + 高亮）
   - 选完自动关闭；点浮层以外也自动关闭
   - 展开时箭头方向翻转（▾ / ▴）

2) Accordion —— 可折叠设置区域（第 2 种）
   点标题栏 -> 在当前区域【原地展开】内部设置
   - 展开后内容直接出现在该区域内部，页面高度会变高
   - 带平滑过渡动画；箭头跟着翻转（▸ / ▾）
   - 再点一次收起

两者区别（必须分清）：
   Dropdown ：点 -> 旁边浮出 -> 选一个 -> 自动关（不改页面布局）
   Accordion：点 -> 原地撑开 -> 显示内部设置 -> 再点收起（页面变高）
"""
import customtkinter as ctk

import theme
from fonts import FONT

ARROW_DOWN = "▾"
ARROW_UP = "▴"
ARROW_RIGHT = "▸"


class FloatingDropdown(ctk.CTkFrame):
    """自定义浮动选择下拉（不是原生下拉框）

    性能要点（避免卡顿/拖影）：
    - 浮层的控件【只创建一次】，之后只是 place / place_forget，不再反复建控件
    - 浮层用【窗口内叠加层】，不开独立小窗口，避免跨窗口重绘残留
    """

    def __init__(self, master, values, variable=None, command=None,
                 height=34, font_size=14, placeholder="请选择", min_width=120):
        super().__init__(master, fg_color=theme.BTN, corner_radius=theme.RADIUS_BTN,
                         height=height, cursor="hand2")
        self.pack_propagate(False)
        self._values = [str(v) for v in values]
        self._var = variable if variable is not None else ctk.StringVar(
            value=self._values[0] if self._values else "")
        self._command = command
        self._font_size = font_size
        self._placeholder = placeholder
        self._popup = None
        self._items = []
        self._bound = False
        self._min_width = min_width

        self._lbl = ctk.CTkLabel(self, text="", font=(FONT, font_size),
                                 text_color=theme.TEXT, anchor="w")
        self._lbl.pack(side="left", fill="x", expand=True, padx=(11, 0))
        self._arrow = ctk.CTkLabel(self, text=ARROW_DOWN, font=(FONT, font_size),
                                   text_color=theme.DIM, width=20)
        self._arrow.pack(side="right", padx=(0, 8))

        for w in (self, self._lbl, self._arrow):
            try:
                w.bind("<Button-1>", self._on_click)
            except Exception:
                pass
        self._sync()

    # ---------- 工具 ----------

    def _host(self):
        """拿到根窗口（浮层要放在它上面）。

        注意：不能用 winfo_toplevel()，CustomTkinter 覆盖了 _root 属性，
        会让 tkinter 的 nametowidget 偶发报错。
        """
        w = self
        try:
            for _ in range(32):
                m = getattr(w, "master", None)
                if m is None:
                    break
                w = m
        except Exception:
            pass
        return w

    # ---------- 显示 ----------

    def _sync(self):
        try:
            v = str(self._var.get())
            self._lbl.configure(text=v if v else self._placeholder,
                                text_color=theme.TEXT if v else theme.DIM)
        except Exception:
            pass

    def set_values(self, values):
        self._values = [str(v) for v in values]
        self._popup = None

    def get(self):
        return self._var.get()

    def set(self, v):
        try:
            self._var.set(str(v))
        except Exception:
            pass
        self._sync()

    # ---------- 浮层（只建一次，之后复用）----------

    def _ensure_popup(self):
        if self._popup is not None:
            return
        try:
            host = self._host()
        except Exception:
            return
        pop = ctk.CTkFrame(host, fg_color=theme.CARD, corner_radius=8,
                           border_width=1, border_color=theme.BORDER,
                           width=max(self.winfo_width(), self._min_width), height=96)
        pop.pack_propagate(False)     # CustomTkinter 的 place 不接受 width/height，
                                      # 尺寸必须在控件创建时定好
        self._items = []
        for v in self._values:
            b = ctk.CTkButton(
                pop, text="　" + v, anchor="w", font=(FONT, self._font_size),
                fg_color="transparent", hover_color=theme.BTN_HOVER,
                text_color=theme.TEXT, corner_radius=6, height=28,
                command=lambda vv=v: self._select(vv),
            )
            b.pack(fill="x", padx=5, pady=1)
            self._items.append((v, b))
        self._popup = pop

    def _on_click(self, _e=None):
        if self._popup is not None and self._popup.winfo_ismapped():
            self._close()
        else:
            self._open()

    def _open(self):
        if not self._values:
            return
        self._ensure_popup()
        if self._popup is None:
            return
        try:
            # 刷新每个选项的选中状态
            cur = str(self._var.get())
            for v, b in self._items:
                sel = (v == cur)
                b.configure(text=("✓ " if sel else "　") + v,
                            fg_color=(theme.ACCENT if sel else "transparent"),
                            hover_color=(theme.ACCENT_DARK if sel else theme.BTN_HOVER),
                            text_color=("#FFFFFF" if sel else theme.TEXT))
            self.update_idletasks()
            host = self._host()
            w = max(self.winfo_width(), self._min_width)
            h = 28 * len(self._items) + 12
            x = self.winfo_rootx() - host.winfo_rootx()
            y = self.winfo_rooty() - host.winfo_rooty() + self.winfo_height() + 3
            if y + h > host.winfo_height() - 4:          # 下面放不下就往上翻
                y = max(2, self.winfo_rooty() - host.winfo_rooty() - h - 3)
            self._popup.configure(width=w, height=h)
            self._popup.place(x=x, y=y)
            self._popup.lift()
            self._arrow.configure(text=ARROW_UP, text_color=theme.ACCENT)
            self.after(60, self._bind_outside)
        except Exception:
            pass

    def _bind_outside(self):
        if self._bound:
            return
        try:
            self._root = self._host()
            self._root.bind_all("<Button-1>", self._on_global_click, add="+")
            self._root.bind_all("<MouseWheel>", self._on_scroll_close, add="+")
            self._bound = True
        except Exception:
            pass

    def _on_scroll_close(self, _e=None):
        """滚动时关掉浮层（否则会和内容脱节）"""
        self._close()

    def _on_global_click(self, event):
        if self._popup is None or not self._popup.winfo_ismapped():
            return
        try:
            px, py = self._popup.winfo_rootx(), self._popup.winfo_rooty()
            pw, ph = self._popup.winfo_width(), self._popup.winfo_height()
            if px <= event.x_root <= px + pw and py <= event.y_root <= py + ph:
                return      # 点在浮层里，交给选项自己处理
            if self.winfo_rootx() <= event.x_root <= self.winfo_rootx() + self.winfo_width() \
               and self.winfo_rooty() <= event.y_root <= self.winfo_rooty() + self.winfo_height():
                return      # 点在触发框上，交给它自己切换
        except Exception:
            pass
        self._close()

    def _select(self, v):
        try:
            self._var.set(v)
        except Exception:
            pass
        self._sync()
        self._close()
        if self._command:
            try:
                self._command(v)
            except Exception:
                pass

    def _close(self):
        try:
            if self._bound:
                self._root.unbind_all("<Button-1>")
                self._root.unbind_all("<MouseWheel>")
                self._bound = False
        except Exception:
            pass
        try:
            if self._popup is not None:
                self._popup.place_forget()
        except Exception:
            pass
        try:
            self._arrow.configure(text=ARROW_DOWN, text_color=theme.DIM)
        except Exception:
            pass


class Accordion(ctk.CTkFrame):
    """可折叠设置区域（原地展开/收起，带过渡动画）"""

    def __init__(self, master, icon, title, desc, build_body,
                 expanded=False, icon_size=20, title_size=16, desc_size=12,
                 on_change=None):
        super().__init__(master, corner_radius=theme.RADIUS_CARD, fg_color=theme.CARD,
                         border_width=1, border_color=theme.BORDER)
        self.pack(fill="x", pady=(0, 8))
        self._build_body = build_body
        self._built = False
        self._expanded = False
        self._anim = None
        self._title_size = title_size
        self._on_change = on_change

        head = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        head.pack(fill="x")
        self._head = head

        self._arrow = ctk.CTkLabel(head, text=ARROW_RIGHT, font=(FONT, title_size),
                                   text_color=theme.DIM, width=22)
        self._arrow.pack(side="right", padx=(6, 14))

        ic = ctk.CTkFrame(head, width=42, height=42, corner_radius=12, fg_color=theme.CARD_INNER)
        ic.pack(side="left", padx=(14, 12), pady=9)
        ic.pack_propagate(False)
        ctk.CTkLabel(ic, text=icon, font=(FONT, icon_size), text_color=theme.ACCENT).place(
            relx=0.5, rely=0.5, anchor="center")

        mid = ctk.CTkFrame(head, fg_color="transparent")
        mid.pack(side="left", fill="both", expand=True, pady=9)
        self._title = ctk.CTkLabel(mid, text=title, font=(FONT, title_size, "bold"),
                                   text_color=theme.TEXT, anchor="w")
        self._title.pack(anchor="w")
        self._desc = ctk.CTkLabel(mid, text=desc, font=(FONT, desc_size), text_color=theme.DIM,
                                  anchor="w", justify="left", wraplength=380)
        self._desc.pack(anchor="w", pady=(2, 0))

        for w in (self._head, ic, mid, self._title, self._desc, self._arrow):
            try:
                w.bind("<Button-1>", lambda e: self.toggle())
            except Exception:
                pass

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        if expanded:
            self.toggle()

    # ---------- 展开 / 收起 ----------

    def toggle(self):
        if self._anim:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self):
        if not self._built:
            try:
                self._build_body(self.body)
            except Exception:
                pass
            self._built = True
            # 新造出来的控件需要贴一次背景（动画过程中由 <Configure> 自己跟进）
            self._notify_change()
        try:
            self.body.pack(fill="x")
            self.update_idletasks()
            target = max(1, self.body.winfo_reqheight())
            self.body.configure(height=0)
            self.body.pack_propagate(False)
        except Exception:
            return
        self._animate(0, target, True)

    def _collapse(self):
        try:
            cur = max(1, self.body.winfo_height())
            self.body.pack_propagate(False)
            self.body.configure(height=cur)
        except Exception:
            return
        self._animate(cur, 0, False)

    def _animate(self, start, end, expanding):
        steps = 10

        def step(i):
            try:
                t = i / float(steps)
                self.body.configure(height=max(0, int(start + (end - start) * t)))
            except Exception:
                self._finish(expanding)
                return
            if i < steps:
                self._anim = self.after(16, lambda: step(i + 1))
            else:
                self._anim = None
                self._finish(expanding)

        step(1)

    def _notify_change(self):
        """展开/收起过程中通知外面（用来重贴玻璃背景）"""
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def _finish(self, expanding):
        try:
            if expanding:
                self.body.pack_propagate(True)
                self.body.configure(height=self.body.winfo_reqheight())
                self._arrow.configure(text=ARROW_DOWN, text_color=theme.ACCENT)
                self._expanded = True
            else:
                self.body.pack_forget()
                self.body.pack_propagate(True)
                self._arrow.configure(text=ARROW_RIGHT, text_color=theme.DIM)
                self._expanded = False
        except Exception:
            pass
        self._notify_change()

    def collapse_now(self):
        """立刻收起（不播动画）"""
        if self._anim:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None
        try:
            self.body.pack_forget()
            self.body.pack_propagate(True)
        except Exception:
            pass
        self._expanded = False
        try:
            self._arrow.configure(text=ARROW_RIGHT, text_color=theme.DIM)
        except Exception:
            pass
