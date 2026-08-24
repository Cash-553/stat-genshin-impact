# -*- coding: utf-8 -*-
"""
横向收益统计条
放在直播间里的小窗口：摩拉 / 素材 / 狗粮 三个格子，图标在上、数量在下。
图标可以在 设置→图标管理 的"统计条图标"里自己截取/更换。
"""
import time
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

import paths

ICONS_DIR = paths.icons_dir()

import theme
from fonts import FONT

BAR_BG = theme.BG
CARD = theme.CARD
BORDER = theme.BORDER
ACCENT = theme.ACCENT
TEXT = theme.TEXT
DIM = theme.DIM
RADIUS_CARD = theme.RADIUS_CARD


def _fmt_num(n):
    return f"{n:,}"


def _ensure_placeholder(slot_key, label):
    """生成默认占位图标（下划线开头，不影响识别）"""
    target = ICONS_DIR / f"_bar_{slot_key}.png"
    if target.exists():
        return target
    try:
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (64, 64), "#242424")
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([4, 4, 60, 60], radius=12, fill="#2A2A2A")
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
        except Exception:
            font = ImageFont.load_default()
        d.text((32, 32), label[0], fill="#4A90D9", font=font, anchor="mm")
        img.save(target)
    except Exception:
        return None
    return target


class StatBar(ctk.CTkToplevel):
    """横向统计条窗口"""

    def __init__(self, parent, stats_provider, settings_provider, on_closed=None):
        super().__init__(parent)
        self.title("收益统计条")
        self.overrideredirect(True)   # 无边框
        self.configure(fg_color=BAR_BG)
        self._drag_x = 0
        self._drag_y = 0

        self.stats_provider = stats_provider          # () -> 统计字典
        self.settings_provider = settings_provider    # () -> 统计条设置字典
        self.on_closed = on_closed
        self._slots = []                              # (图标标签, 数量标签, 插槽名, 标题)

        self._build()
        self._apply_topmost()
        self._refresh()
        self.after(500, self._loop)

    # ---------- 窗口操作（无边框，手动拖动/右键关闭）----------

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        try:
            self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")
        except Exception:
            pass

    # ---------- 界面 ----------

    def _build(self):
        # 三格：摩拉 / 材料 / 狗粮
        specs = [("slot1", "摩拉"), ("slot2", "材料"), ("slot3", "狗粮")]
        for key, title in specs:
            cell = ctk.CTkFrame(self, fg_color=CARD, corner_radius=RADIUS_CARD, width=126, height=112,
                               border_width=1, border_color=BORDER)
            cell.pack(side="left", padx=5, pady=8)
            cell.pack_propagate(False)

            ctk.CTkLabel(cell, text=title, font=(FONT, 11), text_color=DIM).pack(pady=(9, 2))
            icon_lbl = ctk.CTkLabel(cell, text="", width=36, height=36)
            icon_lbl.pack()
            count_lbl = ctk.CTkLabel(cell, text="0", font=(FONT, 18, "bold"), text_color=TEXT)
            count_lbl.pack(pady=(2, 6))
            self._slots.append((icon_lbl, count_lbl, key, title))
            # 整个格子都可以按住拖动，右键关闭
            cell.bind("<Button-1>", self._drag_start)
            cell.bind("<B1-Motion>", self._drag_move)
            cell.bind("<Button-3>", lambda e: self.on_closing())

    def _apply_topmost(self):
        s = self.settings_provider() or {}
        try:
            self.attributes("-topmost", bool(s.get("always_on_top", True)))
        except Exception:
            pass

    # ---------- 数据刷新 ----------

    def _slot_icon_file(self, key):
        s = self.settings_provider() or {}
        fname = s.get(key)
        if fname:
            p = ICONS_DIR / fname
            if p.exists():
                return p
        return None

    def _refresh(self):
        st = self.stats_provider() or {}
        materials = st.get("material_total", 0) or (st.get("monster", 0) + st.get("normal", 0))
        values = {
            "slot1": _fmt_num(st.get("mora", 0)),
            "slot2": str(materials),
            "slot3": str(st.get("artifact", 0)),
        }
        for icon_lbl, count_lbl, key, title in self._slots:
            count_lbl.configure(text=values.get(key, "0"))
            p = self._slot_icon_file(key)
            if p is None:
                p = _ensure_placeholder(key, title)
            if p:
                try:
                    img = Image.open(p).convert("RGBA")
                    img = img.resize((36, 36), Image.LANCZOS)
                    icon_lbl.configure(
                        image=ctk.CTkImage(light_image=img, dark_image=img, size=(36, 36)),
                        text="",
                    )
                except Exception:
                    pass

    def _loop(self):
        try:
            self._refresh()
        except Exception:
            pass
        try:
            if self.winfo_exists():
                self.after(500, self._loop)
        except Exception:
            pass

    # ---------- 关闭 ----------

    def close_bar(self):
        try:
            self.destroy()
        except Exception:
            pass

    def on_closing(self):
        if self.on_closed:
            try:
                self.on_closed()
            except Exception:
                pass
        self.close_bar()
