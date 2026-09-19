# -*- coding: utf-8 -*-
"""各个页面的搭建 + 卡片工厂 + 页面切换。

页面是懒加载的：只有第一次切到某一页才建它（全部一次建完要 1.7 秒以上）。
注意各页面的 _build_page_* 里都【不调用 grid()】—— 统一由 _grid_page 控制，
否则后台预建页面时会「闪一下」。"""
from ui_base import (
    CARD, CARD_INNER, ACCENT, ACCENT_DARK, TEXT, DIM, SWITCH_OFF, BAD, NAV_ON, BTN, BTN_HOVER, DANGER, DANGER_HOVER, RADIUS_CARD, RADIUS_BTN, RADIUS_INNER, FONT,
)
import customtkinter as ctk
from pathlib import Path

import theme
from ui_widgets import FloatingDropdown, Accordion
import config_manager



class PagesMixin:
    def _prebuild_pages(self, *keys):
        """按顺序、间隔着预建页面，避免集中在一起卡顿"""
        keys = list(keys)
        if not keys:
            return
        k = keys.pop(0)
        try:
            if k != getattr(self, "_current_page", None):
                self._ensure_page(k)
        except Exception:
            pass
        if keys:
            self.after(150, lambda: self._prebuild_pages(*keys))

    def _build_page_launch(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="启动", font=(FONT, 23, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        # ---- 顶部：大标题 + 状态 + 装饰区 ----
        header = self._make_card(page)
        header.grid(row=1, column=0, sticky="ew")

        deco = ctk.CTkFrame(header, width=104, height=68, corner_radius=RADIUS_CARD,
                            fg_color=CARD_INNER, border_width=1, border_color=theme.BORDER)
        deco.pack(side="right", padx=(8, 12), pady=9)
        deco.pack_propagate(False)
        ctk.CTkLabel(deco, text="🍃", font=(FONT, 23)).pack(pady=(6, 0))
        ctk.CTkLabel(deco, text="StatGI V0.7", font=(FONT, 11, "bold"), text_color=ACCENT).pack()

        hl = ctk.CTkFrame(header, fg_color="transparent")
        hl.pack(side="left", fill="both", expand=True, padx=16, pady=8)
        ctk.CTkLabel(hl, text="🍃  StatGI", font=(FONT, 24, "bold"), text_color=TEXT).pack(anchor="w")
        _r1 = ctk.CTkFrame(hl, fg_color="transparent")
        _r1.pack(anchor="w")
        self.launch_status_label = ctk.CTkLabel(_r1, text="🟢 未开始", font=(FONT, 13, "bold"), text_color=BAD)
        self.launch_status_label.pack(side="left")
        self.launch_region_label = ctk.CTkLabel(_r1, text="　📍 自动检测游戏窗口", font=(FONT, 11), text_color=DIM)
        self.launch_region_label.pack(side="left")
        self.last_event_label = ctk.CTkLabel(hl, text="🕐 最后识别：—", font=(FONT, 11), text_color=DIM)
        self.last_event_label.pack(anchor="w")

        # ---- 功能卡片：横向长条（左图标 / 中标题说明 / 右按钮）----
        rows = ctk.CTkFrame(page, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        page.grid_rowconfigure(2, weight=1)
        rows.grid_columnconfigure(0, weight=1)

        self.start_card, self.start_card_title, self.start_card_btn = self._make_row_card(
            rows, "▶", "开始监测", "自动找到游戏窗口并识别掉落收益",
            "开始", self.on_start_stop, accent=True)
        self.start_card.pack(fill="x", pady=(0, 6))

        # 「清空」卡片：第 1 种浮动下拉选清空内容 + 右边按钮执行
        self._make_clear_card(rows)

        # 「重新框选」折叠区：第 2 种（点标题原地展开，里面含诊断截图）
        _acc = Accordion(rows, "🎯", "重新框选",
                         "手动指定要识别的屏幕区域；里面还有「诊断截图」（一般都不用）",
                         self._build_reselect_body, on_change=self._apply_background)
        _acc.pack(fill="x", pady=(0, 6))
        return page

    def _build_reselect_body(self, parent):
        """「重新框选」展开后的内容：重新框选 + 诊断截图"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkButton(
            row, text="🎯 重新框选", font=(FONT, 15), height=36, corner_radius=RADIUS_BTN,
            fg_color=BTN, hover_color=BTN_HOVER, command=self.on_reselect,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row, text="📷 诊断截图", font=(FONT, 15), height=36, corner_radius=RADIUS_BTN,
            fg_color=BTN, hover_color=BTN_HOVER, command=self.on_debug_screenshot,
        ).pack(side="left")
        ctk.CTkLabel(
            parent,
            text="· 重新框选：手动圈出识别区域（平时不用，程序会自动找游戏窗口）\n"
                 "· 诊断截图：用来查看识别区域里到底有什么文字（一般不用）",
            font=(FONT, 12), text_color=DIM, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 12))

    def _make_clear_card(self, parent):
        """清空卡片：第 1 种浮动下拉选「清空数据 / 清空时间 / 都清空」，右边按钮执行"""
        card = ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)
        ctk.CTkButton(
            card, text="清空", font=(FONT, 15), width=84, height=34,
            corner_radius=RADIUS_BTN, fg_color=DANGER, hover_color=DANGER_HOVER,
            text_color="#FFFFFF", command=self._on_clear_selected,
        ).pack(side="right", padx=(10, 14), pady=9)

        self.clear_dd = FloatingDropdown(
            card, values=["清空今日数据", "清空监测时间", "清空数据和时间"],
            height=34, font_size=14, min_width=110)
        self.clear_dd.configure(width=176)
        self.clear_dd.set("清空今日数据")
        self.clear_dd.pack(side="right", padx=(8, 0), pady=9)
        self.clear_choice = self.clear_dd._var      # 兼容旧引用

        ic = ctk.CTkFrame(card, width=42, height=42, corner_radius=12, fg_color=CARD_INNER)
        ic.pack(side="left", padx=(14, 12), pady=9)
        ic.pack_propagate(False)
        ctk.CTkLabel(ic, text="🧹", font=(FONT, 20), text_color=ACCENT).place(
            relx=0.5, rely=0.5, anchor="center")
        mid = ctk.CTkFrame(card, fg_color="transparent")
        mid.pack(side="left", fill="both", expand=True, pady=9)
        ctk.CTkLabel(mid, text="清空", font=(FONT, 16, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(mid, text="选好要清空的内容，再点右边按钮（收益记录不受影响）",
                     font=(FONT, 12), text_color=DIM, anchor="w").pack(anchor="w", pady=(2, 0))
        card.pack(fill="x", pady=(0, 6))
        return card

    def _make_row_card(self, parent, icon, title, desc, btn_text, command, accent=False):
        """横向长条卡片：[图标小卡片] [标题 + 说明] ......... [按钮]

        返回 (卡片, 标题标签, 按钮)
        """
        card = ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)

        btn = ctk.CTkButton(
            card, text=btn_text, font=(FONT, 15), width=94, height=38,
            corner_radius=RADIUS_BTN,
            fg_color=(ACCENT if accent else BTN),
            hover_color=(ACCENT_DARK if accent else BTN_HOVER),
            text_color=("#FFFFFF" if accent else TEXT),
            command=command,
        )
        btn.pack(side="right", padx=(10, 14), pady=9)

        ic = ctk.CTkFrame(card, width=46, height=46, corner_radius=13,
                          fg_color=(ACCENT if accent else CARD_INNER))
        ic.pack(side="left", padx=(14, 12), pady=9)
        ic.pack_propagate(False)
        _il = ctk.CTkLabel(ic, text=icon, font=(FONT, 24),
                           text_color=("#FFFFFF" if accent else ACCENT))
        _il.place(relx=0.5, rely=0.5, anchor="center")

        mid = ctk.CTkFrame(card, fg_color="transparent")
        mid.pack(side="left", fill="both", expand=True, pady=9)
        tl = ctk.CTkLabel(mid, text=title, font=(FONT, 18, "bold"), text_color=TEXT, anchor="w")
        tl.pack(anchor="w")
        ctk.CTkLabel(mid, text=desc, font=(FONT, 13), text_color=DIM, anchor="w").pack(anchor="w", pady=(2, 0))

        def _click(_e=None):
            try:
                command()
            except Exception:
                pass

        # 整行都能点（按钮自己已绑定，不重复绑）
        for _w in (card, ic, _il, mid, tl):
            try:
                _w.bind("<Button-1>", _click)
                _w.configure(cursor="hand2")
            except Exception:
                pass
        return card, tl, btn

    def _build_page_home(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)

        # 上排三个卡片：摩拉 / 狗粮 / 监测时间
        cards = ctk.CTkFrame(page, fg_color="transparent")
        cards.grid(row=0, column=0, sticky="ew")
        for i in range(3):
            cards.grid_columnconfigure(i, weight=1)

        mora_card = self._make_card(cards)
        mora_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(mora_card, text="💰 今日摩拉", font=(FONT, 15), text_color=DIM).pack(pady=(14, 2))
        self.mora_label = ctk.CTkLabel(mora_card, text="0", font=(FONT, 36, "bold"), text_color=ACCENT)
        self.mora_label.pack(pady=(0, 14))

        art_card = self._make_card(cards)
        art_card.grid(row=0, column=1, sticky="nsew", padx=6)
        ctk.CTkLabel(art_card, text="💠 狗粮（圣遗物）", font=(FONT, 15), text_color=DIM).pack(pady=(14, 2))
        self.artifact_label = ctk.CTkLabel(art_card, text="×0", font=(FONT, 36, "bold"), text_color=ACCENT)
        self.artifact_label.pack(pady=(0, 14))

        time_card = self._make_card(cards)
        time_card.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(time_card, text="⏱ 监测时间", font=(FONT, 15), text_color=DIM).pack(pady=(14, 2))
        self.time_label = ctk.CTkLabel(time_card, text="00:00:00", font=(FONT, 28, "bold"), text_color=TEXT)
        self.time_label.pack(pady=(6, 14))

        # 素材区（双列：怪物素材 | 普通材料）
        recent = self._make_card(page)
        recent.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        page.grid_rowconfigure(1, weight=1)

        head2 = ctk.CTkFrame(recent, fg_color="transparent")
        head2.pack(fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(head2, text="⚔ 材料", font=(FONT, 17, "bold"), text_color=ACCENT).pack(side="left")
        # 「查看明细」按钮：原「素材明细」页已合并到这里，点它就地展开明细
        self.detail_toggle_btn = ctk.CTkButton(
            head2, text="查看明细", font=(FONT, 13), width=84, height=26,
            corner_radius=RADIUS_BTN, fg_color=BTN, hover_color=BTN_HOVER,
            text_color=TEXT, command=self._toggle_material_detail,
        )
        self.detail_toggle_btn.pack(side="right")

        # 简要列表（默认显示）
        self.mat_scroll = ctk.CTkScrollableFrame(recent, corner_radius=RADIUS_INNER, fg_color=CARD_INNER)
        self.mat_scroll.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        # 明细视图（默认隐藏，点「查看明细」展开）
        self.detail_frame = ctk.CTkFrame(recent, fg_color="transparent")
        self.detail_scroll = ctk.CTkScrollableFrame(
            self.detail_frame, corner_radius=RADIUS_INNER, fg_color=CARD_INNER)
        self.detail_scroll.pack(fill="both", expand=True)
        self.detail_total_label = ctk.CTkLabel(self.detail_frame, text="", font=(FONT, 15), text_color=DIM)
        self.detail_total_label.pack(anchor="w", padx=6, pady=(6, 0))
        self.detail_scroll2 = self.detail_scroll   # 兼容旧引用
        self._detail_shown = False
        return page

    def _build_page_bar(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="收益统计条", font=(FONT, 23, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        card = self._make_card(page)
        card.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            card, text="直播间小窗口：摩拉 / 材料 / 狗粮 三个格子，图标在上、数量在下。",
            font=(FONT, 16), text_color=TEXT,
        ).pack(padx=20, pady=(16, 4))
        ctk.CTkLabel(
            card, text="· 打开后可以随便拖动位置，放到直播间角落\n"
                       "· 三个格子的图标已内置（默认图标）\n"
                       "· OBS 里用「窗口捕获」选「收益统计条」窗口即可上屏",
            font=(FONT, 15), text_color=DIM, justify="left",
        ).pack(padx=20, pady=(0, 12))
        self.bar_btn = ctk.CTkButton(
            card, text="📶 打开统计条", font=(FONT, 17),
            height=44, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_DARK,
            text_color="#FFFFFF", command=self.on_stat_bar_toggle,
        )
        self.bar_btn.pack(padx=20, pady=(4, 18))

        # ---- 子选项：统计条透明度 ----
        op_card = self._make_card(page)
        op_card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(op_card, text="🌓 统计条透明度", font=(FONT, 17, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=20, pady=(14, 2))
        ctk.CTkLabel(op_card, text="往左拉更透明，放在直播画面上不容易挡到游戏画面。",
                     font=(FONT, 15), text_color=DIM).pack(anchor="w", padx=20, pady=(0, 8))

        op_row = ctk.CTkFrame(op_card, fg_color="transparent")
        op_row.pack(fill="x", padx=20, pady=(0, 16))
        self.bar_opacity_label = ctk.CTkLabel(op_row, text="", font=(FONT, 16, "bold"),
                                              text_color=TEXT, width=56)
        self.bar_opacity_label.pack(side="right", padx=(12, 0))
        _cur_op = float((self.settings.get("stat_bar") or {}).get("opacity", 1.0))
        _cur_op = max(0.2, min(1.0, _cur_op))
        self.bar_opacity_slider = ctk.CTkSlider(
            op_row, from_=0.2, to=1.0, number_of_steps=16,
            command=self._on_bar_opacity_change,
        )
        self.bar_opacity_slider.set(_cur_op)
        self.bar_opacity_slider.pack(side="left", fill="x", expand=True)
        self.bar_opacity_label.configure(text=f"{int(round(_cur_op * 100))}%")

        # ---- 子选项：显示哪几个格子 ----
        slot_card = self._make_card(page)
        slot_card.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(slot_card, text="📶 显示哪几个格子", font=(FONT, 17, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=20, pady=(14, 2))
        ctk.CTkLabel(slot_card, text="不想显示的直接关掉即可（改完立即生效）。",
                     font=(FONT, 15), text_color=DIM).pack(anchor="w", padx=20, pady=(0, 8))
        _bar = self.settings.get("stat_bar") or {}
        self._slot_vars = {}
        for _key, _name in (("slot1", "💰 摩拉"), ("slot2", "⚔ 材料"), ("slot3", "💠 狗粮")):
            _v = ctk.BooleanVar(value=bool(_bar.get("show_" + _key, True)))
            ctk.CTkSwitch(
                slot_card, text=_name, variable=_v, onvalue=True, offvalue=False,
                font=(FONT, 16), fg_color=SWITCH_OFF, progress_color=ACCENT, text_color=TEXT,
                command=self._on_any_setting_change,
            ).pack(anchor="w", padx=20, pady=(2, 2))
            self._slot_vars[_key] = _v
        ctk.CTkFrame(slot_card, height=10, fg_color="transparent").pack()
        return page

    def _build_page_records(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(head, text="收益记录", font=(FONT, 23, "bold"), text_color=ACCENT).pack(side="left")
        ctk.CTkButton(
            head, text="🗑 清空记录", font=(FONT, 15), width=100, height=30,
            corner_radius=RADIUS_BTN, fg_color=DANGER, hover_color=DANGER_HOVER,
            command=self.on_clear_records,
        ).pack(side="right")

        self.records_scroll = ctk.CTkScrollableFrame(page, corner_radius=RADIUS_CARD, fg_color=CARD)
        self.records_scroll.grid(row=1, column=0, sticky="nsew")
        self.records_scroll.grid_columnconfigure(0, weight=1)

        self._rec_open = set()
        self._rec_widgets = {}
        self._rebuild_records()
        return page

    def _make_record_card(self, parent, idx, rec):
        card = ctk.CTkFrame(parent, fg_color=CARD_INNER, corner_radius=10)
        card.pack(fill="x", padx=8, pady=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(top, text=f"{rec.get('start', '')}  →  {rec.get('end', '')}",
                     font=(FONT, 13), text_color=DIM).pack(side="left")
        ctk.CTkLabel(top, text=self._fmt_dur(rec.get("seconds", 0)),
                     font=(FONT, 15, "bold"), text_color=ACCENT).pack(side="right")

        mid = ctk.CTkFrame(card, fg_color="transparent")
        mid.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(mid, text=f"💰 {int(rec.get('mora', 0)):,}", font=(FONT, 16), text_color=TEXT).pack(
            side="left", padx=(0, 18))
        ctk.CTkLabel(mid, text=f"💠 狗粮 ×{int(rec.get('artifact', 0))}", font=(FONT, 16), text_color=TEXT).pack(
            side="left", padx=(0, 18))
        _mats = rec.get("materials") or {}
        ctk.CTkLabel(mid, text=f"⚔ 材料 {len(_mats)} 种 / {sum(_mats.values())} 个",
                     font=(FONT, 16), text_color=TEXT).pack(side="left")

        # 明细区（默认收起）
        detail = ctk.CTkFrame(card, fg_color="transparent")
        if _mats:
            for name, cnt in sorted(_mats.items(), key=lambda kv: -kv[1]):
                r = ctk.CTkFrame(detail, fg_color="transparent")
                r.pack(fill="x", pady=1)
                ctk.CTkLabel(r, text=name, font=(FONT, 15), text_color=TEXT).pack(side="left")
                ctk.CTkLabel(r, text=f"×{cnt}", font=(FONT, 15, "bold"), text_color=ACCENT).pack(side="right")
        else:
            ctk.CTkLabel(detail, text="（这段时间没有识别到材料）",
                         font=(FONT, 13), text_color=DIM).pack(anchor="w")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 10))
        btn = ctk.CTkButton(
            btn_row, text="查看明细 ▾", font=(FONT, 15), width=100, height=28,
            corner_radius=RADIUS_BTN, fg_color=BTN, hover_color=BTN_HOVER,
            command=lambda i=idx: self._toggle_record_detail(i),
        )
        btn.pack(side="right")

        self._rec_widgets[idx] = (detail, btn)
        if idx in getattr(self, "_rec_open", set()):
            detail.pack(fill="x", padx=12, pady=(0, 8))
            btn.configure(text="收起明细 ▴")

    def _build_page_settings(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(page, text="设置", font=(FONT, 23, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        # ---- 标签栏 ----
        self.settings_tab_var = ctk.StringVar(value="识别")
        ctk.CTkSegmentedButton(
            page, values=["识别", "统计", "外观", "关于"], variable=self.settings_tab_var,
            font=(FONT, 14), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM, command=self._on_settings_tab,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        holder = ctk.CTkFrame(page, fg_color="transparent")
        holder.grid(row=2, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self._settings_tabs = {}
        for _name in ("识别", "统计", "外观", "关于"):
            _f = ctk.CTkScrollableFrame(holder, corner_radius=0, fg_color="transparent")
            _f.grid(row=0, column=0, sticky="nsew")
            _f.grid_columnconfigure(0, weight=1)
            self._settings_tabs[_name] = _f

        # ================= 识别 =================
        t = self._settings_tabs["识别"]

        h = self._make_setting_card(t, "⏱", "检测间隔", "每多少毫秒检查一次画面（10~5000，默认 50）")
        self.tick_entry = ctk.CTkEntry(h, font=(FONT, 14), height=34, width=104,
                                       fg_color=CARD_INNER, text_color=TEXT, border_color=BTN_HOVER)
        self.tick_entry.insert(0, str(int(self.settings.get("tick_interval", 50))))
        self.tick_entry.pack(side="right")
        self.tick_entry.bind("<KeyRelease>", self._on_tick_change)
        self.tick_entry.bind("<FocusOut>", self._on_any_setting_change)

        h = self._make_setting_card(t, "🎚", "画面变化灵敏度", "越灵敏识别越快，太灵敏会耗电")
        self.change_var = ctk.StringVar(value=str(self.settings.get("change_level", "中")))
        self.change_dd = FloatingDropdown(h, ["高", "中", "低"], variable=self.change_var,
                                          command=self._on_any_setting_change, font_size=14)
        self.change_dd.pack(fill="x")

        h = self._make_setting_card(t, "🔁", "防重复窗口", "同一提示消失多久后再出现才算新掉落")
        _ev = str(self.settings.get("event_end_window", 1.5)).replace("秒", "").strip()
        self.event_var = ctk.StringVar(value=f"{_ev} 秒")
        self.event_dd = FloatingDropdown(h, ["1.0 秒", "1.5 秒", "2.5 秒"], variable=self.event_var,
                                         command=self._on_any_setting_change, font_size=14)
        self.event_dd.pack(fill="x")

        h = self._make_setting_card(t, "🔍", "文字识别频率", "越快响应越及时，越慢越省电")
        self.ocr_var = ctk.StringVar(
            value={150: "快", 250: "标准", 500: "慢"}.get(int(self.settings.get("ocr_interval", 250)), "标准"))
        self.ocr_dd = FloatingDropdown(h, ["快", "标准", "慢"], variable=self.ocr_var,
                                       command=self._on_any_setting_change, font_size=14)
        self.ocr_dd.pack(fill="x")

        h = self._make_setting_card(t, "➕", "自动登记新材料", "遇到材料库里没有的名字时自动加进材料库")
        self.auto_reg_var = ctk.BooleanVar(value=bool(self.settings.get("auto_register_material", True)))
        ctk.CTkSwitch(h, text="", variable=self.auto_reg_var, onvalue=True, offvalue=False,
                      width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                      command=self._on_any_setting_change).pack(side="right")

        # ================= 统计 =================
        t = self._settings_tabs["统计"]

        # 识别内容：第 2 种折叠区（三个开关合并进来）
        self._acc_enable = Accordion(
            t, "🎯", "识别内容", "想统计什么就开什么（点这里展开）", self._build_enable_body,
            on_change=self._apply_background)
        self._acc_enable.pack(fill="x", pady=(0, 8))

        h = self._make_setting_card(t, "✖", "点右上角 ✕ 时", "关闭窗口时的行为")
        _cb = {"ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"}.get(
            self.settings.get("close_behavior", "ask"), "每次询问")
        self.close_btn_var = ctk.StringVar(value=_cb)
        self.close_dd = FloatingDropdown(
            h, ["每次询问", "最小化到托盘", "直接退出"], variable=self.close_btn_var,
            command=self._on_any_setting_change, font_size=14)
        self.close_dd.pack(fill="x")

        h = self._make_setting_card(t, "🎯", "只在原神前台时识别", "切到别的应用就暂停，回到原神自动继续")
        self.only_foreground_var = ctk.BooleanVar(value=bool(self.settings.get("only_foreground", True)))
        ctk.CTkSwitch(h, text="", variable=self.only_foreground_var, onvalue=True, offvalue=False,
                      width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                      command=self._on_any_setting_change).pack(side="right")

        # 换日时间：输入框（自己填 0~23）
        h = self._make_setting_card(t, "🌙", "换日时间", "填 0~23。挂机挂过零点的话，往后填几小时就不会中途归零")
        try:
            _ro = int(self.settings.get("rollover_hour", 0)) % 24
        except Exception:
            _ro = 0
        self.rollover_entry = ctk.CTkEntry(h, font=(FONT, 14), height=34, width=84,
                                           fg_color=CARD_INNER, text_color=TEXT, border_color=BTN_HOVER)
        self.rollover_entry.insert(0, str(_ro))
        ctk.CTkLabel(h, text="点", font=(FONT, 14), text_color=DIM).pack(side="right")
        self.rollover_entry.pack(side="right", padx=(0, 6))
        self.rollover_var = ctk.StringVar(value=str(_ro))

        def _ro_edit(_e=None):
            try:
                self.rollover_var.set(self.rollover_entry.get().strip())
            except Exception:
                pass
            self._on_tick_change()

        self.rollover_entry.bind("<KeyRelease>", _ro_edit)
        self.rollover_entry.bind("<FocusOut>", self._on_any_setting_change)

        # 全局热键（按一下就设定）
        h = self._make_setting_card(t, "⌨", "全局热键（开始/停止监测）", "点按钮后按下想用的键（Esc 取消）")
        self.hotkey_btn = ctk.CTkButton(
            h, text=str(self.settings.get("hotkey", "关闭")), font=(FONT, 14),
            height=34, corner_radius=RADIUS_BTN, fg_color=BTN, hover_color=BTN_HOVER,
            command=self._start_hotkey_capture,
        )
        self.hotkey_btn.pack(fill="x")
        self.hotkey_var = ctk.StringVar(value=str(self.settings.get("hotkey", "关闭")))

        # ================= 外观 =================
        t = self._settings_tabs["外观"]

        h = self._make_setting_card(t, "🎨", "背景颜色", "窗口背景色")
        cur_bg = self.settings.get("bg_color", "经典深黑")
        if cur_bg not in theme.BG_PRESETS:
            self._custom_bg_hex = cur_bg
        self.bg_var = ctk.StringVar(value=cur_bg if cur_bg in theme.BG_PRESETS else "自定义…")
        # 记住上一次选的预设（取消取色时用来回退）
        self._last_bg_sel = cur_bg if cur_bg in theme.BG_PRESETS else "经典深黑"
        self.bg_dd = FloatingDropdown(
            h, list(theme.BG_PRESETS.keys()) + ["自定义…"], variable=self.bg_var,
            command=self._on_pick_bg_color, font_size=14)
        self.bg_dd.pack(fill="x")

        h = self._make_setting_card(t, "🌈", "强调色", "按钮、选中项、数字高亮的颜色")
        cur_ac = self.settings.get("accent_color", "经典蓝")
        if cur_ac not in theme.ACCENT_PRESETS:
            self._custom_accent_hex = cur_ac
        self.accent_var = ctk.StringVar(value=cur_ac if cur_ac in theme.ACCENT_PRESETS else "自定义…")
        self._last_accent_sel = cur_ac if cur_ac in theme.ACCENT_PRESETS else "经典蓝"
        self.accent_dd = FloatingDropdown(
            h, list(theme.ACCENT_PRESETS.keys()) + ["自定义…"], variable=self.accent_var,
            command=self._on_pick_accent_color, font_size=14)
        self.accent_dd.pack(fill="x")

        # 背景图片 + 毛玻璃：第 2 种折叠区
        self._acc_bg = Accordion(
            t, "🖼", "自定义背景图片", "选图片当窗口背景；可以调卡片透明度（含侧边栏和按钮）",
            self._build_bg_body, on_change=self._apply_background)
        self._acc_bg.pack(fill="x", pady=(0, 8))

        # 统计条图标：打开图标管理窗口
        h = self._make_setting_card(t, "🖼", "统计条图标", "换收益统计条三个格子的图标（摩拉/材料/狗粮）")
        ctk.CTkButton(
            h, text="打开图标管理", font=(FONT, 14), height=34,
            fg_color=BTN, hover_color=BTN_HOVER, command=self.on_icon_manager,
        ).pack(fill="x")

        # OBS：第 2 种折叠区
        self._acc_obs = Accordion(
            t, "📺", "连接 OBS 直播覆盖", "点开可以看到开关和浏览器源地址",
            self._build_obs_body, on_change=self._apply_background)
        self._acc_obs.pack(fill="x", pady=(0, 8))

        # ================= 关于 =================
        t = self._settings_tabs["关于"]

        h = self._make_setting_card(t, "ℹ️", "StatGI V0.7（测试版）",
                                    "识别只靠文字（OCR），不读内存、不控制游戏\n"
                                    "防重复统计：同一个掉落提示只统计一次\n"
                                    "数据保存在程序旁边的 data 文件夹", wide=True)
        _upd = ctk.CTkFrame(h, fg_color="transparent")
        _upd.pack(fill="x")
        ctk.CTkButton(
            _upd, text="🔍 检测更新", font=(FONT, 14), height=34, width=130,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_DARK, text_color="#FFFFFF",
            command=self.on_check_update,
        ).pack(side="left")
        self.update_status_label = ctk.CTkLabel(_upd, text="", font=(FONT, 13), text_color=DIM)
        self.update_status_label.pack(side="left", padx=10)
        ctk.CTkLabel(h, text="检测更新会访问 GitHub Releases，需要联网。",
                     font=(FONT, 12), text_color=DIM).pack(anchor="w", pady=(6, 0))

        if self.settings.get("developer_mode", False):
            self._build_dev_card(t, 0)

        self._on_settings_tab("识别")
        return page

    def _build_enable_body(self, parent):
        """「识别内容」展开后：摩拉 / 怪物素材 / 圣遗物 三个开关"""
        self.enable_mora_var = ctk.BooleanVar(value=bool(self.settings.get("enable_mora", True)))
        self.enable_mat_var = ctk.BooleanVar(value=bool(self.settings.get("enable_material", True)))
        self.enable_art_var = ctk.BooleanVar(value=bool(self.settings.get("enable_artifact", True)))
        for var, text, tip in (
            (self.enable_mora_var, "💰 识别摩拉", "统计掉落提示里的摩拉"),
            (self.enable_mat_var, "⚔ 识别怪物素材", "统计怪物掉落的各种素材"),
            (self.enable_art_var, "💠 识别圣遗物（狗粮）", "统计捡到的圣遗物数量"),
        ):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(row, text=text, font=(FONT, 15), text_color=TEXT, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=tip, font=(FONT, 12), text_color=DIM, anchor="w").pack(
                side="left", padx=(10, 0))
            ctk.CTkSwitch(row, text="", variable=var, onvalue=True, offvalue=False,
                          width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                          command=self._on_any_setting_change).pack(side="right")
        ctk.CTkFrame(parent, height=8, fg_color="transparent").pack()

    def _build_bg_body(self, parent):
        """「自定义背景图片」展开后：选图片 + 清除 + 毛玻璃开关"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkButton(
            row, text="🖼 选择图片…", font=(FONT, 14), height=32, width=130,
            fg_color=BTN, hover_color=BTN_HOVER, command=self._choose_bg_image,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row, text="✖ 清除背景", font=(FONT, 14), height=32, width=130,
            fg_color=DANGER, hover_color=DANGER_HOVER, command=self._clear_bg_image,
        ).pack(side="left", padx=(0, 12))
        _cur_bg_file = Path(self.settings.get("bg_image") or "").name if self.settings.get("bg_image") else ""
        self._bg_img_label = ctk.CTkLabel(
            row, text=f"当前：{_cur_bg_file}" if _cur_bg_file else "未设置（纯色背景）",
            font=(FONT, 13), text_color=DIM)
        self._bg_img_label.pack(side="left")

        row2 = ctk.CTkFrame(parent, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(2, 10))
        ctk.CTkLabel(row2, text="左侧栏毛玻璃效果", font=(FONT, 15), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(row2, text="需要先设置背景图片（模糊+压暗，模拟磨砂质感）",
                     font=(FONT, 12), text_color=DIM).pack(side="left", padx=(10, 0))
        self.glass_var = ctk.BooleanVar(value=bool(self.settings.get("sidebar_glass", True)))
        ctk.CTkSwitch(row2, text="", variable=self.glass_var, onvalue=True, offvalue=False,
                      width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                      command=self._on_any_setting_change).pack(side="right")

        row3 = ctk.CTkFrame(parent, fg_color="transparent")
        row3.pack(fill="x", padx=14, pady=(2, 10))
        ctk.CTkLabel(row3, text="卡片透明度", font=(FONT, 15), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(row3, text="卡片 / 侧边栏 / 按钮统一用这个（0%=全透明）",
                     font=(FONT, 12), text_color=DIM).pack(side="left", padx=(10, 0))
        _op = int(round(float(self.settings.get("panel_opacity", 0.5)) * 100))
        self.opacity_label = ctk.CTkLabel(row3, text=f"{_op}%", font=(FONT, 13),
                                          text_color=ACCENT, width=44)
        self.opacity_label.pack(side="right")
        self.opacity_slider = ctk.CTkSlider(
            row3, from_=0, to=100, number_of_steps=20, width=150, height=16,
            fg_color=BTN, progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_DARK, command=self._on_panel_opacity_change)
        self.opacity_slider.set(_op)
        self.opacity_slider.pack(side="right", padx=(10, 4))

        row4 = ctk.CTkFrame(parent, fg_color="transparent")
        row4.pack(fill="x", padx=14, pady=(2, 10))
        ctk.CTkLabel(row4, text="背景压暗", font=(FONT, 15), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(row4, text="背景图太花、字看不清时往右拉（0%=不压暗）",
                     font=(FONT, 12), text_color=DIM).pack(side="left", padx=(10, 0))
        _dm = int(round(float(self.settings.get("bg_dim", 0.0) or 0.0) * 100))
        self.dim_label = ctk.CTkLabel(row4, text=f"{_dm}%", font=(FONT, 13),
                                      text_color=ACCENT, width=44)
        self.dim_label.pack(side="right")
        self.dim_slider = ctk.CTkSlider(
            row4, from_=0, to=60, number_of_steps=12, width=150, height=16,
            fg_color=BTN, progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_DARK, command=self._on_bg_dim_change)
        self.dim_slider.set(_dm)
        self.dim_slider.pack(side="right", padx=(10, 4))

    def _build_obs_body(self, parent):
        """「连接 OBS」展开后：开关 + 地址 + 复制"""
        ctk.CTkLabel(parent, text="在 OBS 里添加「浏览器源」，粘贴下面的地址即可在直播画面上显示收益。",
                     font=(FONT, 12), text_color=DIM, justify="left").pack(anchor="w", padx=14, pady=(0, 6))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))
        self.obs_var = ctk.BooleanVar(value=bool(self.settings.get("obs_browser_source", False)))
        ctk.CTkSwitch(row, text="开启", variable=self.obs_var, onvalue=True, offvalue=False,
                      font=(FONT, 14), fg_color=SWITCH_OFF, progress_color=ACCENT, text_color=TEXT,
                      command=self._toggle_obs_source).pack(side="left")
        api_port = int(self.settings.get("api_port", 8765))
        self._obs_addr_label = ctk.CTkLabel(row, text=f"http://127.0.0.1:{api_port}/overlay",
                                            font=(FONT, 13), text_color=TEXT)
        self._obs_addr_label.pack(side="left", padx=(16, 8))
        ctk.CTkButton(row, text="复制", font=(FONT, 13), width=56, height=28,
                      corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER,
                      command=self._copy_obs_addr).pack(side="left")

    def _make_setting_card(self, parent, icon, title, desc, wide=False):
        """设置项卡片：和启动页同款横向长条

        [图标小卡] [标题 + 说明] …… [右侧控件区]
        返回右侧（或下方）的控件容器，调用方把控件 pack 进去。
        """
        card = ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, 8))
        holder = ctk.CTkFrame(card, fg_color="transparent")
        ic = ctk.CTkFrame(card, width=42, height=42, corner_radius=12, fg_color=CARD_INNER)
        mid = ctk.CTkFrame(card, fg_color="transparent")
        if wide:
            holder.pack(fill="x", padx=14, pady=(0, 10))
        else:
            # 固定宽度 + 不许子控件撑大：这样每张卡片右边的控件都能对齐
            # 宽度调窄一些（原来 300 太宽），输入框/下拉看起来更紧凑
            holder.configure(width=178, height=44)
            holder.pack_propagate(False)
            holder.pack(side="right", padx=(10, 14), pady=9)
        ic.pack(side="left", padx=(14, 12), pady=9)
        ic.pack_propagate(False)
        ctk.CTkLabel(ic, text=icon, font=(FONT, 20), text_color=ACCENT).place(
            relx=0.5, rely=0.5, anchor="center")
        mid.pack(side="left", fill="both", expand=True, pady=9)
        ctk.CTkLabel(mid, text=title, font=(FONT, 16, "bold"), text_color=TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(mid, text=desc, font=(FONT, 12), text_color=DIM, anchor="w",
                     justify="left", wraplength=300).pack(anchor="w", pady=(2, 0))
        return holder

    def _on_settings_tab(self, name):
        """切换设置页标签：同一格里只显示当前标签的滚动容器"""
        try:
            for k, f in getattr(self, "_settings_tabs", {}).items():
                if k == name:
                    f.grid()
                    try:
                        f._parent_canvas.yview_moveto(0)
                    except Exception:
                        pass
                else:
                    f.grid_remove()
        except Exception:
            pass

    def _setting_row(self, card, title, desc):
        ctk.CTkLabel(card, text=title, font=(FONT, 16), text_color=TEXT).pack(padx=20, pady=(6, 0), anchor="w")
        ctk.CTkLabel(card, text=desc, font=(FONT, 13), text_color=DIM).pack(padx=20, pady=(0, 4), anchor="w")

    def _build_dev_card(self, scroll, r):
        """构建开发者选项卡片（仅开发者模式显示）"""
        card = self._make_card(scroll)
        card.grid(row=r, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(card, text="🛠 开发者选项", font=(FONT, 16, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 4))
        ctk.CTkLabel(
            card, text="本地 AI 样本采集（仅供开发者收集训练数据，不影响普通使用）。\n"
                       "截图全部保存在本地，不上传、不联网、不进 Git。",
            font=(FONT, 12), text_color=DIM, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 8))

        # 启用样本采集
        self.dataset_enabled_var = ctk.BooleanVar(value=bool(self.settings.get("dataset_enabled", False)))
        ctk.CTkSwitch(
            card, text="启用样本采集", variable=self.dataset_enabled_var, onvalue=True, offvalue=False,
            font=(FONT, 15), fg_color=SWITCH_OFF, progress_color=ACCENT, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(0, 6))

        # 保存位置
        self._setting_row(card, "保存位置", "样本保存目录（默认在用户目录，不在项目内）")
        path_row = ctk.CTkFrame(card, fg_color="transparent")
        path_row.pack(fill="x", padx=20, pady=(0, 4))
        self._dataset_path_label = ctk.CTkLabel(
            path_row, text=self._dev_path_display(), font=(FONT, 12), text_color=TEXT, anchor="w",
        )
        self._dataset_path_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            path_row, text="浏览…", font=(FONT, 13), width=60, height=26,
            corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER, command=self._on_choose_dataset_path,
        ).pack(side="right")

        # 统计
        self._dev_stats_label = ctk.CTkLabel(card, text="", font=(FONT, 12), text_color=DIM, justify="left")
        self._dev_stats_label.pack(anchor="w", padx=20, pady=(4, 6))
        self._refresh_dev_stats()

        # 手动采集 + 操作按钮
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkButton(
            btns, text="采集 GAMEPLAY", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=BTN, hover_color=BTN_HOVER, command=lambda: self._on_manual_capture("gameplay"),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="采集 NON_GAMEPLAY", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=BTN, hover_color=BTN_HOVER, command=lambda: self._on_manual_capture("non_gameplay"),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="打开文件夹", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=BTN, hover_color=BTN_HOVER, command=self._on_open_dataset,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="清空样本", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=DANGER, hover_color=DANGER_HOVER, command=self._on_clear_dataset,
        ).pack(side="left")

    def _make_card(self, parent):
        return ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)

    @staticmethod
    def _grid_page(frame, show):
        """显示 / 隐藏一个页面（页面自己不再 grid，统一在这里控制）"""
        try:
            if frame is None:
                return
            if show:
                frame.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
            else:
                frame.grid_remove()
        except Exception:
            pass

    def _ensure_page(self, key):
        """按需构建页面（懒加载）：第一次切到某页才建它"""
        if key in getattr(self, "_pages", {}):
            return self._pages[key]
        frame = None
        try:
            frame = self._page_builders[key]()
        except Exception:
            frame = None
        self._pages[key] = frame
        # 只有「当前页」才显示；后台预建出来的其它页完全不 grid，
        # 这样启动时就不会闪一下设置界面了
        self._grid_page(frame, key == getattr(self, "_current_page", None))
        return frame

    def _show_page(self, key):
        self._current_page = key
        self._ensure_page(key)
        for k, f in getattr(self, "_pages", {}).items():
            self._grid_page(f, k == key)
        # 页面「第一次」显示时才需要整体贴一次背景；
        # 之后控件的位置没变，不需要每次切页都把两百多个控件重走一遍
        # （否则每切一次页面都要多花三四百毫秒）。
        if self.settings.get("bg_image"):
            sig = (str(self.settings.get("bg_image") or ""),
                   round(self._glass_alpha(), 3),
                   bool(self.settings.get("sidebar_glass", True)),
                   self.winfo_width(), self.winfo_height())
            if getattr(self, "_glass_page_sig", None) != sig:
                self._glass_page_sig = sig
                self._glass_pages_done = set()
            done = getattr(self, "_glass_pages_done", None)
            if done is None:
                done = set()
                self._glass_pages_done = done
            if key not in done:
                done.add(key)
                self._apply_background()
        for k, btn in self.nav_btns.items():
            if k == key:
                btn.configure(fg_color=NAV_ON, text_color=ACCENT, font=(FONT, 16, "bold"))
            else:
                btn.configure(fg_color="transparent", text_color=DIM, font=(FONT, 16))
        # 进「收益记录」时刷新一次列表
        if key == "records":
            try:
                self._rebuild_records()
            except Exception:
                pass
        # 刚建好的页面补一次数据刷新
        try:
            self._refresh_ui()
        except Exception:
            pass
