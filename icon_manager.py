# -*- coding: utf-8 -*-
"""
图标管理窗口（设置 → 图标管理）

只管理「收益统计条」的格子图标（直播间小窗口）：
- 当前 3 格：摩拉 / 材料 / 狗粮
- 以后清单整理好会加第 4 格（自动出现）

功能：预览格子图标、从电脑换图、从游戏屏幕截取。
图标文件放在 icons 文件夹（_bar_slot*.png），与识别无关。
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


class IconManagerWindow(ctk.CTkToplevel):
    def __init__(self, parent, on_change=None):
        super().__init__(parent)
        self.title("图标管理")
        self.geometry("680x430")
        self.resizable(False, False)

        self.on_change = on_change
        self.settings = config_manager.load_settings()
        self._capture = None  # 截图器：用到才创建
        self._photos = []     # 保存图片引用，防止被回收

        self._build_ui()
        self._refresh_slots()

    # ---------- 界面 ----------

    def _build_ui(self):
        # 顶部说明
        ctk.CTkLabel(
            self, text="🖼 收益统计条图标", font=(FONT, 16, "bold"), text_color=TEXT,
        ).pack(pady=(16, 2))
        ctk.CTkLabel(
            self, text="管理直播间统计条格子显示的图标，与识别无关。\n更换后需重启程序生效（统计条会同步更新）。",
            font=(FONT, 11), text_color=DIM, justify="center",
        ).pack(pady=(0, 10))

        # 田字型 2×2 网格容器
        self.cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.cards_frame.pack(fill="both", expand=True, padx=24, pady=(0, 6))
        for c in range(2):
            self.cards_frame.grid_columnconfigure(c, weight=1)

        # 底部：置顶 + 提示
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=24, pady=(0, 12))

        self.topmost_var = ctk.BooleanVar(value=bool((self.settings.get("stat_bar") or {}).get("always_on_top", True)))
        ctk.CTkSwitch(
            bottom, text="统计条置顶显示", variable=self.topmost_var,
            onvalue=True, offvalue=False, command=self.on_toggle_topmost,
            font=(FONT, 12), fg_color=ACCENT, progress_color=ACCENT_DARK, text_color=TEXT,
        ).pack(anchor="w")

        ctk.CTkLabel(
            self, text="💡 图标文件保存在 icons 文件夹，可随时更换。",
            font=(FONT, 10), text_color=DIM,
        ).pack(side="bottom", pady=(0, 8))

    def _refresh_slots(self):
        """重建所有格子卡片（田字型 2×2）"""
        for w in self.cards_frame.winfo_children():
            w.destroy()
        for idx, (slot_key, label) in enumerate(SLOTS):
            row = idx // 2
            col = idx % 2
            self._make_slot_card(slot_key, label, row, col)

    def _make_slot_card(self, slot_key, label, row=0, col=0):
        """一个格子卡片（田字型网格）：大图标预览 + 名称 + 操作按钮"""
        card = ctk.CTkFrame(self.cards_frame, corner_radius=RADIUS_CARD, fg_color=CARD,
                           border_width=1, border_color=BORDER)
        card.grid(row=row, column=col, padx=8, pady=6, sticky="nsew")
        card.grid_propagate(False)
        card.configure(width=200, height=130)

        # 卡片内部：左大图标 + 右侧信息
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=10)

        # 左：图标预览（大图，正方形不被压扁）
        preview = ctk.CTkLabel(inner, text="", width=70, height=70)
        preview.pack(side="left", padx=(0, 10))
        if not hasattr(self, "_slot_previews"):
            self._slot_previews = {}
        self._slot_previews[slot_key] = preview
        self._update_slot_preview(slot_key, label)

        # 右：名称 + 按钮
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="left", fill="y", expand=True)
        ctk.CTkLabel(right, text=label, font=(FONT, 13, "bold"), text_color=TEXT).pack(anchor="w", pady=(2, 6))
        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack(anchor="w")
        ctk.CTkButton(
            btn_row, text="📷", font=(FONT, 12), width=40, height=28,
            corner_radius=RADIUS_BTN,
            fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
            command=lambda k=slot_key, l=label: self.on_capture_slot(k, l),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            btn_row, text="更换", font=(FONT, 12), width=56, height=28,
            corner_radius=RADIUS_BTN,
            fg_color=ACCENT, hover_color=ACCENT_DARK, text_color="#FFFFFF",
            command=lambda k=slot_key, l=label: self.on_replace_slot(k, l),
        ).pack(side="left", padx=3)

    def _update_slot_preview(self, slot_key, label):
        preview = self._slot_previews.get(slot_key)
        if preview is None:
            return
        self.settings = config_manager.load_settings()
        bar = self.settings.get("stat_bar") or {}
        fname = bar.get(slot_key)
        icon_file = ICONS_DIR / fname if fname else None
        if icon_file and icon_file.exists():
            photo = self._load_preview(icon_file, 72)
            if photo is not None:
                preview.configure(image=photo, text="")
                return
        preview.configure(image=None, text="未设置", text_color=DIM, font=(FONT, 11))

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
        )
        try:
            region = region_selector.select_region(self)
        except Exception as e:
            messagebox.showerror("失败", f"截取失败：{e}")
            return
        if not region:
            return
        try:
            frame = self._get_capture().grab(region)
            from PIL import Image as PILImage
            img = PILImage.fromarray(frame[:, :, :3][:, :, ::-1])
            ICONS_DIR.mkdir(parents=True, exist_ok=True)
            fname = f"_bar_{slot_key}.png"
            self._auto_trim(img).save(ICONS_DIR / fname, format="PNG")
            self._save_slot_settings(slot_key, fname)
            messagebox.showinfo("成功", f"「{label}」图标已保存！")
            self._refresh_slots()
            self._notify_change()
        except Exception as e:
            messagebox.showerror("失败", f"截取失败：{e}")

    def on_replace_slot(self, slot_key, label):
        """从电脑选择图片作为格子图标"""
        path = filedialog.askopenfilename(
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
            ICONS_DIR.mkdir(parents=True, exist_ok=True)
            fname = f"_bar_{slot_key}.png"
            # webp 等格式统一转 PNG 保存
            self._auto_trim(img).save(ICONS_DIR / fname, format="PNG")
            self._save_slot_settings(slot_key, fname)
            messagebox.showinfo("成功", f"「{label}」图标已更新！")
            self._refresh_slots()
            self._notify_change()
        except Exception as e:
            messagebox.showerror("失败", f"保存失败：{e}")

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

    def on_close(self):
        if self._capture is not None:
            try:
                self._capture.close()
            except Exception:
                pass
        self.destroy()
