# -*- coding: utf-8 -*-
"""
图标管理窗口（设置 → 外观 → 统计条图标）

只管理「收益统计条」的格子图标（直播间小窗口）：
- 当前 3 格：摩拉 / 材料 / 狗粮

功能：预览格子图标、从电脑换图、从游戏屏幕截取、重置回内置图标。
自定义图标保存为 icons/_bar_my_slotN.png，
【不会覆盖内置的 _bar_slotN.png】—— 所以「重置」随时能把内置图标找回来。
"""
import os
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

import config_manager
import paths
import region_selector
from capture import ScreenCapture

import theme
from fonts import FONT
from ui_widgets import FramelessWindow

ACCENT = theme.ACCENT
ACCENT_DARK = theme.ACCENT_DARK
TEXT = theme.TEXT
DIM = theme.DIM
CARD = theme.CARD
CARD_INNER = theme.CARD_INNER
BORDER = theme.BORDER
BTN = theme.BTN
BTN_HOVER = theme.BTN_HOVER
BAD = theme.BAD
RADIUS_CARD = theme.RADIUS_CARD
RADIUS_BTN = theme.RADIUS_BTN
ICONS_DIR = paths.icons_dir()

# 统计条格子定义：当前3格，以后清单整理好加第4格
SLOTS = [
    ("slot1", "摩拉"),
    ("slot2", "材料"),
    ("slot3", "狗粮"),
]


def _builtin_name(slot_key):
    """内置图标文件名（打包时自带，用户不该覆盖它）"""
    return f"_bar_{slot_key}.png"


def _custom_name(slot_key):
    """用户自定义的图标文件名（换图/截图都写这个）"""
    return f"_bar_my_{slot_key}.png"


class IconManagerWindow(FramelessWindow):
    def __init__(self, parent, on_change=None, on_closed=None):
        super().__init__(parent, title="🖼  统计条图标管理", width=700, height=470,
                         modal=False, on_close=on_closed)

        self.on_change = on_change
        self.settings = config_manager.load_settings()
        self._capture = None  # 截图器：用到才创建
        self._photos = []     # 保存图片引用，防止被回收
        self._slot_previews = {}
        self._slot_state = {}  # 每格下面那行小字（内置图标 / 自定义图标）

        self._build_ui()
        self._refresh_slots()

    # ---------- 界面 ----------

    def _build_ui(self):
        root = self.body

        ctk.CTkLabel(
            root, text="管理直播间收益统计条 3 个格子显示的图标，与识别无关。",
            font=(FONT, 13), text_color=DIM,
        ).pack(pady=(12, 8))

        # 田字型 2×2 网格容器（3 个格子 + 1 个「重置」卡片）
        self.cards_frame = ctk.CTkFrame(root, fg_color="transparent")
        self.cards_frame.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        for c in range(2):
            self.cards_frame.grid_columnconfigure(c, weight=1)

        # 底部：置顶开关
        bottom = ctk.CTkFrame(root, corner_radius=RADIUS_CARD, fg_color=CARD,
                              border_width=1, border_color=BORDER)
        bottom.pack(fill="x", padx=28, pady=(2, 14))
        self.topmost_var = ctk.BooleanVar(
            value=bool((self.settings.get("stat_bar") or {}).get("always_on_top", True)))
        ctk.CTkSwitch(
            bottom, text="统计条置顶显示", variable=self.topmost_var,
            onvalue=True, offvalue=False, command=self.on_toggle_topmost,
            font=(FONT, 15), fg_color="#5A5A5A", progress_color=ACCENT, text_color=TEXT,
        ).pack(anchor="w", padx=16, pady=12)

    def _refresh_slots(self):
        """重建所有格子卡片（田字型 2×2）"""
        for w in self.cards_frame.winfo_children():
            w.destroy()
        self._slot_previews = {}
        self._slot_state = {}
        for idx, (slot_key, label) in enumerate(SLOTS):
            self._make_slot_card(slot_key, label, idx // 2, idx % 2)
        # 第 4 格：重置
        self._make_reset_card(3 // 2, 3 % 2)

    def _make_slot_card(self, slot_key, label, row=0, col=0):
        """一个格子卡片（田字型网格）：大图标预览 + 名称 + 操作按钮"""
        card = ctk.CTkFrame(self.cards_frame, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=BORDER)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        card.grid_propagate(False)
        card.configure(width=300, height=140)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=10)

        box = ctk.CTkFrame(inner, width=78, height=78, corner_radius=12, fg_color=CARD_INNER)
        box.pack(side="left", padx=(0, 12))
        box.pack_propagate(False)
        preview = ctk.CTkLabel(box, text="", width=70, height=70)
        preview.place(relx=0.5, rely=0.5, anchor="center")
        self._slot_previews[slot_key] = preview

        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="left", fill="y", expand=True)
        ctk.CTkLabel(right, text=label, font=(FONT, 16, "bold"),
                     text_color=TEXT).pack(anchor="w", pady=(4, 2))
        self._slot_state[slot_key] = ctk.CTkLabel(
            right, text="", font=(FONT, 12), text_color=DIM)
        self._slot_state[slot_key].pack(anchor="w", pady=(0, 8))
        # 注意：状态小字要在建好之后再刷新，否则第一遍刷不到它
        self._update_slot_preview(slot_key)

        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack(anchor="w")
        ctk.CTkButton(
            btn_row, text="📷", font=(FONT, 15), width=40, height=28,
            corner_radius=RADIUS_BTN,
            fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
            command=lambda k=slot_key, l=label: self.on_capture_slot(k, l),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_row, text="更换", font=(FONT, 14), width=64, height=28,
            corner_radius=RADIUS_BTN,
            fg_color=ACCENT, hover_color=ACCENT_DARK, text_color="#FFFFFF",
            command=lambda k=slot_key, l=label: self.on_replace_slot(k, l),
        ).pack(side="left")

    def _make_reset_card(self, row, col):
        card = ctk.CTkFrame(self.cards_frame, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=BORDER)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        card.grid_propagate(False)
        card.configure(width=300, height=140)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=12)
        ctk.CTkLabel(inner, text="↺  全部重置", font=(FONT, 16, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(inner, text="把三个格子都恢复成程序内置的图标，\n"
                                 "并删掉你自己换的那些。",
                     font=(FONT, 12), text_color=DIM, justify="left").pack(anchor="w", pady=(2, 10))
        ctk.CTkButton(
            inner, text="重置为内置图标", font=(FONT, 14), height=32,
            corner_radius=RADIUS_BTN,
            fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
            command=self.on_reset_all,
        ).pack(anchor="w")

    def _update_slot_preview(self, slot_key):
        preview = self._slot_previews.get(slot_key)
        if preview is None:
            return
        self.settings = config_manager.load_settings()
        bar = self.settings.get("stat_bar") or {}
        fname = bar.get(slot_key)
        icon_file = ICONS_DIR / fname if fname else None
        is_custom = bool(fname) and fname == _custom_name(slot_key)
        if icon_file and icon_file.exists():
            photo = self._load_preview(icon_file, 66)
            if photo is not None:
                preview.configure(image=photo, text="")
                st = self._slot_state.get(slot_key)
                if st is not None:
                    st.configure(text="自定义图标" if is_custom else "内置图标",
                                 text_color=ACCENT if is_custom else DIM)
                return
        preview.configure(image=None, text="未设置", text_color=DIM, font=(FONT, 12))
        st = self._slot_state.get(slot_key)
        if st is not None:
            st.configure(text="文件丢失", text_color=BAD)

    # ---------- 工具 ----------

    def _load_preview(self, icon_file, size):
        """加载图标为 CTkImage（适配高DPI缩放）"""
        try:
            from PIL import Image as PILImage
            with PILImage.open(icon_file) as pil:
                pil = pil.convert("RGBA")
                pil = pil.resize((size, size), PILImage.LANCZOS)
                img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
            self._photos.append(img)
            return img
        except Exception:
            return None

    def _get_capture(self):
        if self._capture is None:
            self._capture = ScreenCapture()
        return self._capture

    def _save_slot_settings(self, slot_key, fname):
        self.settings = config_manager.load_settings()
        bar = dict(self.settings.get("stat_bar") or {})
        bar[slot_key] = fname
        self.settings["stat_bar"] = bar
        config_manager.save_settings(self.settings)

    # ---------- 操作 ----------

    def on_capture_slot(self, slot_key, label):
        """从屏幕截取格子图标"""
        messagebox.showinfo(
            "截取提示",
            f"接下来框选【{label}】的图标。\n\n"
            "· 框得越贴近图标越好\n"
            "· 看不到框选界面请按 Esc 取消，把游戏改成无边框窗口",
            parent=self,
        )
        try:
            region = region_selector.select_region(self)
        except Exception as e:
            messagebox.showerror("失败", f"截取失败：{e}", parent=self)
            return
        if not region:
            return
        try:
            frame = self._get_capture().grab(region)
            from PIL import Image as PILImage
            img = PILImage.fromarray(frame[:, :, :3][:, :, ::-1])
            self._write_icon(slot_key, img)
            messagebox.showinfo("成功", f"「{label}」图标已保存！", parent=self)
        except Exception as e:
            messagebox.showerror("失败", f"截取失败：{e}", parent=self)

    def on_replace_slot(self, slot_key, label):
        """从电脑选择图片作为格子图标"""
        path = filedialog.askopenfilename(
            parent=self,
            title=f"选择「{label}」图标的图片",
            filetypes=[
                ("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                ("PNG 图片", "*.png"),
                ("所有图片", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
            ],
        )
        if not path:
            return
        try:
            from PIL import Image as PILImage
            img = PILImage.open(path).convert("RGBA")
            self._write_icon(slot_key, img)
            messagebox.showinfo("成功", f"「{label}」图标已更新！", parent=self)
        except Exception as e:
            messagebox.showerror("失败", f"保存失败：{e}", parent=self)

    def _write_icon(self, slot_key, img):
        """把图标写进 icons 文件夹（用自定义文件名，不动内置的那份）"""
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        fname = _custom_name(slot_key)
        self._auto_trim(img).save(ICONS_DIR / fname, format="PNG")
        self._save_slot_settings(slot_key, fname)
        self._refresh_slots()
        self._notify_change()

    def on_reset_all(self):
        """重置：三个格子都恢复成内置图标，并删掉用户自己换的那些"""
        if not messagebox.askyesno(
                "确认重置",
                "要把 3 个格子都恢复成内置图标吗？\n（你自己换的图标文件会被删掉）",
                parent=self):
            return
        removed = 0
        for slot_key, _label in SLOTS:
            f = ICONS_DIR / _custom_name(slot_key)
            if f.exists():
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
            self._save_slot_settings(slot_key, _builtin_name(slot_key))
        self._refresh_slots()
        self._notify_change()

        missing = [l for k, l in SLOTS if not (ICONS_DIR / _builtin_name(k)).exists()]
        if missing:
            messagebox.showwarning(
                "重置完成（有缺文件）",
                "已恢复成内置图标，但下面这些内置图标文件找不到了：\n  "
                + "、".join(missing)
                + "\n\n重新解压一份发布包，把 icons 文件夹覆盖回来即可。",
                parent=self)
        else:
            messagebox.showinfo("重置完成", f"已恢复内置图标，删掉了 {removed} 个自定义图标。",
                                parent=self)

    def on_toggle_topmost(self):
        bar = dict(self.settings.get("stat_bar") or {})
        bar["always_on_top"] = bool(self.topmost_var.get())
        self.settings["stat_bar"] = bar
        config_manager.save_settings(self.settings)

    @staticmethod
    def _auto_trim(img, margin=4):
        """自动去掉图标四周的纯色边框，让图标更紧凑"""
        import numpy as np
        a = np.array(img.convert("RGB"))
        h, w = a.shape[:2]
        if h < 20 or w < 20:
            return img
        corner = a[0, 0].astype(int)
        diff = np.abs(a.astype(int) - corner).sum(axis=2)
        ys, xs = np.where(diff > 30)
        if len(xs) == 0:
            return img
        x0 = max(0, int(xs.min()) - margin)
        y0 = max(0, int(ys.min()) - margin)
        x1 = min(w, int(xs.max()) + margin + 1)
        y1 = min(h, int(ys.max()) + margin + 1)
        return img.crop((x0, y0, x1, y1))

    def _notify_change(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def close(self):
        if self._capture is not None:
            try:
                self._capture.close()
            except Exception:
                pass
            self._capture = None
        super().close()
