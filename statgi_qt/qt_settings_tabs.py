# -*- coding: utf-8 -*-
"""设置页的标签页 —— 一个标签页一个类。

从 `qt_pages.PageSettings` 拆出来的（第 9 批）。

原来 `PageSettings` 是一个 1346 行的巨类：7 个 `_build_*` 挨在一起，
**而它们的处理器全混在文件尾部**（外观的、识别的、统计的、直播的……交错着），
加一个设置项要在这堆里翻半天 —— 架构体检把它列为「当前开发速度的主要瓶颈」。

现在：**一个标签页一个类，构建 + 自己的处理器放在一起**，
`PageSettings` 只剩「标签栏 + 滚动区 + 造出这 7 个页面」。

⚠ 拆的时候是**逐像素比对**的：拆完之后冒烟截图必须跟拆之前一字不差。
  见 `_morph\\smoke_baseline.py`。

⚠ 进度：**一次拆一个**。还没拆的那些标签页仍然由 `PageSettings._build_*` 建，
  两边并存（`qt_pages.TAB_FACTORIES` 里登记了哪些已经拆走）。
"""
import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog,
                               QHBoxLayout, QGridLayout, QFrame, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from qt_theme import (btn_qss, combo_qss, entry_qss, label_qss, rgba,
                      slider_qss)
import qt_theme as T
import qt_checklist as _ck
from qt_checklist import _box_qss
import config_manager
import svc_capture
import svc_names
import svc_autostart
from qt_widgets import (Accordion, Card, RedDot, SettingRow, Switch,
                        SwitchAccordion, level_name, level_value, make_combo,
                        msg_info, right_wrap, set_btn_icon, small_button,
                        bind_cb)
from qt_dlg_card import CardDialog
from app_info import VERSION

# 颜色下拉框里那一项「自定义颜色…」（选了会开取色器）
#
# ⚠ 原来住在 `qt_pages` 上；标签页拆出来之后两边都要用，而 `qt_pages`
#   反向 import 本模块会成环 —— 所以定义搬到这里，
#   `qt_pages.CUSTOM_COLOR` 改成从这儿转发（对外表面不变）。
CUSTOM_COLOR = "自定义颜色…"


class SettingsTab(QWidget):
    """设置页里一个标签页的基类。

    ⚠ 这个类**故意只拿三样**：parent / cfg / alpha。
      不拿 `AppState`、不拿主窗口 —— 第 8 批刚把 `PageSettings` 从 `AppState`
      上摘下来（那个对象上挂着 `toggle()`，**会启动识别**），别在这儿又请回来。
      确实需要主窗口帮忙的标签页，走**显式回调**（见 `LiveTab`）。
    """

    def __init__(self, parent, cfg, alpha):
        super().__init__(parent)
        self.cfg = cfg
        self.alpha = alpha
        # 热键录制时要抢焦点的那个控件（只有「行为」标签页用）。
        # 默认是自己；设置页建完之后会把它改成**设置页**本身 ——
        # 因为 `keyPressEvent` 是装在页面上的（页面才是那个能收键盘的控件）。
        self.focus_host = self
        # ⚠ 跟原来 PageSettings 里那个 inner 控件一模一样：
        #   透明底 + 右边留 10px（给滚动条）+ 行距 10 + 末尾弹簧
        self.setStyleSheet("background: transparent;")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 10, 0)
        self.v.setSpacing(10)
        self.v.addStretch(1)

    def row(self, icon, title, desc, right=None, height=70, tip=""):
        """加一行设置（跟原来 `PageSettings._row` 的行为完全一样）。

        `tip` 是鼠标悬停时显示的**详细说明**（比 desc 长、讲原理和注意事项）。
        """
        r = SettingRow(self, icon, title, desc, right, alpha=self.alpha,
                       height=height, tip=tip)
        self.v.insertWidget(self.v.count() - 1, r)
        return r

    def _dd(self, items, width=150):
        """通用下拉框（跟原来 `PageSettings._dd` 是同一个实现）"""
        return make_combo(items, width)

    def add_card(self, w):
        """往末尾（弹簧之前）插一张卡片。

        跟原来 `self._lay[tb].insertWidget(self._lay[tb].count() - 1, w)`
        完全等价 —— 折叠区那种"整张卡片"的行用这个。
        """
        self.v.insertWidget(self.v.count() - 1, w)
        return w


class LiveTab(SettingsTab):
    """直播：数据接口总开关 + 收益条地址 + 接口端口。"""

    def __init__(self, parent, cfg, alpha, apply_api=None):
        # ⚠ 只拿一个回调，不拿整个主窗口：这个标签页需要主窗口做的
        #   唯一一件事就是「按新设置把接口起停一下」。
        self._apply_api = apply_api or (lambda: None)
        super().__init__(parent, cfg, alpha)

        # ---- 直播数据接口总开关 ----
        # 这个是**真的开关**：关掉就把接口停掉（OBS 那个浏览器源会没数据），
        # 打开就重新起来。以前它只存了个值、什么都不干。
        self.obs_sw = Switch(self, bool(self.cfg.get("obs_api_enabled", True)))
        self.obs_sw.toggled.connect(self._on_obs)
        self.row("radio", "直播数据接口",
                 "为 OBS 浏览器源提供实时数据接口；关闭后直播端无数据",
                 self.obs_sw,
                 tip="在本机开启一个只读的数据接口，OBS 的浏览器源、直播计时条"
                     "都从这里取数。\n"
                     "关闭后接口进程立即停止，直播端会显示为无数据；"
                     "不需要直播时建议关掉，少占一个本地端口。")

        # ---- 收益条地址 ----
        # 注意给的是 /bar（**只有收益条**：摩拉/材料/狗粮/监测时间）。
        # /overlay 那个是整块竖屏覆盖层，上面一半是弹幕区，不是纯收益条。
        api_port = int(self.cfg.get("api_port", 8765) or 8765)
        self.obs_addr = QLabel(self._bar_url(api_port))
        self.obs_addr.setStyleSheet(label_qss(T.TEXT, 13))
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(60, 28)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(btn_qss("normal", self.alpha))
        copy_btn.clicked.connect(self._copy_obs)
        self.row("monitor", "收益条地址",
                 "OBS 浏览器源地址，建议尺寸 340×200",
                 right_wrap(self.obs_addr, copy_btn),
                 tip="这是**只有收益条**的地址（摩拉 / 材料 / 狗粮 / 监测时间）。\n"
                     "在 OBS 里添加「浏览器源」，粘贴此地址，建议尺寸 340×200。\n"
                     "地址里的端口跟下面「接口端口」一致，改端口后要重新复制。")

        # ---- 端口 ----
        self.api_entry = QLineEdit(str(api_port))
        self.api_entry.setFixedWidth(90)
        self.api_entry.setAlignment(Qt.AlignCenter)
        self.api_entry.setStyleSheet(entry_qss())
        self.api_entry.editingFinished.connect(self._on_api_port)
        self.row("plug", "接口端口",
                 "接口监听端口；修改即时生效，OBS 端需同步更新", self.api_entry,
                 tip="数据接口监听的本地端口，范围 1024~65535，默认 8765。\n"
                     "改完立即重启接口；若有别的程序占用该端口，接口会起不来，"
                     "换一个端口即可。\n"
                     "改完记得把「收益条地址」重新复制到 OBS。")

    @staticmethod
    def _bar_url(port):
        return f"http://127.0.0.1:{int(port)}/bar"

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_api_port(self):
        try:
            v = max(1024, min(65535, int(self.api_entry.text().strip())))
        except Exception:
            v = 8765
        self.api_entry.setText(str(v))
        self.cfg.set("api_port", v)
        # 地址显示跟着改，并且**立刻**把接口换到新端口（以前要重启）
        try:
            self.obs_addr.setText(self._bar_url(v))
        except Exception:
            pass
        try:
            self._apply_api()
        except Exception:
            pass

    def _on_obs(self, v):
        """直播数据接口总开关：立刻开 / 关接口"""
        self.cfg.set("obs_api_enabled", bool(v))
        try:
            self._apply_api()
        except Exception:
            pass

    def _copy_obs(self):
        from PySide6.QtWidgets import QApplication as _A
        _A.clipboard().setText(self.obs_addr.text())
        QMessageBox.information(self, "已复制",
                                f"OBS 浏览器源地址已复制：\n{self.obs_addr.text()}")


class RecognizeTab(SettingsTab):
    """识别：检测间隔 / 文字识别频率 / 画面变化灵敏度 / 防重复窗口 / 识别哪几样。"""

    def __init__(self, parent, cfg, alpha):
        super().__init__(parent, cfg, alpha)

        # 兜底值跟 config_manager.DEFAULT_SETTINGS["tick_interval"] 一致（100）。
        # ⚠ 改了默认值记得同步改这里，否则"设置项缺失"时两个地方对不上。
        self.tick_entry = QLineEdit(str(self.cfg.get("tick_interval", 100)))
        self.tick_entry.setFixedWidth(90)
        self.tick_entry.setAlignment(Qt.AlignCenter)
        self.tick_entry.setStyleSheet(entry_qss())
        self.tick_entry.editingFinished.connect(self._on_tick)
        self.row("timer", "检测间隔",
                 "画面采样间隔（毫秒）；取值 10~5000，默认 100", self.tick_entry,
                 tip="程序多久看一次屏幕（毫秒）。它只做**便宜的**画面差异比较，"
                     "真正耗时的文字识别另有节流，所以调小不一定更吃 CPU。\n"
                     "越小＝越能及时察觉掉落提示出现；\n"
                     "越大＝越省电，但快速连续的拾取可能被合并观察。\n"
                     "建议 50（默认），笔记本省电可 80~120。")

        # 文字识别频率：性能 / 标准 / 省电 / 极致省电（越小越频繁）
        self.ocr_dd = self._dd([name for name, _v in config_manager.OCR_LEVELS])
        self.ocr_dd.setCurrentText(
            level_name(config_manager.OCR_LEVELS,
                       int(self.cfg.get("ocr_interval", 150) or 150), config_manager.DEFAULT_OCR_LEVEL))
        self.ocr_dd.currentTextChanged.connect(self._on_ocr_interval)
        self.row("search", "文字识别频率",
                 "文字识别间隔（毫秒）；数值越小响应越快、占用越高", self.ocr_dd,
                 tip="OCR 的节流档位（性能 100 / 标准 150 / 省电 250 / 极致省电 500 毫秒）。\n"
                     "文字识别本身较慢（一次约 0.6 秒），这是**主要**的性能开销来源。\n"
                     "档位越高越省电，但收获提示淡出得快时可能来不及读全。\n"
                     "建议保持「标准」；挂机发热明显再降档。")

        # 画面变化灵敏度：同一套名字，数值是变化阈值（越小越灵敏）
        #
        # 注意：识别核心读的是 change_threshold，不是 change_level。
        # Tk 版在这儿有个 bug：下拉框按 change_level 显示、保存却只写
        # change_threshold，于是 change_level 永远是老值，**看到的值跟
        # 实际用的值对不上**。这里按 change_threshold 反推显示，并且两个都写。
        self.change_dd = self._dd([name for name, _v in config_manager.CHANGE_LEVELS])
        try:
            _cur_thr = float(self.cfg.get("change_threshold", 2.0))
        except Exception:
            _cur_thr = 2.0
        self.change_dd.setCurrentText(
            level_name(config_manager.CHANGE_LEVELS, _cur_thr,
                       config_manager.DEFAULT_CHANGE_LEVEL))
        self.change_dd.currentTextChanged.connect(self._on_change_level)
        self.row("sliders-horizontal", "画面变化灵敏度",
                 "画面变化判定阈值；越灵敏响应越快、占用越高", self.change_dd,
                 tip="判定「画面变了、该跑一次文字识别」的阈值。\n"
                     "档位：性能 1.0 / 标准 2.0 / 省电 4.0 / 极致省电 8.0（数值越小越灵敏）。\n"
                     "调得太灵敏时，战斗特效、伤害数字跳动都会被当成「画面变了」，"
                     "反而频繁触发识别、更吃 CPU。\n"
                     "掉落识别不灵（漏记）时先往「性能」调一档试试。")

        ev = str(self.cfg.get("event_end_window", 1.5)).replace("秒", "").strip()
        self.event_dd = self._dd(["1.0 秒", "1.5 秒", "2.5 秒"])
        self.event_dd.setCurrentText((f"{ev} 秒" if f"{ev} 秒" in ("1.0 秒", "1.5 秒", "2.5 秒")
                                      else "1.5 秒"))
        self.event_dd.currentTextChanged.connect(self._on_event_window)
        self.row("repeat", "防重复窗口",
                 "同一名称消失超过该时长后再次出现，计为新掉落", self.event_dd,
                 tip="同一条收获提示「消失」超过这个时长后再次出现，才算一次新的掉落，"
                     "用来防止 OCR 漏读、提示淡出被误判成多次拾取。\n"
                     "提示淡出较慢、或跨零点挂机时，可适当调大；\n"
                     "自动拾取很快、连续同名掉落被少记时，可调小到 1.0 秒。")

        # 识别哪几样：折叠区，每一项一张子卡片
        self.kind_switches = {}
        kind_items = []
        for key, ic_name, name, desc, tip in (
                ("enable_mora", "coins", "摩拉", "识别并统计拾取到的摩拉",
                 "统计「获得」栏里的摩拉。\n"
                 "摩拉读数偶尔会与角色伤害数字重叠，造成异常大值 —— "
                 "「统计」标签页里的「摩拉单次计数上限」就是拦这个的。"),
                ("enable_material", "swords", "材料", "识别并统计怪物掉落的素材",
                 "统计怪物掉落与采集到的素材。\n"
                 "只统计**识别名单**里的名字；名单外的名字不会入账，"
                 "只会记进识别日志备查（名单在「统计」标签页里改）。"),
                ("enable_artifact", "gem", "狗粮", "识别并统计拾取的圣遗物",
                 "统计拾取到的圣遗物（俗称狗粮）。\n"
                 "判定依据是圣遗物名表与套装关键词，名单外的名字不会入账。")):
            sw = Switch(self, bool(self.cfg.get(key, True)))
            sw.toggled.connect(lambda v, k=key: self._on_kinds_changed(k, v))
            self.kind_switches[key] = sw
            kind_items.append((ic_name, name, desc, sw, None, tip))
        self.kind_acc = Accordion(self, "target", "识别哪几样",
                                  "选择需要统计的物品种类",
                                  items=kind_items, alpha=self.alpha,
                                  tip="关掉某一类的识别开关后，该类物品即使被认出来也不会入账，"
                                      "可以省下对应的处理开销。\n"
                                      "「材料」和「狗粮」只统计识别名单里的名字，"
                                      "名单在「统计」标签页里维护。")
        self.add_card(self.kind_acc)
        self._sync_kind_desc()

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _sync_kind_desc(self):
        names = [n for k, n in (("enable_mora", "摩拉"), ("enable_material", "材料"),
                                ("enable_artifact", "狗粮"))
                 if self.kind_switches[k].isChecked()]
        self.kind_acc.desc_label.setText(
            f"当前识别：{'、'.join(names) if names else '（都不识别）'}"
            "　·　展开后勾选；不需要统计的取消勾选")

    def _on_kinds_changed(self, key, val):
        self.cfg.set(key, bool(val))
        self._sync_kind_desc()
        self.cfg.apply_live()

    def _on_change_level(self, v):
        """灵敏度：写进识别核心真正读的 change_threshold

        档位：性能 1.0 / 标准 2.0 / 省电 4.0 / 极致省电 8.0（越小越灵敏）
        """
        thr = level_value(config_manager.CHANGE_LEVELS, v, 2.0)
        self.cfg.set("change_threshold", thr)
        self.cfg.set("change_level", v)      # 一起写，避免显示/实际不一致
        self.cfg.apply_live()

    def _on_event_window(self, v):
        try:
            sec = float(str(v).replace("秒", "").strip())
        except Exception:
            return
        self.cfg.set("event_end_window", sec)
        self.cfg.apply_live()

    def _on_ocr_interval(self, v):
        """频率：性能 100 / 标准 150 / 省电 250 / 极致省电 500（毫秒）"""
        ms = level_value(config_manager.OCR_LEVELS, v, 150)
        self.cfg.set("ocr_interval", ms)
        self.cfg.apply_live()

    def _on_tick(self):
        try:
            v = max(10, min(5000, int(self.tick_entry.text().strip())))
        except Exception:
            v = 50
        self.tick_entry.setText(str(v))
        self.cfg.set("tick_interval", v)


class BehaviorTab(SettingsTab):
    """行为：只在原神前台时识别 / 关闭按钮行为 / 全局热键录制。"""

    def __init__(self, parent, cfg, alpha):
        super().__init__(parent, cfg, alpha)

        self.only_fg = Switch(self, bool(self.cfg.get("only_foreground", True)))
        self.only_fg.toggled.connect(
            lambda v: self.cfg.set("only_foreground", bool(v)))
        self.row("crosshair", "只在原神前台时识别",
                 "仅在原神处于前台时识别；切出后自动暂停", self.only_fg,
                 tip="开启后，原神窗口不在前台时直接跳过这一轮：不截图、不识别，"
                     "既省性能，也避免把浏览器/聊天窗口上的文字当成掉落。\n"
                     "关掉它＝任何窗口在前台都照常识别，只在多开或特殊录屏场景下需要。")

        self.close_dd = self._dd(["每次询问", "最小化到托盘", "直接退出"])
        self.close_dd.setCurrentText({
            "ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"
        }.get(str(self.cfg.get("close_behavior", "ask")), "每次询问"))
        self.close_dd.currentTextChanged.connect(self._on_close_behavior)
        self.row("x", "点右上角 ✕ 时", "点击标题栏关闭按钮时的行为", self.close_dd,
                 tip="决定点窗口右上角 ✕ 之后发生什么：\n"
                     "· 每次询问 —— 弹窗让你选，防止误关；\n"
                     "· 最小化到托盘 —— 窗口收起但程序继续运行，监测不中断；\n"
                     "· 直接退出 —— 立即关闭并保存数据。\n"
                     "想让挂机不被打断，选「最小化到托盘」。")

        # ---- 全局热键（收成一张折叠卡片）----
        # 每个动作一个按钮，点按钮后按下想用的键即可录制。
        # _hotkey_btns 记着「设置里的键名 -> 按钮」，录制时按名字找按钮。
        self._hotkey_btns = {}
        self._capturing = None
        hk_items = []
        for key, ic_name, title, desc, tip in (
                ("hotkey", "play", "开始 / 停止监测",
                 "按下即开始监测；再次按下停止",
                 "同一个键负责开始和停止：正在监测时按下就停止。\n"
                 "建议选游戏里不常用的键（如 F9），避免与游戏操作冲突。"),
                ("hotkey_bar", "chart-column", "显示 / 隐藏统计条",
                 "按下显示统计条；再次按下隐藏",
                 "控制桌面统计条的显示与隐藏。\n"
                 "全屏游戏时按一下就能看当次收益，不用切窗口。")):
            btn = small_button(str(self.cfg.get(key, "关闭")), None, self.alpha,
                               width=120, height=30)
            btn.clicked.connect(lambda _=False, k=key: self._start_hotkey_capture(k))
            self._hotkey_btns[key] = btn
            hk_items.append((ic_name, title, desc, btn, None, tip))

        hk_tip = QLabel("点击右侧按钮后按下目标按键即可设置，Esc 取消；不使用则保持「关闭」")
        hk_tip.setStyleSheet(label_qss(T.DIM, 12))
        hk_tip.setWordWrap(True)

        self.hotkey_acc = Accordion(self, "keyboard", "全局热键",
                                    "系统级热键，游戏内同样生效",
                                    items=hk_items, footer=hk_tip,
                                    alpha=self.alpha,
                                    tip="热键在系统范围内生效，游戏全屏时同样可用。\n"
                                        "设置方法：点右侧按钮，再按下目标按键；按 Esc 取消。\n"
                                        "同一个按键不能同时分配给两个动作，"
                                        "按键冲突时会提示更换。")
        self.add_card(self.hotkey_acc)

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_close_behavior(self, text):
        self.cfg.set("close_behavior", {
            "每次询问": "ask", "最小化到托盘": "tray", "直接退出": "exit"}.get(text, "ask"))

    def _start_hotkey_capture(self, which="hotkey"):
        """开始录制热键

        which 指明这次是给哪个动作录：设置里的键名（hotkey / hotkey_bar …）。
        """
        self._capturing = which
        if which not in self._hotkey_btns:
            return
        self._hotkey_btns[which].setText("请按下按键…（Esc 取消）")
        # ⚠ 焦点要给 `focus_host`（设置页），**不是这个标签页** ——
        #   `keyPressEvent` 装在页面身上，焦点给标签页的话按键收不到。
        self.focus_host.setFocus()

    def on_key(self, e):
        """处理一次按键（设置页收到 keyPressEvent 后转发过来）。

        返回 True 表示这次按键被吃掉了。
        """
        which = getattr(self, "_capturing", None)
        if not which:
            return False
        btn = self._hotkey_btns.get(which)
        cur = str(self.cfg.raw.get(which, "关闭"))
        self._capturing = None
        if btn is None:
            return True
        k = e.key()
        if k == Qt.Key_Escape:
            btn.setText(cur)
            return True
        name = _qt_key_name(e)
        if name is None:
            btn.setText(cur)
            return True
        # 同一个键不能同时给两个动作用 —— 不然按一下触发两个
        for other, obtn in self._hotkey_btns.items():
            if other != which and str(self.cfg.raw.get(other, "关闭")) == name:
                QMessageBox.information(
                    self, "这个键已经用过了",
                    f"「{name}」已分配给其他动作，请更换按键。")
                btn.setText(cur)
                return True
        self.cfg.set(which, name)
        btn.setText(name)
        return True


def _qt_key_name(e):
    """Qt 的按键 -> 设置里存的名字（跟 Tk 版用同一套字符串格式）"""
    from PySide6.QtCore import Qt as _Qt
    mods = e.modifiers()
    parts = []
    if mods & _Qt.ControlModifier:
        parts.append("Ctrl")
    if mods & _Qt.AltModifier:
        parts.append("Alt")
    if mods & _Qt.ShiftModifier:
        parts.append("Shift")
    if mods & _Qt.MetaModifier:
        parts.append("Win")
    k = e.key()
    if _Qt.Key_A <= k <= _Qt.Key_Z:
        parts.append(chr(k))
    elif _Qt.Key_0 <= k <= _Qt.Key_9:
        parts.append(chr(k))
    elif _Qt.Key_F1 <= k <= _Qt.Key_F24:
        parts.append(f"F{k - _Qt.Key_F1 + 1}")
    else:
        m = {_Qt.Key_Space: "SPACE", _Qt.Key_Tab: "TAB", _Qt.Key_Return: "RETURN",
             _Qt.Key_Backspace: "BACKSPACE", _Qt.Key_Insert: "INSERT",
             _Qt.Key_Delete: "DELETE", _Qt.Key_Home: "HOME", _Qt.Key_End: "END",
             _Qt.Key_PageUp: "PRIOR", _Qt.Key_PageDown: "NEXT",
             _Qt.Key_Up: "UP", _Qt.Key_Down: "DOWN", _Qt.Key_Left: "LEFT",
             _Qt.Key_Right: "RIGHT", _Qt.Key_Minus: "MINUS", _Qt.Key_Equal: "EQUAL",
             _Qt.Key_BracketLeft: "BRACKETLEFT", _Qt.Key_BracketRight: "BRACKETRIGHT",
             _Qt.Key_Backslash: "BACKSLASH", _Qt.Key_Semicolon: "SEMICOLON",
             _Qt.Key_Apostrophe: "APOSTROPHE", _Qt.Key_Comma: "COMMA",
             _Qt.Key_Period: "PERIOD", _Qt.Key_Slash: "SLASH", _Qt.Key_QuoteLeft: "GRAVE"}
        name = m.get(k)
        if name is None:
            return None
        parts.append(name)
    if not parts:
        return None
    return "+".join(parts)


class StatsTab(SettingsTab):
    """统计：换日刷新 / 识别名单 / 黑名单 / 白名单。

    ⚠ 这是设置页里最重的一个标签页：黑名单 / 白名单是**三层折叠卡片**，
      而且「离开设置页时的空名单提醒」也归它管（设置页留了个转发）。
    """

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win

        # ---- 摩拉单次计数上限 ----
        # 战斗时角色伤害数字会跟「获得」栏的摩拉读数叠在一起，OCR 可能一次
        # 读出「摩拉 12500」这种，一笔就把摩拉统计顶上天（几万、几十万都出现过）。
        # 超过这个上限的读数一律当误读丢掉（同时写进识别日志，来源列标「未统计」）。
        # 0 = 不限制（老行为）。
        cap = int(self.cfg.get("mora_max_amount", 3000) or 0)
        self.mora_cap_entry = QLineEdit(str(cap))
        self.mora_cap_entry.setFixedWidth(90)
        self.mora_cap_entry.setAlignment(Qt.AlignCenter)
        self.mora_cap_entry.setStyleSheet(entry_qss())
        self.mora_cap_entry.editingFinished.connect(self._on_mora_cap)
        _tip = ("战斗时角色的伤害数字会与「获得」栏的摩拉读数重叠，"
                "可能一次读出数万甚至数十万的异常值。\n"
                "超过该上限的读数一律判为误读：不计入摩拉统计，"
                "只写进识别日志（来源列标「未统计」）备查。\n\n"
                "填 0 表示不限制。")
        self.mora_cap_entry.setToolTip(_tip)
        _r = self.row("coins", "摩拉单次计数上限",
                      "单次读数上限；超过即判为误读并丢弃，0 为不限制",
                      self.mora_cap_entry, tip=_tip)

        # ---- 换日刷新数据（折叠卡片，默认收起）----
        # 展开里面两组：总开关 + 换日时间，每组下面紧跟一句说明。
        # 关掉开关就**完全不换日**，数据一直累着，直到手动清空。
        #
        # 排版：说明要跟它那一行贴在一起（组内 2px），两组之间才留大间距（14px）。
        # 以前每样都是 12px 平铺，说明就飘在两行正中间，看着空隙特别大。
        self.ro_switch = Switch(self,
                                bool(self.cfg.get("rollover_enabled", True)))
        self.ro_switch.toggled.connect(self._on_rollover_enabled)

        self.ro_entry = QLineEdit(str(int(self.cfg.get("rollover_hour", 0) or 0)))
        self.ro_entry.setFixedWidth(70)
        self.ro_entry.setAlignment(Qt.AlignCenter)
        self.ro_entry.setStyleSheet(entry_qss())
        self.ro_entry.editingFinished.connect(self._on_rollover)
        hour_box = QWidget()
        hl = QHBoxLayout(hour_box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self.ro_entry)
        unit = QLabel("点")
        unit.setStyleSheet(label_qss(T.DIM, 13))
        hl.addWidget(unit)

        ro_items = [
            ("refresh-cw", "启用换日刷新",
             "关闭后不再自动换日，数据持续累计", self.ro_switch, None,
             "按设定时间把当日数据归档、并重新开始统计（相当于「今天」这个概念翻页）。\n"
             "关闭后**完全不会自动换日**，数据一直累计，直到你手动清空 —— "
             "适合想统计「这一周总共刷了多少」的场景。"),
            ("clock", "换日时间（整点 0~23）",
             "跨零点挂机可适当延后，避免中途重新统计", hour_box, None,
             "每天几点算「新的一天」，默认 0 点（自然日），可设 0~23 整点。\n"
             "跨零点还在挂机的，建议设成 4 点：游戏本身也是凌晨 4 点刷日常，"
             "这样不会半夜打到一半被归档。"),
        ]
        self.ro_acc = Accordion(self, "sunrise", "换日刷新数据",
                                "到达设定时间后归档当日数据并重新开始统计",
                                items=ro_items, alpha=self.alpha,
                                tip="换日＝把当日统计归档，并从零开始累计新的一天。\n"
                                    "归档后的历史仍可在「收益细则」页查到，不会被删除。")
        self.add_card(self.ro_acc)

        # ---- 识别名单 ----
        # 放「统计」里（不放「开发」）—— 这个是日常要用的：
        # 识别到什么材料都按这个名单判定，名字错了或者漏了要能随时改。
        warn = QLabel("⚠ 名单决定可识别的物品范围。不在名单中的名称不会被统计；"
                      "若名单被清空，将无法识别任何物品，请用「恢复默认名单」还原。")
        warn.setWordWrap(True)
        warn.setStyleSheet(label_qss("#E06C5A", 12, True))
        self.mat_acc = Accordion(
            self, "clipboard-list", "识别名单",
            "不要乱改！！！",
            items=self._make_mat_items(), alpha=self.alpha, footer=warn,
            tip="名单决定**哪些名字算数**：认出来的名字不在名单里，一律不入账，"
                "只会记进识别日志备查。\n"
                "内置名单含材料与圣遗物共 800 多条，正常游玩无需改动；"
                "只有遇到「某个明明捡到了却没统计」才需要往里加名字。\n"
                "**名单被清空会导致什么都识别不到**，误删请用「恢复默认名单」。")
        self.add_card(self.mat_acc)
        self._refresh_mat_count()

        # ---- 黑名单 / 白名单（决定「认出来了要不要记账」）----
        # 层级（用户指定）：
        #   黑名单管理 ▸  材料黑名单 [开关] ▸ 配置名单 ▸ …
        #                圣遗物黑名单 [开关] ▸ 配置名单 ▸ …
        #   白名单管理 ▸  材料白名单 [开关] ▸ 配置名单 ▸ …
        #                圣遗物白名单 [开关] ▸ 配置名单 ▸ …
        # 主卡片**没有开关**，开关在材料 / 圣遗物那一层；开了才出现配置卡片。
        self.filter_switches = {}       # 名单键 -> Switch（在卡片头上）
        self.filter_units = {}          # 名单键 -> SwitchAccordion
        self.filter_cfg_accs = {}       # 名单键 -> 「配置名单」折叠卡片
        self.filter_sub_accs = {}       # 名单键 -> 同 units（老名字，留着兼容）
        for kind, kind_label, icon_name, main_title, main_desc in (
                ("black", "黑名单", "eye-off", "黑名单管理",
                 "名单里的物品识别到了也不记账"),
                ("white", "白名单", "square-check", "白名单管理",
                 "只记账名单里的物品，其余一律不记")):
            self.add_card(
                self._build_filter_group(kind, kind_label, icon_name,
                                         main_title, main_desc))

    # ---------- 黑名单 / 白名单 ----------

    def _build_filter_group(self, kind, kind_label, icon_name,
                            main_title, main_desc):
        """一张主卡片（黑名单管理 / 白名单管理）。

        层级（用户指定）：
            主卡片（**没有开关**）         <- Accordion
              └ 材料XX名单  [开关]         <- SwitchAccordion
                   点标题展开 →「配置名单」<- 自己给的控件，不再被包卡片
        """
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        for cat, cat_label in (("material", "材料"), ("artifact", "圣遗物")):
            key = f"{cat}_{kind}"
            label = f"{cat_label}{kind_label}"
            is_white = (kind == "white")
            filt_desc = (f"只记账名单里的{cat_label}" if is_white
                         else f"名单里的{cat_label}不记账")

            # 「配置名单」那张卡片（内容区的真正内容）
            # ⚠ 图标名要写**存在的**：icons 里没有 "list"，写错了 Qt 会把名字
            #   当**文字**画出来（这里以前就画着"list"四个字母）。
            # ⚠ 原来这里是 `lambda k=key: self._open_filter(k)` ——
            #   clicked 塞进来的 checked(False) 会把 k 顶掉，点这张卡片
            #   实际是 `_open_filter(False)`（2026-10-04 顺手修掉）。
            cfg_btn = small_button(
                "配置名单", bind_cb(self._open_filter, key), self.alpha,
                icon="file-text", width=104, height=30)
            cfg_acc = Accordion(
                body, "file-text", "配置名单",
                self._filter_cfg_desc(key, label, []),
                items=[("file-text", label, "打开后搜索、勾选", cfg_btn, None,
                        ("打开名单编辑窗，可以按名字搜索、勾选需要的"
                         f"{'材料' if cat == 'material' else '圣遗物'}。\n"
                         "名单里已选中的项会打勾，改完直接生效。"))],
                alpha=T.panel_alpha(self.alpha),
                tip="这张卡片里放的就是当前名单的内容，"
                    "点「配置名单」按钮打开编辑窗。")
            self.filter_cfg_accs[key] = cfg_acc

            if kind == "white":
                unit_tip = (f"开启后**只有**名单里的{cat_label}会被记账，"
                            "名单之外的一律不统计。\n"
                            "⚠ 白名单开着但**名单为空**时，什么都记不了；"
                            "离开设置页时会弹窗提醒并自动关闭白名单。\n"
                            "适合「只想统计某几样」的场景。")
            else:
                unit_tip = (f"开启后，名单里的{cat_label}即使认出来也不记账。\n"
                            "黑名单为空不影响识别，只是不排除任何物品。\n"
                            "适合把不关心的掉落（如常见垃圾材料）排除在统计之外。")
            unit = SwitchAccordion(
                body, icon="layers", title=label, desc=filt_desc,
                alpha=T.panel_alpha(self.alpha),
                checked=svc_names.is_enabled(self.cfg.raw, key),
                body=cfg_acc, tip=unit_tip)
            unit.toggled.connect(
                lambda v, k=key, lb=label: self._on_filter_toggled(k, v, lb))
            self.filter_units[key] = unit
            self.filter_switches[key] = unit.switch
            self.filter_sub_accs[key] = unit

            bl.addWidget(unit)

        if kind == "white":
            main_tip = ("白名单＝**只记账名单里的物品**，其余一律不记。\n"
                        "开关在下面「材料白名单 / 圣遗物白名单」那一层，"
                        "开了才会出现「配置名单」。\n"
                        "⚠ 白名单为空会导致该类物品完全统计不到，"
                        "离开设置页时会有提醒。")
        else:
            main_tip = ("黑名单＝**名单里的物品不记账**，其余照常统计。\n"
                        "开关在下面「材料黑名单 / 圣遗物黑名单」那一层，"
                        "开了才会出现「配置名单」。\n"
                        "黑名单为空不影响识别，只是不排除任何物品。")
        return Accordion(self, icon_name, main_title, main_desc,
                         items=None, body_widget=body, alpha=self.alpha,
                         tip=main_tip)

    @staticmethod
    def _filter_cfg_desc(key, label, names):
        """配置名单那张卡片的简介：带上当前有几个名字"""
        cat = "材料" if key.startswith("material") else "圣遗物"
        n = len(names or [])
        if not n:
            return f"还没配任何{cat} —— 打开后搜索、勾选"
        return f"已配 {n} 个{cat}，打开后可继续增删"

    def _on_filter_toggled(self, key, val, label):
        """开关一变：写设置 + 让「配置名单」跟着显隐"""
        filters = svc_names.get(self.cfg.raw)
        filters[key]["enabled"] = bool(val)
        self.cfg.set("records.filters", filters)
        acc = self.filter_cfg_accs.get(key)
        if acc is not None:
            acc.desc_label.setText(
                self._filter_cfg_desc(key, label, filters[key]["names"]))

    def _open_filter(self, key):
        """打开某张名单的配置窗"""
        import qt_dialogs
        label = svc_names.KEY_LABEL.get(key, key)
        cat = "材料" if key.startswith("material") else "圣遗物"
        is_white = key.endswith("_white")
        desc = (f"只有在这张名单里的{cat}才会被记账；名单为空则什么都记不了。"
                if is_white else
                f"在这张名单里的{cat}识别到了也不记账。")
        try:
            import svc_names
            d = svc_names.load()
            pool = d.get("materials" if cat == "材料" else "artifacts") or []
        except Exception:
            pool = []
        cur = svc_names.names_of(self.cfg.raw, key)
        dlg = qt_dialogs.NameListDialog(self, key, f"配置{label}", desc,
                                        pool, cur, alpha=self.alpha)
        if dlg.exec() != QDialog.Accepted:
            return
        filters = svc_names.get(self.cfg.raw)
        filters[key]["names"] = dlg.chosen()
        self.cfg.set("records.filters", filters)
        acc = self.filter_cfg_accs.get(key)
        if acc is not None:
            acc.desc_label.setText(
                self._filter_cfg_desc(key, label, filters[key]["names"]))

    # ---------- 离开设置页时的空名单提醒 ----------

    def warn_empty_filters(self):
        """检查「开着但空着」的名单，弹窗提醒 + 自动关掉白名单。

        用户要求：
          · 弹窗要弹在**应用正中间**
          · 白名单为空 = 识别不到任何内容，文案要提到「去识别里关掉」
            并且**自动把该白名单关掉**（提示语里写「白名单功能已关闭」）
          · 弹完才切页 —— 所以主窗口必须在 setCurrentIndex **之前**调它

        ⚠ 第 9 批之前这是 `PageSettings.on_hide`；现在本体在这个标签页里，
          设置页的 `on_hide` 只负责转发一下（因为它才是「页面」）。
        """
        whites = svc_names.empty_enabled_whitelists(self.cfg.raw)
        blacks = svc_names.empty_enabled_blacklists(self.cfg.raw)
        if not whites and not blacks:
            return

        lines = []
        for key in whites:
            label = svc_names.KEY_LABEL.get(key, key)
            cat = "材料" if key.startswith("material") else "圣遗物"
            enable_key = ("enable_material" if cat == "材料"
                          else "enable_artifact")
            if bool(self.cfg.get(enable_key, True)):
                tip = ("如不需要识别这项内容，可前往「设置 → 识别」里"
                       "将其关闭。")
            else:
                tip = ("如需重新识别这项内容，可前往「设置 → 识别」里"
                       "重新开启。")
            lines.append(f"「{label}」为空，将识别不到{cat}任何内容。\n"
                         f"{tip}\n白名单功能已关闭。")
        for key in blacks:
            label = svc_names.KEY_LABEL.get(key, key)
            cat = "材料" if key.startswith("material") else "圣遗物"
            lines.append(f"「{label}」为空，不会过滤任何{cat}。\n"
                         "（黑名单为空不影响识别，只是不排除任何物品。）")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("名单为空")
        box.setText("检测到名单已开启但没有内容")
        box.setInformativeText("\n\n".join(lines))
        box.setStandardButtons(QMessageBox.Ok)
        box.setStyleSheet(f"""
            QMessageBox {{ background: {T.BG}; }}
            QMessageBox QLabel {{ color: {T.TEXT}; background: transparent; }}
        """)
        self._center_on_app(box)
        box.exec()

        # 白名单：自动关掉（用户要求「白名单功能已关闭」）
        if whites:
            filters = svc_names.get(self.cfg.raw)
            for key in whites:
                filters[key]["enabled"] = False
            self.cfg.set("records.filters", filters)
            for key in whites:
                sw = self.filter_switches.get(key)
                if sw is not None:
                    sw.blockSignals(True)
                    sw.setChecked(False)
                    sw.blockSignals(False)
                acc = self.filter_cfg_accs.get(key)
                if acc is not None:
                    acc.setVisible(False)

    def _center_on_app(self, dlg):
        """把一个弹窗摆到**应用窗口正中间**（用户要求）"""
        try:
            win = self.window()
            dlg.adjustSize()
            g = win.frameGeometry()
            dlg.move(g.center().x() - dlg.width() // 2,
                     g.center().y() - dlg.height() // 2)
        except Exception:
            pass

    # ---------- 识别名单 ----------

    def _make_mat_items(self):
        """识别名单那一组子卡片（挂在「统计」页）"""
        items = []

        # 1) 管理识别名单
        self.name_count_label = QLabel("")
        self.name_count_label.hide()
        edit_btn = small_button("管理…", self._open_material_editor, self.alpha,
                                icon="clipboard-list", width=84, height=30)
        items.append(("clipboard-list", "管理识别名单",
                      "查看、增删名单里的名字", edit_btn, None,
                      "打开名单编辑器，可以搜索、勾选、增删名字，"
                      "也可以把不在名单里的名字加进去。\n"
                      "改完立即生效，不用重启软件。\n"
                      "「材料 N 个 / 圣遗物 N 个」显示的是当前名单规模。"))

        # 2) 恢复默认名单
        reset_btn = small_button("恢复默认", self._reset_names, self.alpha,
                                 kind="danger", icon="refresh-cw", width=104,
                                 height=30)
        items.append(("refresh-cw", "恢复默认名单",
                      "恢复成内置名单", reset_btn, None,
                      "把识别名单还原成程序内置的那一份。\n"
                      "⚠ 你自己加过或删过的名字都会丢失（会先弹窗确认）。\n"
                      "误删导致什么都识别不到时，用这个恢复。"))

        return items

    def _reset_names(self):
        """恢复默认识别名单"""
        import svc_names
        try:
            cur = svc_names.load()
            n = len(cur["materials"]) + len(cur["artifacts"])
        except Exception:
            n = 0
        if QMessageBox.question(
                self, "恢复默认名单",
                "会把识别名单还原成内置的那份。\n\n"
                "你自己加过或删过的名字都会没掉。\n"
                f"当前名单 {n} 个。确定吗？") != QMessageBox.Yes:
            return
        try:
            svc_names.reset_to_default()
            # ⚠ 原来是裸的 `reload_names()` —— 那个名字在 qt_pages 里**根本没定义**
            #   （列表还老是提示"恢复失败：name 'reload_names' is not defined"），
            #   正确入口是 svc_capture.reload_names（下面的"管理…"一直用的是它）。
            svc_capture.reload_names()
            self._refresh_mat_count()
            msg_info(self, "已恢复", "识别名单已还原成内置的。")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"恢复失败：{e}")

    def _refresh_mat_count(self):
        try:
            import svc_names
            d = svc_names.load()
            txt = (f"材料 {len(d['materials'])} 个　"
                   f"圣遗物 {len(d['artifacts'])} 个")
        except Exception:
            txt = "（读取失败）"
        self.name_count_label.setText(txt)
        acc = getattr(self, "mat_acc", None)
        if acc is not None:
            for c in acc.item_cards:
                if c.title_label.text() == "管理识别名单":
                    c.desc_label.setText(txt)

    def _open_material_editor(self):
        from qt_dialogs import MaterialDialog
        dlg = MaterialDialog(self._win, self.alpha)
        dlg.exec()
        # 改完名单立刻生效（detector 里的集合是原地更新的）
        try:
            svc_capture.reload_names()
        except Exception:
            pass
        self._refresh_mat_count()

    def _reset_materials(self):
        """旧名字，保留兼容（现在的入口是「恢复默认名单」）"""
        self._reset_names()

    # ---- 换日刷新 ----

    def _on_mora_cap(self):
        """摩拉单次计数上限：写进设置。

        ⚠ 这里**不用** `apply_live()`：识别器是每次解析时现读
          `settings["mora_max_amount"]` 的（见 `detector._mora_over_limit`），
          所以改完立刻生效，不需要推给正在跑的那个实例。
        """
        try:
            v = int(float(self.mora_cap_entry.text().strip()))
        except Exception:
            v = 3000
        v = max(0, min(9999999, v))
        self.mora_cap_entry.setText(str(v))
        self.cfg.set("mora_max_amount", v)

    def _on_rollover(self):
        try:
            h = int(self.ro_entry.text().strip()) % 24
        except Exception:
            h = 0
        self.ro_entry.setText(str(h))
        self.cfg.set("rollover_hour", h)

    def _on_rollover_enabled(self, v):
        """换日刷新数据的总开关"""
        self.cfg.set("rollover_enabled", bool(v))


class UpgradeTab(SettingsTab):
    """升级：更新渠道 + 检测更新（+ 自动更新那套下载/替换）。

    ⚠ 这一页有两个东西**必须从外面够得着**：
      · `update_dot` —— 检测到新版本时，侧栏/标签上的红点要跟着亮
        （设置页的 `set_update_badge` 找它）
      · `update_row` —— 侧栏点红点要能滚到「版本更新」那一行
        （设置页的 `goto_update` 找它）

    ⚠ 检测更新的结果是从**后台线程**发回来的，所以信号定义在**这个类**上
      （原来定义在 `PageSettings` 上）。后台线程绝对不能直接碰控件。
    """

    update_checked = Signal(object, object)      # 检测更新结果（从后台线程发回来）

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win
        self.update_checked.connect(self._update_result)

        # ---- 版本卡片（hero）----
        # 2026-10-04 改版：原来这一页只有两行、底下大半页空白，用户说"太丑"。
        # 现在把版本号、状态、按钮、进度、更新说明全收进**一张卡片**，
        # 跟新的卡片弹窗一个调性（大号版本号 + 状态胶囊 + 强调色按钮）。
        card = Card(self, alpha=self.alpha)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.ver_label = QLabel(f"StatGI {VERSION}")
        self.ver_label.setStyleSheet(T.title_qss(26))
        top.addWidget(self.ver_label)
        top.addStretch(1)
        self.state_pill = QLabel("还没检测")
        self.state_pill.setStyleSheet(self._pill_qss(T.DIM))
        top.addWidget(self.state_pill, 0, Qt.AlignTop)
        cl.addLayout(top)

        self.detail_label = QLabel("点「检测更新」去网上比对最新版本（需联网）")
        self.detail_label.setStyleSheet(label_qss(T.DIM, 12))
        self.detail_label.setWordWrap(True)
        cl.addWidget(self.detail_label)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.update_btn = QPushButton("检测更新")
        # 用最小宽度而不是固定 130 —— 固定宽度会让按钮比文字宽一大截，
        # 挂在它右上角的红点看着就像挂在卡片上了
        self.update_btn.setMinimumWidth(108)
        self.update_btn.setFixedHeight(34)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setStyleSheet(btn_qss("accent", self.alpha))
        set_btn_icon(self.update_btn, "refresh-cw", 15, color="#08222E")
        self.update_btn.clicked.connect(self._on_check_update)
        btns.addWidget(self.update_btn)

        self.page_btn = QPushButton("打开发布页")
        self.page_btn.setMinimumWidth(108)
        self.page_btn.setFixedHeight(34)
        self.page_btn.setCursor(Qt.PointingHandCursor)
        self.page_btn.setStyleSheet(btn_qss("normal", self.alpha))
        set_btn_icon(self.page_btn, "globe", 15)
        self.page_btn.clicked.connect(self._open_release_page)
        self.page_btn.setEnabled(False)          # 还不知道地址，检测到再亮
        btns.addWidget(self.page_btn)
        btns.addStretch(1)
        cl.addLayout(btns)

        # ---- 下载进度（只有真在下载时才出现）----
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(18)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background:{rgba('#FFFFFF', 20)}; border:none;"
            f" border-radius:9px; text-align:center; color:{T.TEXT};"
            f" font-size:11px; }}"
            f"QProgressBar::chunk {{ background:{T.ACCENT}; border-radius:9px; }}")
        self.progress.hide()
        cl.addWidget(self.progress)

        # ---- 更新说明（发现新版本时才出现）----
        self.notes_box = QFrame()
        self.notes_box.setStyleSheet(
            f"QFrame {{ background:{rgba('#FFFFFF', 12)}; border:none;"
            f" border-radius:10px; }}")
        nl = QVBoxLayout(self.notes_box)
        nl.setContentsMargins(14, 12, 14, 12)
        nl.setSpacing(8)
        self.notes_title = QLabel("")
        self.notes_title.setStyleSheet(label_qss(T.ACCENT, 14, True))
        nl.addWidget(self.notes_title)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notes_label.setStyleSheet(label_qss(T.TEXT, 13))
        nl.addWidget(self.notes_label)
        self.go_btn = QPushButton("立即更新")
        self.go_btn.setFixedHeight(34)
        self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.setStyleSheet(btn_qss("accent", self.alpha))
        self.go_btn.clicked.connect(self._on_go_update)
        nl.addWidget(self.go_btn)
        self.notes_box.hide()
        cl.addWidget(self.notes_box)

        self.add_card(card)
        # ⚠ 侧栏点红点要滚到这一行 —— `update_row` 这个名字必须留着
        self.update_row = card
        # 检测到新版本时挂个红点（挂在**按钮**右上角，不是整张卡片上）
        self.update_dot = RedDot(self.update_btn)

        # ---- 更新渠道 ----
        # 国内用 Gitee 快；GitHub 的 API 有每小时 60 次的限流，
        # 所以版本信息走的是仓库里的 version.json（raw 地址，不限流）。
        self.channel_dd = self._dd([n for n, _v in
                                    __import__("qt_update").CHANNELS], width=170)
        _cur = str(self.cfg.get("update_channel", "auto") or "auto")
        self.channel_dd.setCurrentText(
            {"auto": "自动", "gitee": "Gitee（国内快）",
             "github": "GitHub"}.get(_cur, "自动"))
        self.channel_dd.currentTextChanged.connect(self._on_update_channel)
        self.row("globe", "更新渠道",
                 "更新检测与安装包下载源；国内推荐 Gitee",
                 self.channel_dd,
                 tip="决定「检测更新」走哪个下载源：\n"
                     "· 自动 —— 按网络情况在 Gitee / GitHub 之间挑一个能用的；\n"
                     "· Gitee（国内快）—— 国内下载速度更稳；\n"
                     "· GitHub —— 更新说明与发布页在 GitHub 上时选它。\n"
                     "版本信息本身走仓库里的说明文件，不限流；"
                     "只有下载安装包才走上面选的源。")
        self._info = None            # 最近一次检测结果（「立即更新」要用）

    # ---- 小工具 ----

    @staticmethod
    def _pill_qss(color):
        """状态胶囊（圆角小标签）"""
        return (f"color:{color}; background:{rgba(color, 40)};"
                f" border-radius:10px; padding:4px 12px;"
                f" font-family:'{T.FONT}'; font-size:12px; font-weight:600;")

    def _set_state(self, text, color, detail=""):
        self.state_pill.setText(str(text))
        self.state_pill.setStyleSheet(self._pill_qss(color))
        if detail:
            self.detail_label.setText(str(detail))
            self.detail_label.setStyleSheet(label_qss(T.DIM, 12))

    def _open_release_page(self):
        url = str((self._info or {}).get("url", "") or "").strip()
        if url:
            try:
                __import__("webbrowser").open(url)
            except Exception:
                pass

    def _on_go_update(self):
        """卡片上那个「立即更新」

        ⚠ 2026-10-13 修：以前这里调 _do_auto_update 时，那个函数内部引用了
          本函数的局部变量 info → NameError → 窗口模式下看不到报错 →
          「按钮点了没反应」（0.9.5 就是这样，用户反馈"跟摆设一样"）。
          现在：notes 用参数传 ✓；任何异常都**弹窗告诉用户** ✗不再悄悄死掉。
        """
        info = self._info or {}
        up = None
        try:
            import qt_updater
            up = qt_updater.update_info_from({"update": info.get("update")})
        except Exception as e:
            up = None
            self._update_error(f"读取更新信息失败：{type(e).__name__}: {e}")
            return
        if not up:
            self._update_error(
                "这个版本没有准备自动更新包（清单里缺分卷地址）。\n"
                "请点「打开发布页」手动下载新版。")
            return
        try:
            self._do_auto_update(up, info.get("version", ""), info.get("notes", ""))
        except Exception as e:
            self._update_error(f"更新器启动失败：{type(e).__name__}: {e}")

    def _update_error(self, msg):
        """更新出错时**要让用户看见**（以前是悄悄死掉 ✗）"""
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._win or self, "更新", str(msg) +
                                "\n\n也可以点「打开发布页」手动下载更新。")
        except Exception:
            pass
        try:
            self._set_state("更新失败", "#E06C5A", str(msg).replace("\n", " "))
        except Exception:
            pass
        try:
            print("[更新] " + str(msg), flush=True)
        except Exception:
            pass

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_check_update(self):
        self._set_state("正在检测…", T.DIM, "正在联网比对，请稍候…")
        try:
            self.update_btn.setEnabled(False)     # 别让用户连点
        except Exception:
            pass
        import threading
        import qt_update

        ch = str(self.cfg.get("update_channel", "auto") or "auto")

        def _do():
            # 网络活儿在后台线程干，结果用信号发回主线程
            # （后台线程绝对不能直接碰控件）
            try:
                info, used, reason = qt_update.check(ch, bust_cache=True)
            except Exception:
                info, used, reason = None, "", "network"
            self.update_checked.emit(info, reason)

        threading.Thread(target=_do, daemon=True).start()

    def _update_result(self, info, reason):
        import qt_update
        if not info:
            self._set_state("检测失败", "#E06C5A",
                            f"{qt_update.reason_text(reason)}"
                            "　·　点「检测更新」重试")
            self.update_btn.setEnabled(True)
            return
        ver = info.get("version", "")
        used = qt_update.CHANNEL_NAMES.get(info.get("channel", ""), "")
        self._info = info
        self.update_btn.setEnabled(True)
        self.page_btn.setEnabled(bool(str(info.get("url", "") or "").strip()))
        if not info.get("is_newer"):
            # 远端不比本地新（包括远端更旧的情况）—— 都算「已是最新」
            self._set_state("已是最新", "#6CCB5F",
                            f"当前 {VERSION}　·　来自 {used}"
                            f"　·　{time.strftime('%H:%M')} 检测")
            self.notes_box.hide()
            return
        self._set_state(f"发现新版本 {ver}", T.ACCENT,
                        f"当前 {VERSION} → {ver}　·　来自 {used}")
        self._show_update_available(info)

    def _show_update_available(self, info):
        """发现新版本 —— **就在卡片里展开说明**，不再弹一个朴素对话框。

        2026-10-04 改版：原来发现新版本会弹 QDialog，跟新界面风格不搭；
        现在信息直接铺在卡片上（更新说明可选中复制），按钮也在这张卡片里。
        """
        ver = info.get("version", "")
        notes = str(info.get("notes", "") or "").strip()
        try:
            import qt_updater
            up = qt_updater.update_info_from({"update": info.get("update")})
        except Exception:
            up = None

        size_txt = ""
        if up and up.get("size"):
            size_txt = f"（安装包约 {up['size'] / 1024 / 1024:.0f} MB）"
        self.notes_title.setText(f"新版本 {ver} 更新内容{size_txt}")
        self.notes_label.setText(notes or "（这次没有写更新说明）")
        # 没有自动更新信息（version.json 里没带分卷地址）→ 只能去发布页手动下
        self.go_btn.setVisible(bool(up))
        if not up:
            self.detail_label.setText(
                f"当前 {VERSION} → {ver}　·　点右边「打开发布页」手动下载")
        self.notes_box.show()

    def _ask_update(self, info):
        """兼容旧调用：现在不弹窗了，直接在卡片里展开"""
        self._show_update_available(info)

    def _do_auto_update(self, up, ver, notes=""):
        """下载 → 合并 → 校验 → 解压 → 交给「更新.bat」去替换

        下载在**后台线程**跑，进度通过信号发回主线程更新界面 ——
        后台线程绝对不能直接碰控件。
        """
        import qt_updater
        from PySide6.QtCore import QObject, Signal

        class Sig(QObject):
            progress = Signal(int, int)
            msg = Signal(str)
            done = Signal(bool, str)

        # ⚠ 以前这里写的是 info.get("notes") —— info 是**上一个函数**的局部
        #   变量，会抛 NameError → 按钮点了毫无反应（0.9.5 同病）
        dlg = self._make_progress_dialog(ver, (up or {}).get("size", 0), notes)
        sig = Sig()
        state = {"dir": None, "cancel": False, "msg": "准备中…", "prog": (0, 0)}
        # ⚠ 「取消」以前是**假的**：点了只是把窗关掉，下载线程照样跑完，
        #   然后照样问你"现在开始更新？"、照样关软件 —— 点取消反而更懵。
        #   现在真的取消：拒绝即置位，`on_fin` 看到就掉头。
        dlg.rejected.connect(lambda: state.__setitem__("cancel", True))

        def on_p(p, t):
            # 进度、速度、MB 都在弹窗里自己算（它内部有采样窗口）
            dlg.set_progress(p, t)

        def on_msg(s):
            # 更新器说的话（正在校验 / 正在解压…）—— 直接显示在速度那一行；
            # 下载中紧接着的进度回调会把它盖回"速度 …"，所以不会打架
            state["msg"] = str(s)
            dlg.set_status(str(s))

        sig.progress.connect(on_p)
        sig.msg.connect(on_msg)

        def work():
            try:
                d = qt_updater.prepare(up, on_log=lambda s: sig.msg.emit(str(s)),
                                       on_progress=lambda a, b: sig.progress.emit(int(a), int(b)))
                state["dir"] = d
                sig.done.emit(True, "")
            except Exception as e:
                sig.done.emit(False, str(e))

        def on_fin(ok, err):
            if state["cancel"]:
                return                    # 用户取消了，什么都别做
            if not ok:
                QMessageBox.warning(self, "更新没做成",
                                    f"{err}\n\n当前版本不受影响，可稍后重试，"
                                    "或点击「打开下载页」手动下载。")
                dlg.reject()
                return
            try:
                bat = qt_updater.write_updater(state["dir"])
            except Exception as e:
                QMessageBox.warning(self, "更新没做成", f"准备更新脚本失败：{e}")
                dlg.reject()
                return
            dlg.accept()
            if not self._make_ready_dialog(ver):
                return
            if not qt_updater.launch_updater(bat):
                QMessageBox.warning(self, "启动更新失败",
                                    f"请手动双击这个文件完成更新：\n{bat}")
                dlg.reject()
                return
            dlg.accept()
            # 关掉自己，让更新脚本接手。
            # 三步走，越往后越狠：
            try:
                self._win.hide()         # 先藏窗口，别让用户盯着一个卡住的界面
            except Exception:
                pass
            try:
                self._win._shutdown()    # 停监测 / 关子窗口 / 停接口
            except Exception:
                pass
            qt_updater.force_quit_soon(3)   # 兜底：3 秒后强杀自己
            QApplication.quit()

        sig.done.connect(on_fin)

        import threading
        threading.Thread(target=work, daemon=True).start()
        dlg.exec()

    def _make_progress_dialog(self, ver, size=0, notes=""):
        """下载进度弹窗（旋转图标 + 进度条 + 速度 + 上面轮播公告/宝典）。

        2026-10-04 按用户草图重做；抽成方法是为了能**单独渲染/测试** ——
        不然它藏在「点立即更新 → 后台线程 → 信号」这条链路里，谁也看不见。
        """
        from qt_update_progress import UpdateProgressDialog
        return UpdateProgressDialog(self, alpha=self.alpha, ver=ver,
                                    size=size, notes=notes)

    def _make_ready_dialog(self, ver):
        """下载完 → 问「现在开始更新吗」（也是卡片式，跟前面一致）"""
        dlg = self._build_ready_dialog(ver)
        return dlg.exec() == QDialog.Accepted

    def _build_ready_dialog(self, ver):
        """只搭不显示 —— 方便单独渲染/测试"""
        dlg = CardDialog(self, alpha=self.alpha, title="更新已准备好",
                         width=340)
        dlg.set_subtitle(f"新版本 {ver} 已经下载好了。")
        body = QLabel("点「现在更新」之后：\n"
                      "· 软件自动关闭\n"
                      "· 自动完成替换（会弹出一个命令行窗口，别关它）\n"
                      "· 更新完自动重新打开\n\n"
                      "设置与收益数据不会被覆盖。")
        body.setWordWrap(True)
        body.setStyleSheet(label_qss(T.TEXT, 13))
        dlg.add_widget(body)
        dlg.add_secondary("稍后再说", dlg.reject)
        dlg.add_confirm("现在更新")
        dlg.fit_to_subtitle(0.85)
        return dlg

    def _on_update_channel(self, text):
        val = {"自动": "auto", "Gitee（国内快）": "gitee",
               "GitHub": "github"}.get(text, "auto")
        self.cfg.set("update_channel", val)
        # 换渠道后状态就不准了 —— 复位成"还没检测"
        self._set_state("还没检测", T.DIM, "换了渠道，点「检测更新」重新比对")


class DevTab(SettingsTab):
    """开发：开发者模式 + 开发者选项（样本采集那几样）。

    ⚠ 「模拟检测到新版本」这个开关（`sim_update`）**设置页还要用** ——
      切走「开发」标签页时要把它自动关掉（见 `PageSettings._on_tab`），
      所以它必须是个能从外面拿到的属性（`_tab_attr("开发", "sim_update")`）。
    """

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win

        self.dev_enabled = Switch(self, bool(self.cfg.get("developer_mode", False)))
        self.dev_enabled.toggled.connect(self._on_developer_mode)
        self.row("wrench", "开发者模式",
                 "开启后显示下方维护工具", self.dev_enabled,
                 tip="打开后才会显示下面的「开发者选项」（样本采集等维护工具）。\n"
                     "普通使用不需要开启；关闭后已采集的样本文件不会被删除。")

        # ---- 识别日志（一次运行一个文件，放在 data/识别日志/）----
        # ⚠ 这几行**不放进「开发者选项」里** —— 它们是给普通用户反馈问题用的，
        #   藏进开发者模式就等于没有。
        log_open = small_button("打开文件夹", self._open_log_dir, self.alpha,
                                icon="folder-open", width=104)
        log_clear = small_button("清空", self._on_clear_logs, self.alpha,
                                 kind="danger", icon="trash", width=76)
        self.log_row = self.row(
            "file-text", "识别日志",
            "每次启动生成一个日志文件；目录超过 20 MB 自动清理最早文件",
            right_wrap(log_open, log_clear),
            tip="识别日志记的是**每一次判断**：认出了什么、原始文字是什么、"
                "这一笔有没有入账。查「为什么没统计到 / 为什么统计多了」全靠它。\n"
                "· 每次启动软件生成一个新文件（文件名就是启动时刻）；\n"
                "· 整个文件夹超过 20 MB 会从最老的开始自动清理；\n"
                "· 「清空」会删掉全部日志（正在识别也不受影响，下次写入会重建）。\n"
                "日志只写在本机，不会上传。")

        # ---- 一键收集问题信息 ----
        diag_btn = small_button("打包诊断信息", self._make_diagnose, self.alpha,
                                icon="activity", width=140)
        self.row("activity", "出了问题怎么办",
                 "打包版本、设置、报错日志与识别日志，用于问题反馈",
                 diag_btn,
                 tip="点一下会生成一个 zip，里面是：\n"
                     "· 环境概况（版本 / 系统 / 屏幕缩放 / 关键设置 / 数据文件大小）；\n"
                     "· 当前设置；\n"
                     "· 报错日志和最近一次识别日志的**末尾 400 行**。\n"
                     "默认存到桌面，把它发给作者就能定位问题。\n"
                     "包里的路径是本机路径，介意的话可以自己删掉几条再发。")

        # ---- 设置备份（导出 / 导入）----
        exp_btn = small_button("导出…", self._export_settings, self.alpha,
                               icon="file-text", width=92)
        imp_btn = small_button("导入…", self._import_settings, self.alpha,
                               icon="folder-open", width=92)
        self.row("database", "设置备份",
                 "导出设置、识别名单与悬浮窗配置，用于迁移或重装后恢复",
                 right_wrap(exp_btn, imp_btn),
                 tip="**导出**：把设置 / 识别名单 / 悬浮窗配置（含预设）/ 收藏夹"
                     "打包成一个 zip，换电脑、重装、给朋友一份配置都用它。\n"
                     "**导入**：从这样的 zip 恢复。导入前会先把现在这份**原样备份**"
                     "到 data/导入前备份_<时间>/，导错了还能自己拷回来。\n"
                     "⚠ 导入后建议重启软件，让全部设置生效。")

        # ---- 精确模式（外部数据源模块）----
        # ⚠ 主程序**不注入、不读游戏内存**：模块是用户自己另外下载的独立进程，
        #   风险由使用者自担（设计见 `_morph\外部数据源模块_设计.md`）。
        #   默认关；不装模块的话这一行只表示"有这么个东西"。
        precise_btn = small_button("管理…", self._open_precise, self.alpha,
                                   icon="plug", width=92)
        self.precise_row = self.row(
            "plug", "精确模式（需另装模块）",
            self._precise_desc(),
            precise_btn,
            tip="另装一个**独立模块**后，可以直接读取游戏内的掉落事件：\n"
                "· 数据精确到每一笔（材料 / 狗粮 / 摩拉），不再依赖截图识别；\n"
                "· 模块在线时识别会**自动暂停**（省 CPU），掉线 30 秒自动恢复。\n\n"
                "⚠ 该模块会读取游戏进程，属于第三方软件行为、违反游戏用户协议，"
                "**存在账号被封禁的可能，风险由使用者自行承担**。\n"
                "本程序自己不注入、不读内存；不装模块一切照旧（识别模式，零风险）。\n"
                "模块可以在本程序里直接下载安装，也可以随时卸载。")

        # ---- 开发者选项：折叠卡片，每一项一张子卡片 ----
        self.dev_acc = Accordion(self, "flask-conical", "开发者选项",
                                 "采集识别样本用于优化识别准确度；仅保存在本机，不上传、不入账",
                                 items=self._make_dev_items(), alpha=self.alpha,
                                 tip="这里的工具用于收集识别样本、排查识别问题，"
                                     "面向开发者与问题定位。\n"
                                     "所有截图**只保存在本机**，不会上传到任何服务器，"
                                     "也不参与收益统计。")
        self.add_card(self.dev_acc)
        self.dev_acc.setVisible(bool(self.cfg.get("developer_mode", False)))
        self._refresh_log_desc()

    # ------------------------------------------------------------ 精确模式
    def _precise_desc(self):
        """「精确模式」那一行的说明 —— 把**当前状态**写进去，不用点开就知道。

        ⚠ 每次读状态都要碰文件（心跳 / 安装记录），所以只在建行和关弹窗时调，
          不做定时刷新（设置页没必要每秒读盘）。
        """
        try:
            import svc_module
            st = svc_module.status()
            if st.get("state") == "online":
                return f"模块正在供数（{st.get('mod') or '模块'}）—— 识别已暂停"
            if svc_module.module_running():
                return "模块进程在跑，等待心跳…"
            if svc_module.installed():
                return "已安装模块，未运行 —— 当前是识别模式"
            return "未安装 —— 当前是识别模式（截图识别，零风险）"
        except Exception:
            return "未安装 —— 当前是识别模式（截图识别，零风险）"

    def _open_precise(self):
        """打开精确模式弹窗（风险告知 + 下载 / 启动 / 卸载）"""
        try:
            from qt_dlg_precise import PreciseModeDialog
            dlg = PreciseModeDialog(self._win, self.alpha,
                                    settings=self._win.state.settings)
            dlg.exec()
        except Exception:
            try:
                import errlog
                errlog.log_exc("精确模式弹窗")
            except Exception:
                pass
        try:
            self.precise_row.set_text(desc=self._precise_desc())
        except Exception:
            pass

        # 折叠卡片里的「保存目录」和「已采集样本」两行要动态更新，
        # 建完之后按标题把卡片找出来存好
        for c in self.dev_acc.item_cards:
            t = c.title_label.text()
            if t == "样本保存目录":
                self.dev_path_card = c
            elif t == "已采集样本":
                self.dev_stats_card = c
        self._set_dev_path(self.cfg.get("dataset_path", ""))
        self._refresh_dev_stats()

    # ---------- 开发者选项 ----------
    def _make_dev_items(self):
        """开发者选项的每一项（Accordion 会给每项包一张子卡片）"""
        DEFAULT_PATH = svc_capture.dataset_default_path()

        items = []

        # 1) 启用样本采集
        # 注意：DatasetCollector 读的键是 dataset_enabled，
        # 不是 dataset_collect —— 键名写错了这个开关就是空的。
        self.dev_switch = Switch(self,
                                 bool(self.cfg.get("dataset_enabled", False)))
        self.dev_switch.toggled.connect(
            lambda v: self.cfg.set("dataset_enabled", bool(v)))
        items.append(("flask-conical", "启用样本采集",
                      "开启后每次确认拾取都会存一张截图", self.dev_switch, None,
                      "确认拾取时，把当时的画面连同识别到的名字一起存成样本，"
                      "供后续改进识别用。\n"
                      "开启后会持续写入磁盘（受下方目录与容量限制），"
                      "平时建议关闭。"))

        # 2) 保存目录（长路径放说明里，太长会省略，完整路径在鼠标提示里）
        browse = small_button("浏览…", self._on_choose_dataset_path, self.alpha,
                              icon="folder-open", width=84)
        items.append(("folder-open", "样本保存目录",
                      "截图只存在这个文件夹里，不会上传", browse, None,
                      "样本截图的存放位置，默认放在用户数据目录下。\n"
                      "可以改到空间更大的磁盘。改动只影响之后新采集的样本，"
                      "已存在的文件不会被搬动。"))

        # 3) 已采集样本（统计数字写在说明里）
        self.dev_stats_label = QLabel("")     # 留着兼容，实际显示在子卡片的说明里
        self.dev_stats_label.hide()
        open_btn = small_button("打开", self._on_open_dataset, self.alpha,
                                icon="image", width=76)
        items.append(("database", "已采集样本", "", open_btn, None,
                      "已采集的数量与占用空间，超出上限时程序会自动清理最早的样本。\n"
                      "点「打开」在文件管理器里查看这些截图。"))

        # 4) 清空样本
        clear_btn = small_button("清空", self._on_clear_dataset, self.alpha,
                                 kind="danger", icon="trash", width=76)
        items.append(("trash", "清空样本",
                      "删掉全部已采集的截图，不影响收益数据", clear_btn, None,
                      "删除样本目录下**全部**已采集的截图。\n"
                      "只影响样本文件，**收益记录与统计不受影响**，且不可恢复。"))

        # 5) 预览「检测到新版本」的效果
        self.sim_update = Switch(self, False)
        self.sim_update.toggled.connect(self._on_sim_update)
        items.append(("eye", "模拟检测到新版本",
                      "预览左下角闪烁与设置红点的提示效果", self.sim_update, None,
                      "纯预览开关：打开后立刻模拟「检测到新版本」的提示效果，"
                      "用于确认提示是否明显。\n"
                      "离开「开发」标签页时会自动关闭，不会真的联网或更新。"))

        # ⚠ 这里原来有一组「弹窗预览」（标题/数字/材料/弹出来看看），
        #   2026-09-29 用户看过之后说**删掉** —— 不需要，别再加回来。
        #
        # ⚠ 也别在这里加「压测：生成假收益记录」这类按钮 ——
        #   用户明确说了不要这种功能，他只是想知道记录多了卡不卡。
        #   想量性能请用 `_morph\test_records_stress.py`（在临时目录里灌数据）。
        return items

    # ---------- 识别日志 / 诊断 / 设置备份 ----------

    def _refresh_log_desc(self):
        """把「本次多少行 / 一共几个文件多大」写到那一行的说明里"""
        try:
            import svc_diag
            st = svc_diag.log_stats()
            self.log_row.desc_label.setText(
                f"本次 {st['lines']} 行　·　共 {st['files']} 个文件 / "
                f"{svc_diag.human_size(st['bytes'])}　·　超过 20 MB 自动删最早的")
        except Exception:
            pass

    def _open_log_dir(self):
        try:
            self._win.open_log_dir()
        except Exception:
            pass

    def _on_clear_logs(self):
        import svc_diag
        try:
            st = svc_diag.log_stats()
        except Exception:
            st = {}
        if QMessageBox.question(
                self, "确认",
                f"清空识别日志？\n\n"
                f"会删掉 {st.get('files', 0)} 个日志文件"
                f"（{svc_diag.human_size(st.get('bytes', 0))}），包括本次的。\n"
                "正在识别不受影响，下次写入会自动重建。\n\n这个操作不能撤销。"
        ) != QMessageBox.Yes:
            return
        n, freed = svc_diag.clear_logs()
        self._refresh_log_desc()
        msg_info(self, "已清空",
                 f"删掉了 {n} 个日志文件，腾出 {svc_diag.human_size(freed)}。")

    def _make_diagnose(self):
        import svc_diag
        p = svc_diag.collect_diagnose()
        if p is None:
            msg_info(self, "打包失败", "诊断信息打包失败了，可以到 data 文件夹里手动找日志。")
            return
        msg_info(self, "打包好了",
                 f"诊断信息已保存到：\n{p}\n\n"
                 "把它发给作者就能定位问题（里面是本机路径和最近的日志）。")

    def _export_settings(self):
        import svc_diag
        from PySide6.QtWidgets import QFileDialog
        default = f"StatGI设置备份_{time.strftime('%Y%m%d')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "导出设置备份", default,
                                              "压缩包 (*.zip)")
        if not path:
            return
        p = svc_diag.export_settings(path)
        if p is None:
            msg_info(self, "导出失败", "导出失败了，换个位置再试试。")
            return
        msg_info(self, "导出好了",
                 f"设置备份已保存到：\n{p}\n\n"
                 "里面有设置、识别名单、悬浮窗配置和收藏夹。")

    def _import_settings(self):
        import svc_diag
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "导入设置备份", "",
                                              "压缩包 (*.zip)")
        if not path:
            return
        if QMessageBox.question(
                self, "确认导入",
                "导入会**覆盖**当前的设置、识别名单和悬浮窗配置。\n\n"
                "导入前会自动把现在这份备份到 data/导入前备份_xxx/，\n"
                "确定继续吗？"
        ) != QMessageBox.Yes:
            return
        try:
            done, backup = svc_diag.import_settings(path)
        except Exception as e:
            msg_info(self, "导入失败", f"这个文件读不了：{e}")
            return
        # 名单能立刻生效，其它设置（外观/缩放）建议重启
        try:
            svc_capture.reload_names()
        except Exception:
            pass
        self._refresh_log_desc()
        msg_info(self, "导入完成",
                 f"已导入：{'、'.join(done)}\n\n"
                 f"导入前的旧文件备份在：\n{backup}\n\n"
                 "建议重启软件，让全部设置生效。")

    def _set_dev_path(self, path):
        """把样本目录显示到子卡片的说明上（太长就省略，完整路径放提示气泡）"""
        full = str(path or "") or str(svc_capture.dataset_default_path())
        card = getattr(self, "dev_path_card", None)
        if card is not None:
            short = full if len(full) <= 32 else full[:15] + "…" + full[-14:]
            card.desc_label.setText(short)
            card.desc_label.setToolTip(full)
            card.setToolTip(full)

    def _on_sim_update(self, v):
        """开发者选项：把「检测到新版本」的提示效果开/关（纯粹为了看效果）"""
        self._win.set_update_available(bool(v), "9.9")

    def _on_developer_mode(self, v):
        self.cfg.set("developer_mode", bool(v))
        acc = getattr(self, "dev_acc", None)
        if acc is not None:
            acc.setVisible(bool(v))
        if v:
            self._refresh_dev_stats()

    def _refresh_dev_stats(self):
        try:
            st = svc_capture.dataset_stats(self.cfg.raw)
            txt = (f"共 {st.get('total', 0)} 张"
                   f"（正面 {st.get('gameplay', 0)} / 反面 {st.get('non_gameplay', 0)}）"
                   f"　占用 {st.get('size_mb', 0)} / {st.get('max_mb', 100)} MB")
        except Exception:
            txt = "（无法读取样本统计）"
        self.dev_stats_label.setText(txt)
        card = getattr(self, "dev_stats_card", None)
        if card is not None:
            card.desc_label.setText(txt)

    def _on_choose_dataset_path(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择样本保存位置")
        if not d:
            return
        self.cfg.set("dataset_path", d)
        self._set_dev_path(d)

    def _on_open_dataset(self):
        import os
        d = (self.cfg.get("dataset_path", "")
             or str(svc_capture.dataset_default_path()))
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)               # noqa  Windows 专用
        except Exception as e:
            QMessageBox.warning(self, "失败", f"打不开文件夹：{e}")

    def _on_clear_dataset(self):
        if QMessageBox.question(self, "确认", "确定清空所有采集的样本吗？\n（不可恢复）"
                                ) != QMessageBox.Yes:
            return
        try:
            svc_capture.dataset_clear(self.cfg.raw)
            self._refresh_dev_stats()
            QMessageBox.information(self, "已清空", "样本已清空。")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"清空失败：{e}")


class AppearanceTab(SettingsTab):
    """外观：卡片透明度 / 背景压暗 / 背景图 / 背景色 / 强调色 / 毛玻璃 / 统计条图标。

    ⚠ 这是唯一一个**要拿主窗口**的标签页（`win` 参数）。它要做的事
      （换背景图、压暗、毛玻璃、重建界面、遍历所有 Card 改透明度）全是
      窗口级操作，一个个包成回调反而看不清谁是谁。
      注意拿的是**主窗口**，不是 `AppState` —— 那个上面挂着 `toggle()`，
      **会启动识别**，设置页不该碰（第 8 批刚摘掉的东西，别在这儿请回来）。
    """

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win
        # 颜色下拉框的两道闸（原来住在 PageSettings 上）：
        #   `_color_busy`   —— 静默设置下拉框期间，别真的去应用颜色
        #   `_colors_ready` —— 界面还没建完时不要应用（应用会重建界面）
        self._color_busy = False
        self._colors_ready = False

        op = int(float(self.cfg.get("panel_opacity", 0.5) or 0.5) * 100)
        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setRange(0, 100)
        self.alpha_slider.setValue(op)
        self.alpha_slider.setFixedWidth(180)
        self.alpha_slider.setStyleSheet(slider_qss())
        self.alpha_label = QLabel(f"{op}%")
        self.alpha_label.setFixedWidth(46)
        self.alpha_label.setStyleSheet(label_qss(T.ACCENT, 13))
        self.alpha_slider.valueChanged.connect(self._on_alpha)
        self.row("contrast", "卡片透明度",
                 "卡片、侧边栏与按钮的统一不透明度；0% 为全透明",
                 right_wrap(self.alpha_slider, self.alpha_label),
                 tip="统一控制卡片、侧边栏、按钮的不透明度。\n"
                     "设成 0% 时几乎全透明（只剩文字），适合把窗口叠在游戏上；\n"
                     "设得高一些更清晰，但会挡住更多画面。\n"
                     "只改外观，不影响识别与统计。")

        dim = int(float(self.cfg.get("bg_dim", 0.0) or 0.0) * 100)
        self.dim_slider = QSlider(Qt.Horizontal)
        self.dim_slider.setRange(0, 60)
        self.dim_slider.setValue(dim)
        self.dim_slider.setFixedWidth(180)
        self.dim_slider.setStyleSheet(slider_qss())
        self.dim_label = QLabel(f"{dim}%")
        self.dim_label.setFixedWidth(46)
        self.dim_label.setStyleSheet(label_qss(T.ACCENT, 13))
        self.dim_slider.valueChanged.connect(self._on_dim)
        self.row("moon", "背景压暗",
                 "背景图压暗强度；对比度过高时可调高以提升可读性，0% 不压暗",
                 right_wrap(self.dim_slider, self.dim_label),
                 tip="给背景图盖一层暗色，让上面的文字更清楚。\n"
                     "风景、亮色照片类背景图通常需要 20%~40%；"
                     "纯色背景不需要调。\n"
                     "上限 60%，不会把背景压成纯黑。")

        pic = set_btn_icon(QPushButton("选择图片"), "image", 15)
        clr = set_btn_icon(QPushButton("清除"), "x", 15)
        for b, kind, cb in ((pic, "normal", self._choose_bg), (clr, "danger", self._clear_bg)):
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
        cur = self.cfg.get("bg_image") or ""
        self.bg_name = QLabel("")
        self.bg_name.setStyleSheet(label_qss(T.DIM, 12))
        # 长文件名会把整张卡片撑宽 —— 限宽 + 中间省略，完整名字放提示气泡里
        self.bg_name.setMaximumWidth(150)
        self._set_bg_name(cur)
        self.row("image", "自定义背景图片",
                 "设为窗口背景图；卡片区域自动转为半透明",
                 right_wrap(pic, clr, self.bg_name),
                 tip="选一张本地图片当窗口背景。设置后卡片区域转为半透明，"
                     "整体更贴近游戏画面。\n"
                     "建议用与游戏色调相近、对比不高的图；"
                     "太花会让文字难认（配合上面的「背景压暗」使用）。\n"
                     "图片只从本机读取，不会上传；点「清除」恢复纯色背景。")

        import theme as _theme_mod      # 只为了取预设名字列表
        bg_items = list(getattr(_theme_mod, "BG_PRESETS", {"经典深黑": "#1C1C1C"}).keys())
        ac_items = list(getattr(_theme_mod, "ACCENT_PRESETS", {"经典蓝": "#4CC2FF"}).keys())
        self.bg_dd = self._dd(bg_items + [CUSTOM_COLOR])
        self.accent_dd = self._dd(ac_items + [CUSTOM_COLOR])
        self._set_combo_silently(self.bg_dd, self.cfg.get("bg_color", "经典深黑"))
        self._set_combo_silently(self.accent_dd, self.cfg.get("accent_color", "经典蓝"))
        self.bg_dd.currentTextChanged.connect(self._on_bg_color)
        self.accent_dd.currentTextChanged.connect(self._on_accent_color)
        self.row("palette", "背景颜色",
                 "窗口背景色；可选预设或自定义", self.bg_dd,
                 tip="整个窗口的底色。选预设名即可；"
                     "选「自定义颜色…」会打开取色器。\n"
                     "改完立即生效（界面会重建一次，属于正常现象）。")
        self.row("rainbow", "强调色",
                 "按钮、选中项与数值高亮色；可选预设或自定义", self.accent_dd,
                 tip="按钮、开关、选中项、数值高亮用的主色调。\n"
                     "与背景色搭配使用：深色背景配亮一点的强调色更清楚。\n"
                     "同样支持「自定义颜色…」，改完立即生效。")

        self.sidebar_glass = Switch(self, bool(self.cfg.get("sidebar_glass", True)))
        self.sidebar_glass.toggled.connect(self._on_sidebar_glass)
        self.row("eye-off", "左侧栏毛玻璃效果",
                 "对侧边栏做模糊与压暗处理；需先设置背景图", self.sidebar_glass,
                 tip="对左侧栏做模糊 + 压暗，做出磨砂玻璃质感（需要先设置背景图）。\n"
                     "关掉则左侧栏用纯色。\n"
                     "模糊有轻微性能开销，低配机器可以关掉。")

        # 「统计条图标」放在这里（从「直播」挪过来的）
        icon_btn = QPushButton("打开图标管理")
        icon_btn.setFixedHeight(34)
        icon_btn.setCursor(Qt.PointingHandCursor)
        icon_btn.setStyleSheet(btn_qss("normal", self.alpha))
        icon_btn.clicked.connect(self._win.open_icon_manager)
        self.row("image", "统计条图标",
                 "统计条各格图标（摩拉 / 材料 / 狗粮）", icon_btn,
                 tip="打开图标管理器，给桌面统计条每一格挑图标，"
                     "也可以用自己的图片替换。\n"
                     "改动只影响显示，不影响统计结果。")

        # ---- 界面缩放（改完要重启）----
        self.scale_dd = self._dd(["100%（默认）", "110%", "125%"], width=140)
        _sc = float(self.cfg.get("ui_scale", 1.0) or 1.0)
        self.scale_dd.setCurrentText(
            {1.0: "100%（默认）", 1.1: "110%", 1.25: "125%"}.get(
                round(_sc, 2), "100%（默认）"))
        self.scale_dd.currentTextChanged.connect(self._on_ui_scale)
        self.row("monitor", "界面缩放",
                 "整体缩放界面；高分屏字体过小时使用，重启后生效", self.scale_dd,
                 tip="把整个界面（文字、按钮、间距）一起放大，"
                     "适合 2K / 4K 笔记本上觉得字太小的情况。\n"
                     "· 100%（默认）—— 原始大小；\n"
                     "· 110% / 125% —— 逐级放大。\n"
                     "⚠ **改完要重启软件才生效**（Qt 只在启动那一刻读这个值）。\n"
                     "放大后同屏显示的内容会变少，也建议先从 110% 试。")

        # ---- 停止监测时的小结 ----
        self.stop_sum = Switch(self, bool(self.cfg.get("stop_summary", True)))
        self.stop_sum.toggled.connect(
            lambda v: self.cfg.set("stop_summary", bool(v)))
        self.row("chart-bar", "停止监测时显示小结",
                 "停止监测后弹窗汇总本次时长与收益", self.stop_sum,
                 tip="点「停止监测」后弹一个小窗，汇总**本次**这一段：\n"
                     "时长、摩拉、材料（总数 + 前几名）、狗粮。\n"
                     "数据是这次开始到停止之间的增量，跟当日累计无关。\n"
                     "觉得每次弹窗烦可以关掉。")

        # 界面建完了，之后的下拉框变化才真的去应用颜色
        self._colors_ready = True

    def _on_ui_scale(self, text):
        """界面缩放：写设置 + 提示要重启。

        ⚠ 这个值 Qt **只在启动那一刻读**（main.py 里设 QT_SCALE_FACTOR），
          所以这里只能存下来、提示重启，没法立刻生效。
        """
        v = {"100%（默认）": 1.0, "110%": 1.1, "125%": 1.25}.get(text, 1.0)
        old = float(self.cfg.get("ui_scale", 1.0) or 1.0)
        self.cfg.set("ui_scale", v)
        if abs(v - old) > 0.001:
            msg_info(self, "重启后生效",
                     f"界面缩放已设为 {text}。\n\n"
                     "这个设置需要**重启软件**才会生效。")

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_alpha(self, v):
        self.alpha_label.setText(f"{v}%")
        self.cfg.set("panel_opacity", v / 100.0)
        a = int(v / 100 * 255)
        for c in self._win.findChildren(Card):      # 只改背景色，不重建控件
            c.set_alpha(a)

    def _on_dim(self, v):
        self.dim_label.setText(f"{v}%")
        self.cfg.set("bg_dim", v / 100.0)
        self._win.apply_bg_dim()

    def _set_bg_name(self, path):
        """显示背景图文件名。

        这个标签在卡片的右边，**文件名太长会把整张卡片撑宽** —— 撑宽之后
        外观栏看着就像被"拉长"了。所以限宽 + 中间省略，
        完整文件名放进鼠标提示里。
        """
        import os as _os
        name = _os.path.basename(path) if path else ""
        if not name:
            self.bg_name.setText("未设置（纯色背景）")
            self.bg_name.setToolTip("")
            return
        short = name if len(name) <= 16 else name[:7] + "…" + name[-6:]
        self.bg_name.setText(short)
        self.bg_name.setToolTip(name)

    def _choose_bg(self):
        from PySide6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not p:
            return
        try:
            from PIL import Image
            Image.open(p).verify()
        except Exception:
            msg_info(self, "失败", "该文件不是有效的图片，请重新选择。",
                     icon=QMessageBox.Warning)
            return
        self.cfg.set("bg_image", p)
        self._set_bg_name(p)
        self._win.set_background_image(p)
        msg_info(self, "成功", "背景图片已应用。")

    def _clear_bg(self):
        self.cfg.set("bg_image", "")
        self._set_bg_name("")
        self._win.set_background_image(None)

    def _on_sidebar_glass(self, v):
        self.cfg.set("sidebar_glass", bool(v))
        self._win.set_sidebar_glass(bool(v))

    # ---------- 背景色 / 强调色：改完立即生效 ----------

    @staticmethod
    def _combo_show_color(combo, value):
        """把设置里存的颜色显示到下拉框上。

        预设存的是名字（"经典深黑"），自定义存的是 "#RRGGBB" —— 后者
        下拉框里本来没有，得先插一项再选上，否则会显示成空白。
        """
        v = str(value or "")
        if v.startswith("#"):
            label = f"自定义 {v}"
            if combo.findText(label) < 0:
                combo.insertItem(max(0, combo.count() - 1), label)
            combo.setCurrentText(label)
        else:
            combo.setCurrentText(v)

    def _set_combo_silently(self, combo, value):
        """改下拉框，但**不触发** currentTextChanged。

        ⚠ 不加这个会出事：setCurrentText 会发信号 → 又走一遍「应用颜色」
          → 把下拉框上显示的**标签文字**当成颜色存进去，还会重复重建界面
          （重建会把控件删掉，紧跟着访问就崩）。
        """
        self._color_busy = True
        try:
            self._combo_show_color(combo, value)
        finally:
            self._color_busy = False

    def _pick_custom_color(self, key, combo):
        """开取色器选一个自定义颜色"""
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog

        cur = str(self.cfg.raw.get(key, "") or "")
        init = QColor(cur) if QColor.isValidColorName(cur) else QColor(T.ACCENT)
        col = QColorDialog.getColor(init, self._win, "选择颜色")
        if not col.isValid():
            # 取消了 → 下拉框回到当前实际值，别停在「自定义颜色…」上
            self._set_combo_silently(combo, self.cfg.raw.get(key, ""))
            return
        hexv = col.name()
        self._set_combo_silently(combo, hexv)
        self._apply_colors(key, hexv, display=f"自定义 {hexv}")

    def _apply_colors(self, key, value, display=None):
        self.cfg.set(key, value)
        T.reload_colors(self.cfg.raw)
        # ⚠ 先把主窗口记下来：rebuild_ui() 会把旧页面从窗口上摘掉，
        #   之后就找不到主窗口了，弹窗会跑到屏幕角落去。
        win = self._win
        win.rebuild_ui()
        msg_info(win, "已应用", f"颜色已切换为「{display or value}」。")

    def _on_bg_color(self, v):
        if getattr(self, "_color_busy", False):
            return
        if v == CUSTOM_COLOR:
            self._pick_custom_color("bg_color", self.bg_dd)
            return
        if getattr(self, "_colors_ready", False):
            self._apply_colors("bg_color", v)

    def _on_accent_color(self, v):
        if getattr(self, "_color_busy", False):
            return
        if v == CUSTOM_COLOR:
            self._pick_custom_color("accent_color", self.accent_dd)
            return
        if getattr(self, "_colors_ready", False):
            self._apply_colors("accent_color", v)


GROUP_REFRESH_MARK = "\u21bb \u5237\u65b0\u7ec4\u540d\u5217\u8868"


class GroupCombo(QComboBox):
    """配置组用的下拉框（可编辑）。

    为什么要这个子类：老代码和测试都用的是 `.text()` / `.setText()`（原来是
    QLineEdit）。这里给下拉补上同样名字的方法，两边就都不用改了。
    「↻ 刷新组名列表」这一项不算组名，`text()` 里会被过滤掉。
    """

    def text(self):
        t = self.currentText()
        return "" if t == GROUP_REFRESH_MARK else t

    def setText(self, value):
        self.setCurrentText(str(value or ""))


class SettingsTab(QWidget):
    """设置页里一个标签页的基类。

    ⚠ 这个类**故意只拿三样**：parent / cfg / alpha。
      不拿 `AppState`、不拿主窗口 —— 第 8 批刚把 `PageSettings` 从 `AppState`
      上摘下来（那个对象上挂着 `toggle()`，**会启动识别**），别在这儿又请回来。
      确实需要主窗口帮忙的标签页，走**显式回调**（见 `LiveTab`）。
    """

    def __init__(self, parent, cfg, alpha):
        super().__init__(parent)
        self.cfg = cfg
        self.alpha = alpha
        # 热键录制时要抢焦点的那个控件（只有「行为」标签页用）。
        # 默认是自己；设置页建完之后会把它改成**设置页**本身 ——
        # 因为 `keyPressEvent` 是装在页面上的（页面才是那个能收键盘的控件）。
        self.focus_host = self
        # ⚠ 跟原来 PageSettings 里那个 inner 控件一模一样：
        #   透明底 + 右边留 10px（给滚动条）+ 行距 10 + 末尾弹簧
        self.setStyleSheet("background: transparent;")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 10, 0)
        self.v.setSpacing(10)
        self.v.addStretch(1)

    def row(self, icon, title, desc, right=None, height=70, tip=""):
        """加一行设置（跟原来 `PageSettings._row` 的行为完全一样）。

        `tip` 是鼠标悬停时显示的**详细说明**（比 desc 长、讲原理和注意事项）。
        """
        r = SettingRow(self, icon, title, desc, right, alpha=self.alpha,
                       height=height, tip=tip)
        self.v.insertWidget(self.v.count() - 1, r)
        return r

    def _dd(self, items, width=150):
        """通用下拉框（跟原来 `PageSettings._dd` 是同一个实现）"""
        return make_combo(items, width)

    def add_card(self, w):
        """往末尾（弹簧之前）插一张卡片。

        跟原来 `self._lay[tb].insertWidget(self._lay[tb].count() - 1, w)`
        完全等价 —— 折叠区那种"整张卡片"的行用这个。
        """
        self.v.insertWidget(self.v.count() - 1, w)
        return w


class LiveTab(SettingsTab):
    """直播：数据接口总开关 + 收益条地址 + 接口端口。"""

    def __init__(self, parent, cfg, alpha, apply_api=None):
        # ⚠ 只拿一个回调，不拿整个主窗口：这个标签页需要主窗口做的
        #   唯一一件事就是「按新设置把接口起停一下」。
        self._apply_api = apply_api or (lambda: None)
        super().__init__(parent, cfg, alpha)

        # ---- 直播数据接口总开关 ----
        # 这个是**真的开关**：关掉就把接口停掉（OBS 那个浏览器源会没数据），
        # 打开就重新起来。以前它只存了个值、什么都不干。
        self.obs_sw = Switch(self, bool(self.cfg.get("obs_api_enabled", True)))
        self.obs_sw.toggled.connect(self._on_obs)
        self.row("radio", "直播数据接口",
                 "为 OBS 浏览器源提供实时数据接口；关闭后直播端无数据",
                 self.obs_sw,
                 tip="在本机开启一个只读的数据接口，OBS 的浏览器源、直播计时条"
                     "都从这里取数。\n"
                     "关闭后接口进程立即停止，直播端会显示为无数据；"
                     "不需要直播时建议关掉，少占一个本地端口。")

        # ---- 收益条地址 ----
        # 注意给的是 /bar（**只有收益条**：摩拉/材料/狗粮/监测时间）。
        # /overlay 那个是整块竖屏覆盖层，上面一半是弹幕区，不是纯收益条。
        api_port = int(self.cfg.get("api_port", 8765) or 8765)
        self.obs_addr = QLabel(self._bar_url(api_port))
        self.obs_addr.setStyleSheet(label_qss(T.TEXT, 13))
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(60, 28)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(btn_qss("normal", self.alpha))
        copy_btn.clicked.connect(self._copy_obs)
        self.row("monitor", "收益条地址",
                 "OBS 浏览器源地址，建议尺寸 340×200",
                 right_wrap(self.obs_addr, copy_btn),
                 tip="这是**只有收益条**的地址（摩拉 / 材料 / 狗粮 / 监测时间）。\n"
                     "在 OBS 里添加「浏览器源」，粘贴此地址，建议尺寸 340×200。\n"
                     "地址里的端口跟下面「接口端口」一致，改端口后要重新复制。")

        # ---- 端口 ----
        self.api_entry = QLineEdit(str(api_port))
        self.api_entry.setFixedWidth(90)
        self.api_entry.setAlignment(Qt.AlignCenter)
        self.api_entry.setStyleSheet(entry_qss())
        self.api_entry.editingFinished.connect(self._on_api_port)
        self.row("plug", "接口端口",
                 "接口监听端口；修改即时生效，OBS 端需同步更新", self.api_entry,
                 tip="数据接口监听的本地端口，范围 1024~65535，默认 8765。\n"
                     "改完立即重启接口；若有别的程序占用该端口，接口会起不来，"
                     "换一个端口即可。\n"
                     "改完记得把「收益条地址」重新复制到 OBS。")

    @staticmethod
    def _bar_url(port):
        return f"http://127.0.0.1:{int(port)}/bar"

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_api_port(self):
        try:
            v = max(1024, min(65535, int(self.api_entry.text().strip())))
        except Exception:
            v = 8765
        self.api_entry.setText(str(v))
        self.cfg.set("api_port", v)
        # 地址显示跟着改，并且**立刻**把接口换到新端口（以前要重启）
        try:
            self.obs_addr.setText(self._bar_url(v))
        except Exception:
            pass
        try:
            self._apply_api()
        except Exception:
            pass

    def _on_obs(self, v):
        """直播数据接口总开关：立刻开 / 关接口"""
        self.cfg.set("obs_api_enabled", bool(v))
        try:
            self._apply_api()
        except Exception:
            pass

    def _copy_obs(self):
        from PySide6.QtWidgets import QApplication as _A
        _A.clipboard().setText(self.obs_addr.text())
        QMessageBox.information(self, "已复制",
                                f"OBS 浏览器源地址已复制：\n{self.obs_addr.text()}")


class RecognizeTab(SettingsTab):
    """识别：检测间隔 / 文字识别频率 / 画面变化灵敏度 / 防重复窗口 / 识别哪几样。"""

    def __init__(self, parent, cfg, alpha):
        super().__init__(parent, cfg, alpha)

        # 兜底值跟 config_manager.DEFAULT_SETTINGS["tick_interval"] 一致（100）。
        # ⚠ 改了默认值记得同步改这里，否则"设置项缺失"时两个地方对不上。
        self.tick_entry = QLineEdit(str(self.cfg.get("tick_interval", 100)))
        self.tick_entry.setFixedWidth(90)
        self.tick_entry.setAlignment(Qt.AlignCenter)
        self.tick_entry.setStyleSheet(entry_qss())
        self.tick_entry.editingFinished.connect(self._on_tick)
        self.row("timer", "检测间隔",
                 "画面采样间隔（毫秒）；取值 10~5000，默认 100", self.tick_entry,
                 tip="程序多久看一次屏幕（毫秒）。它只做**便宜的**画面差异比较，"
                     "真正耗时的文字识别另有节流，所以调小不一定更吃 CPU。\n"
                     "越小＝越能及时察觉掉落提示出现；\n"
                     "越大＝越省电，但快速连续的拾取可能被合并观察。\n"
                     "建议 50（默认），笔记本省电可 80~120。")

        # 文字识别频率：性能 / 标准 / 省电 / 极致省电（越小越频繁）
        self.ocr_dd = self._dd([name for name, _v in config_manager.OCR_LEVELS])
        self.ocr_dd.setCurrentText(
            level_name(config_manager.OCR_LEVELS,
                       int(self.cfg.get("ocr_interval", 150) or 150), config_manager.DEFAULT_OCR_LEVEL))
        self.ocr_dd.currentTextChanged.connect(self._on_ocr_interval)
        self.row("search", "文字识别频率",
                 "文字识别间隔（毫秒）；数值越小响应越快、占用越高", self.ocr_dd,
                 tip="OCR 的节流档位（性能 100 / 标准 150 / 省电 250 / 极致省电 500 毫秒）。\n"
                     "文字识别本身较慢（一次约 0.6 秒），这是**主要**的性能开销来源。\n"
                     "档位越高越省电，但收获提示淡出得快时可能来不及读全。\n"
                     "建议保持「标准」；挂机发热明显再降档。")

        # 画面变化灵敏度：同一套名字，数值是变化阈值（越小越灵敏）
        #
        # 注意：识别核心读的是 change_threshold，不是 change_level。
        # Tk 版在这儿有个 bug：下拉框按 change_level 显示、保存却只写
        # change_threshold，于是 change_level 永远是老值，**看到的值跟
        # 实际用的值对不上**。这里按 change_threshold 反推显示，并且两个都写。
        self.change_dd = self._dd([name for name, _v in config_manager.CHANGE_LEVELS])
        try:
            _cur_thr = float(self.cfg.get("change_threshold", 2.0))
        except Exception:
            _cur_thr = 2.0
        self.change_dd.setCurrentText(
            level_name(config_manager.CHANGE_LEVELS, _cur_thr,
                       config_manager.DEFAULT_CHANGE_LEVEL))
        self.change_dd.currentTextChanged.connect(self._on_change_level)
        self.row("sliders-horizontal", "画面变化灵敏度",
                 "画面变化判定阈值；越灵敏响应越快、占用越高", self.change_dd,
                 tip="判定「画面变了、该跑一次文字识别」的阈值。\n"
                     "档位：性能 1.0 / 标准 2.0 / 省电 4.0 / 极致省电 8.0（数值越小越灵敏）。\n"
                     "调得太灵敏时，战斗特效、伤害数字跳动都会被当成「画面变了」，"
                     "反而频繁触发识别、更吃 CPU。\n"
                     "掉落识别不灵（漏记）时先往「性能」调一档试试。")

        ev = str(self.cfg.get("event_end_window", 1.5)).replace("秒", "").strip()
        self.event_dd = self._dd(["1.0 秒", "1.5 秒", "2.5 秒"])
        self.event_dd.setCurrentText((f"{ev} 秒" if f"{ev} 秒" in ("1.0 秒", "1.5 秒", "2.5 秒")
                                      else "1.5 秒"))
        self.event_dd.currentTextChanged.connect(self._on_event_window)
        self.row("repeat", "防重复窗口",
                 "同一名称消失超过该时长后再次出现，计为新掉落", self.event_dd,
                 tip="同一条收获提示「消失」超过这个时长后再次出现，才算一次新的掉落，"
                     "用来防止 OCR 漏读、提示淡出被误判成多次拾取。\n"
                     "提示淡出较慢、或跨零点挂机时，可适当调大；\n"
                     "自动拾取很快、连续同名掉落被少记时，可调小到 1.0 秒。")

        # 识别哪几样：折叠区，每一项一张子卡片
        self.kind_switches = {}
        kind_items = []
        for key, ic_name, name, desc, tip in (
                ("enable_mora", "coins", "摩拉", "识别并统计拾取到的摩拉",
                 "统计「获得」栏里的摩拉。\n"
                 "摩拉读数偶尔会与角色伤害数字重叠，造成异常大值 —— "
                 "「统计」标签页里的「摩拉单次计数上限」就是拦这个的。"),
                ("enable_material", "swords", "材料", "识别并统计怪物掉落的素材",
                 "统计怪物掉落与采集到的素材。\n"
                 "只统计**识别名单**里的名字；名单外的名字不会入账，"
                 "只会记进识别日志备查（名单在「统计」标签页里改）。"),
                ("enable_artifact", "gem", "狗粮", "识别并统计拾取的圣遗物",
                 "统计拾取到的圣遗物（俗称狗粮）。\n"
                 "判定依据是圣遗物名表与套装关键词，名单外的名字不会入账。")):
            sw = Switch(self, bool(self.cfg.get(key, True)))
            sw.toggled.connect(lambda v, k=key: self._on_kinds_changed(k, v))
            self.kind_switches[key] = sw
            kind_items.append((ic_name, name, desc, sw, None, tip))
        self.kind_acc = Accordion(self, "target", "识别哪几样",
                                  "选择需要统计的物品种类",
                                  items=kind_items, alpha=self.alpha,
                                  tip="关掉某一类的识别开关后，该类物品即使被认出来也不会入账，"
                                      "可以省下对应的处理开销。\n"
                                      "「材料」和「狗粮」只统计识别名单里的名字，"
                                      "名单在「统计」标签页里维护。")
        self.add_card(self.kind_acc)
        self._sync_kind_desc()

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _sync_kind_desc(self):
        names = [n for k, n in (("enable_mora", "摩拉"), ("enable_material", "材料"),
                                ("enable_artifact", "狗粮"))
                 if self.kind_switches[k].isChecked()]
        self.kind_acc.desc_label.setText(
            f"当前识别：{'、'.join(names) if names else '（都不识别）'}"
            "　·　展开后勾选；不需要统计的取消勾选")

    def _on_kinds_changed(self, key, val):
        self.cfg.set(key, bool(val))
        self._sync_kind_desc()
        self.cfg.apply_live()

    def _on_change_level(self, v):
        """灵敏度：写进识别核心真正读的 change_threshold

        档位：性能 1.0 / 标准 2.0 / 省电 4.0 / 极致省电 8.0（越小越灵敏）
        """
        thr = level_value(config_manager.CHANGE_LEVELS, v, 2.0)
        self.cfg.set("change_threshold", thr)
        self.cfg.set("change_level", v)      # 一起写，避免显示/实际不一致
        self.cfg.apply_live()

    def _on_event_window(self, v):
        try:
            sec = float(str(v).replace("秒", "").strip())
        except Exception:
            return
        self.cfg.set("event_end_window", sec)
        self.cfg.apply_live()

    def _on_ocr_interval(self, v):
        """频率：性能 100 / 标准 150 / 省电 250 / 极致省电 500（毫秒）"""
        ms = level_value(config_manager.OCR_LEVELS, v, 150)
        self.cfg.set("ocr_interval", ms)
        self.cfg.apply_live()

    def _on_tick(self):
        try:
            v = max(10, min(5000, int(self.tick_entry.text().strip())))
        except Exception:
            v = 50
        self.tick_entry.setText(str(v))
        self.cfg.set("tick_interval", v)


class BehaviorTab(SettingsTab):
    """行为：只在原神前台时识别 / 关闭按钮行为 / 全局热键录制。"""

    def __init__(self, parent, cfg, alpha):
        super().__init__(parent, cfg, alpha)

        self.only_fg = Switch(self, bool(self.cfg.get("only_foreground", True)))
        self.only_fg.toggled.connect(
            lambda v: self.cfg.set("only_foreground", bool(v)))
        self.row("crosshair", "只在原神前台时识别",
                 "仅在原神处于前台时识别；切出后自动暂停", self.only_fg,
                 tip="开启后，原神窗口不在前台时直接跳过这一轮：不截图、不识别，"
                     "既省性能，也避免把浏览器/聊天窗口上的文字当成掉落。\n"
                     "关掉它＝任何窗口在前台都照常识别，只在多开或特殊录屏场景下需要。")

        self.close_dd = self._dd(["每次询问", "最小化到托盘", "直接退出"])
        self.close_dd.setCurrentText({
            "ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"
        }.get(str(self.cfg.get("close_behavior", "ask")), "每次询问"))
        self.close_dd.currentTextChanged.connect(self._on_close_behavior)
        self.row("x", "点右上角 ✕ 时", "点击标题栏关闭按钮时的行为", self.close_dd,
                 tip="决定点窗口右上角 ✕ 之后发生什么：\n"
                     "· 每次询问 —— 弹窗让你选，防止误关；\n"
                     "· 最小化到托盘 —— 窗口收起但程序继续运行，监测不中断；\n"
                     "· 直接退出 —— 立即关闭并保存数据。\n"
                     "想让挂机不被打断，选「最小化到托盘」。")

        # ---- 全局热键（收成一张折叠卡片）----
        # 每个动作一个按钮，点按钮后按下想用的键即可录制。
        # _hotkey_btns 记着「设置里的键名 -> 按钮」，录制时按名字找按钮。
        self._hotkey_btns = {}
        self._capturing = None
        hk_items = []
        for key, ic_name, title, desc, tip in (
                ("hotkey", "play", "开始 / 停止监测",
                 "按下即开始监测；再次按下停止",
                 "同一个键负责开始和停止：正在监测时按下就停止。\n"
                 "建议选游戏里不常用的键（如 F9），避免与游戏操作冲突。"),
                ("hotkey_bar", "chart-column", "显示 / 隐藏统计条",
                 "按下显示统计条；再次按下隐藏",
                 "控制桌面统计条的显示与隐藏。\n"
                 "全屏游戏时按一下就能看当次收益，不用切窗口。")):
            btn = small_button(str(self.cfg.get(key, "关闭")), None, self.alpha,
                               width=120, height=30)
            btn.clicked.connect(lambda _=False, k=key: self._start_hotkey_capture(k))
            self._hotkey_btns[key] = btn
            hk_items.append((ic_name, title, desc, btn, None, tip))

        hk_tip = QLabel("点击右侧按钮后按下目标按键即可设置，Esc 取消；不使用则保持「关闭」")
        hk_tip.setStyleSheet(label_qss(T.DIM, 12))
        hk_tip.setWordWrap(True)

        self.hotkey_acc = Accordion(self, "keyboard", "全局热键",
                                    "系统级热键，游戏内同样生效",
                                    items=hk_items, footer=hk_tip,
                                    alpha=self.alpha,
                                    tip="热键在系统范围内生效，游戏全屏时同样可用。\n"
                                        "设置方法：点右侧按钮，再按下目标按键；按 Esc 取消。\n"
                                        "同一个按键不能同时分配给两个动作，"
                                        "按键冲突时会提示更换。")
        self.add_card(self.hotkey_acc)

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_close_behavior(self, text):
        self.cfg.set("close_behavior", {
            "每次询问": "ask", "最小化到托盘": "tray", "直接退出": "exit"}.get(text, "ask"))

    def _start_hotkey_capture(self, which="hotkey"):
        """开始录制热键

        which 指明这次是给哪个动作录：设置里的键名（hotkey / hotkey_bar …）。
        """
        self._capturing = which
        if which not in self._hotkey_btns:
            return
        self._hotkey_btns[which].setText("请按下按键…（Esc 取消）")
        # ⚠ 焦点要给 `focus_host`（设置页），**不是这个标签页** ——
        #   `keyPressEvent` 装在页面身上，焦点给标签页的话按键收不到。
        self.focus_host.setFocus()

    def on_key(self, e):
        """处理一次按键（设置页收到 keyPressEvent 后转发过来）。

        返回 True 表示这次按键被吃掉了。
        """
        which = getattr(self, "_capturing", None)
        if not which:
            return False
        btn = self._hotkey_btns.get(which)
        cur = str(self.cfg.raw.get(which, "关闭"))
        self._capturing = None
        if btn is None:
            return True
        k = e.key()
        if k == Qt.Key_Escape:
            btn.setText(cur)
            return True
        name = _qt_key_name(e)
        if name is None:
            btn.setText(cur)
            return True
        # 同一个键不能同时给两个动作用 —— 不然按一下触发两个
        for other, obtn in self._hotkey_btns.items():
            if other != which and str(self.cfg.raw.get(other, "关闭")) == name:
                QMessageBox.information(
                    self, "这个键已经用过了",
                    f"「{name}」已分配给其他动作，请更换按键。")
                btn.setText(cur)
                return True
        self.cfg.set(which, name)
        btn.setText(name)
        return True


def _qt_key_name(e):
    """Qt 的按键 -> 设置里存的名字（跟 Tk 版用同一套字符串格式）"""
    from PySide6.QtCore import Qt as _Qt
    mods = e.modifiers()
    parts = []
    if mods & _Qt.ControlModifier:
        parts.append("Ctrl")
    if mods & _Qt.AltModifier:
        parts.append("Alt")
    if mods & _Qt.ShiftModifier:
        parts.append("Shift")
    if mods & _Qt.MetaModifier:
        parts.append("Win")
    k = e.key()
    if _Qt.Key_A <= k <= _Qt.Key_Z:
        parts.append(chr(k))
    elif _Qt.Key_0 <= k <= _Qt.Key_9:
        parts.append(chr(k))
    elif _Qt.Key_F1 <= k <= _Qt.Key_F24:
        parts.append(f"F{k - _Qt.Key_F1 + 1}")
    else:
        m = {_Qt.Key_Space: "SPACE", _Qt.Key_Tab: "TAB", _Qt.Key_Return: "RETURN",
             _Qt.Key_Backspace: "BACKSPACE", _Qt.Key_Insert: "INSERT",
             _Qt.Key_Delete: "DELETE", _Qt.Key_Home: "HOME", _Qt.Key_End: "END",
             _Qt.Key_PageUp: "PRIOR", _Qt.Key_PageDown: "NEXT",
             _Qt.Key_Up: "UP", _Qt.Key_Down: "DOWN", _Qt.Key_Left: "LEFT",
             _Qt.Key_Right: "RIGHT", _Qt.Key_Minus: "MINUS", _Qt.Key_Equal: "EQUAL",
             _Qt.Key_BracketLeft: "BRACKETLEFT", _Qt.Key_BracketRight: "BRACKETRIGHT",
             _Qt.Key_Backslash: "BACKSLASH", _Qt.Key_Semicolon: "SEMICOLON",
             _Qt.Key_Apostrophe: "APOSTROPHE", _Qt.Key_Comma: "COMMA",
             _Qt.Key_Period: "PERIOD", _Qt.Key_Slash: "SLASH", _Qt.Key_QuoteLeft: "GRAVE"}
        name = m.get(k)
        if name is None:
            return None
        parts.append(name)
    if not parts:
        return None
    return "+".join(parts)


class StatsTab(SettingsTab):
    """统计：换日刷新 / 识别名单 / 黑名单 / 白名单。

    ⚠ 这是设置页里最重的一个标签页：黑名单 / 白名单是**三层折叠卡片**，
      而且「离开设置页时的空名单提醒」也归它管（设置页留了个转发）。
    """

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win

        # ---- 摩拉单次计数上限 ----
        # 战斗时角色伤害数字会跟「获得」栏的摩拉读数叠在一起，OCR 可能一次
        # 读出「摩拉 12500」这种，一笔就把摩拉统计顶上天（几万、几十万都出现过）。
        # 超过这个上限的读数一律当误读丢掉（同时写进识别日志，来源列标「未统计」）。
        # 0 = 不限制（老行为）。
        cap = int(self.cfg.get("mora_max_amount", 3000) or 0)
        self.mora_cap_entry = QLineEdit(str(cap))
        self.mora_cap_entry.setFixedWidth(90)
        self.mora_cap_entry.setAlignment(Qt.AlignCenter)
        self.mora_cap_entry.setStyleSheet(entry_qss())
        self.mora_cap_entry.editingFinished.connect(self._on_mora_cap)
        _tip = ("战斗时角色的伤害数字会与「获得」栏的摩拉读数重叠，"
                "可能一次读出数万甚至数十万的异常值。\n"
                "超过该上限的读数一律判为误读：不计入摩拉统计，"
                "只写进识别日志（来源列标「未统计」）备查。\n\n"
                "填 0 表示不限制。")
        self.mora_cap_entry.setToolTip(_tip)
        _r = self.row("coins", "摩拉单次计数上限",
                      "单次读数上限；超过即判为误读并丢弃，0 为不限制",
                      self.mora_cap_entry, tip=_tip)

        # ---- 换日刷新数据（折叠卡片，默认收起）----
        # 展开里面两组：总开关 + 换日时间，每组下面紧跟一句说明。
        # 关掉开关就**完全不换日**，数据一直累着，直到手动清空。
        #
        # 排版：说明要跟它那一行贴在一起（组内 2px），两组之间才留大间距（14px）。
        # 以前每样都是 12px 平铺，说明就飘在两行正中间，看着空隙特别大。
        self.ro_switch = Switch(self,
                                bool(self.cfg.get("rollover_enabled", True)))
        self.ro_switch.toggled.connect(self._on_rollover_enabled)

        self.ro_entry = QLineEdit(str(int(self.cfg.get("rollover_hour", 0) or 0)))
        self.ro_entry.setFixedWidth(70)
        self.ro_entry.setAlignment(Qt.AlignCenter)
        self.ro_entry.setStyleSheet(entry_qss())
        self.ro_entry.editingFinished.connect(self._on_rollover)
        hour_box = QWidget()
        hl = QHBoxLayout(hour_box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self.ro_entry)
        unit = QLabel("点")
        unit.setStyleSheet(label_qss(T.DIM, 13))
        hl.addWidget(unit)

        ro_items = [
            ("refresh-cw", "启用换日刷新",
             "关闭后不再自动换日，数据持续累计", self.ro_switch, None,
             "按设定时间把当日数据归档、并重新开始统计（相当于「今天」这个概念翻页）。\n"
             "关闭后**完全不会自动换日**，数据一直累计，直到你手动清空 —— "
             "适合想统计「这一周总共刷了多少」的场景。"),
            ("clock", "换日时间（整点 0~23）",
             "跨零点挂机可适当延后，避免中途重新统计", hour_box, None,
             "每天几点算「新的一天」，默认 0 点（自然日），可设 0~23 整点。\n"
             "跨零点还在挂机的，建议设成 4 点：游戏本身也是凌晨 4 点刷日常，"
             "这样不会半夜打到一半被归档。"),
        ]
        self.ro_acc = Accordion(self, "sunrise", "换日刷新数据",
                                "到达设定时间后归档当日数据并重新开始统计",
                                items=ro_items, alpha=self.alpha,
                                tip="换日＝把当日统计归档，并从零开始累计新的一天。\n"
                                    "归档后的历史仍可在「收益细则」页查到，不会被删除。")
        self.add_card(self.ro_acc)

        # ---- 识别名单 ----
        # 放「统计」里（不放「开发」）—— 这个是日常要用的：
        # 识别到什么材料都按这个名单判定，名字错了或者漏了要能随时改。
        warn = QLabel("⚠ 名单决定可识别的物品范围。不在名单中的名称不会被统计；"
                      "若名单被清空，将无法识别任何物品，请用「恢复默认名单」还原。")
        warn.setWordWrap(True)
        warn.setStyleSheet(label_qss("#E06C5A", 12, True))
        self.mat_acc = Accordion(
            self, "clipboard-list", "识别名单",
            "不要乱改！！！",
            items=self._make_mat_items(), alpha=self.alpha, footer=warn,
            tip="名单决定**哪些名字算数**：认出来的名字不在名单里，一律不入账，"
                "只会记进识别日志备查。\n"
                "内置名单含材料与圣遗物共 800 多条，正常游玩无需改动；"
                "只有遇到「某个明明捡到了却没统计」才需要往里加名字。\n"
                "**名单被清空会导致什么都识别不到**，误删请用「恢复默认名单」。")
        self.add_card(self.mat_acc)
        self._refresh_mat_count()

        # ---- 黑名单 / 白名单（决定「认出来了要不要记账」）----
        # 层级（用户指定）：
        #   黑名单管理 ▸  材料黑名单 [开关] ▸ 配置名单 ▸ …
        #                圣遗物黑名单 [开关] ▸ 配置名单 ▸ …
        #   白名单管理 ▸  材料白名单 [开关] ▸ 配置名单 ▸ …
        #                圣遗物白名单 [开关] ▸ 配置名单 ▸ …
        # 主卡片**没有开关**，开关在材料 / 圣遗物那一层；开了才出现配置卡片。
        self.filter_switches = {}       # 名单键 -> Switch（在卡片头上）
        self.filter_units = {}          # 名单键 -> SwitchAccordion
        self.filter_cfg_accs = {}       # 名单键 -> 「配置名单」折叠卡片
        self.filter_sub_accs = {}       # 名单键 -> 同 units（老名字，留着兼容）
        for kind, kind_label, icon_name, main_title, main_desc in (
                ("black", "黑名单", "eye-off", "黑名单管理",
                 "名单里的物品识别到了也不记账"),
                ("white", "白名单", "square-check", "白名单管理",
                 "只记账名单里的物品，其余一律不记")):
            self.add_card(
                self._build_filter_group(kind, kind_label, icon_name,
                                         main_title, main_desc))

    # ---------- 黑名单 / 白名单 ----------

    def _build_filter_group(self, kind, kind_label, icon_name,
                            main_title, main_desc):
        """一张主卡片（黑名单管理 / 白名单管理）。

        层级（用户指定）：
            主卡片（**没有开关**）         <- Accordion
              └ 材料XX名单  [开关]         <- SwitchAccordion
                   点标题展开 →「配置名单」<- 自己给的控件，不再被包卡片
        """
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        for cat, cat_label in (("material", "材料"), ("artifact", "圣遗物")):
            key = f"{cat}_{kind}"
            label = f"{cat_label}{kind_label}"
            is_white = (kind == "white")
            filt_desc = (f"只记账名单里的{cat_label}" if is_white
                         else f"名单里的{cat_label}不记账")

            # 「配置名单」那张卡片（内容区的真正内容）
            # ⚠ 图标名要写**存在的**：icons 里没有 "list"，写错了 Qt 会把名字
            #   当**文字**画出来（这里以前就画着"list"四个字母）。
            # ⚠ 原来这里是 `lambda k=key: self._open_filter(k)` ——
            #   clicked 塞进来的 checked(False) 会把 k 顶掉，点这张卡片
            #   实际是 `_open_filter(False)`（2026-10-04 顺手修掉）。
            cfg_btn = small_button(
                "配置名单", bind_cb(self._open_filter, key), self.alpha,
                icon="file-text", width=104, height=30)
            cfg_acc = Accordion(
                body, "file-text", "配置名单",
                self._filter_cfg_desc(key, label, []),
                items=[("file-text", label, "打开后搜索、勾选", cfg_btn, None,
                        ("打开名单编辑窗，可以按名字搜索、勾选需要的"
                         f"{'材料' if cat == 'material' else '圣遗物'}。\n"
                         "名单里已选中的项会打勾，改完直接生效。"))],
                alpha=T.panel_alpha(self.alpha),
                tip="这张卡片里放的就是当前名单的内容，"
                    "点「配置名单」按钮打开编辑窗。")
            self.filter_cfg_accs[key] = cfg_acc

            if kind == "white":
                unit_tip = (f"开启后**只有**名单里的{cat_label}会被记账，"
                            "名单之外的一律不统计。\n"
                            "⚠ 白名单开着但**名单为空**时，什么都记不了；"
                            "离开设置页时会弹窗提醒并自动关闭白名单。\n"
                            "适合「只想统计某几样」的场景。")
            else:
                unit_tip = (f"开启后，名单里的{cat_label}即使认出来也不记账。\n"
                            "黑名单为空不影响识别，只是不排除任何物品。\n"
                            "适合把不关心的掉落（如常见垃圾材料）排除在统计之外。")
            unit = SwitchAccordion(
                body, icon="layers", title=label, desc=filt_desc,
                alpha=T.panel_alpha(self.alpha),
                checked=svc_names.is_enabled(self.cfg.raw, key),
                body=cfg_acc, tip=unit_tip)
            unit.toggled.connect(
                lambda v, k=key, lb=label: self._on_filter_toggled(k, v, lb))
            self.filter_units[key] = unit
            self.filter_switches[key] = unit.switch
            self.filter_sub_accs[key] = unit

            bl.addWidget(unit)

        if kind == "white":
            main_tip = ("白名单＝**只记账名单里的物品**，其余一律不记。\n"
                        "开关在下面「材料白名单 / 圣遗物白名单」那一层，"
                        "开了才会出现「配置名单」。\n"
                        "⚠ 白名单为空会导致该类物品完全统计不到，"
                        "离开设置页时会有提醒。")
        else:
            main_tip = ("黑名单＝**名单里的物品不记账**，其余照常统计。\n"
                        "开关在下面「材料黑名单 / 圣遗物黑名单」那一层，"
                        "开了才会出现「配置名单」。\n"
                        "黑名单为空不影响识别，只是不排除任何物品。")
        return Accordion(self, icon_name, main_title, main_desc,
                         items=None, body_widget=body, alpha=self.alpha,
                         tip=main_tip)

    @staticmethod
    def _filter_cfg_desc(key, label, names):
        """配置名单那张卡片的简介：带上当前有几个名字"""
        cat = "材料" if key.startswith("material") else "圣遗物"
        n = len(names or [])
        if not n:
            return f"还没配任何{cat} —— 打开后搜索、勾选"
        return f"已配 {n} 个{cat}，打开后可继续增删"

    def _on_filter_toggled(self, key, val, label):
        """开关一变：写设置 + 让「配置名单」跟着显隐"""
        filters = svc_names.get(self.cfg.raw)
        filters[key]["enabled"] = bool(val)
        self.cfg.set("records.filters", filters)
        acc = self.filter_cfg_accs.get(key)
        if acc is not None:
            acc.desc_label.setText(
                self._filter_cfg_desc(key, label, filters[key]["names"]))

    def _open_filter(self, key):
        """打开某张名单的配置窗"""
        import qt_dialogs
        label = svc_names.KEY_LABEL.get(key, key)
        cat = "材料" if key.startswith("material") else "圣遗物"
        is_white = key.endswith("_white")
        desc = (f"只有在这张名单里的{cat}才会被记账；名单为空则什么都记不了。"
                if is_white else
                f"在这张名单里的{cat}识别到了也不记账。")
        try:
            import svc_names
            d = svc_names.load()
            pool = d.get("materials" if cat == "材料" else "artifacts") or []
        except Exception:
            pool = []
        cur = svc_names.names_of(self.cfg.raw, key)
        dlg = qt_dialogs.NameListDialog(self, key, f"配置{label}", desc,
                                        pool, cur, alpha=self.alpha)
        if dlg.exec() != QDialog.Accepted:
            return
        filters = svc_names.get(self.cfg.raw)
        filters[key]["names"] = dlg.chosen()
        self.cfg.set("records.filters", filters)
        acc = self.filter_cfg_accs.get(key)
        if acc is not None:
            acc.desc_label.setText(
                self._filter_cfg_desc(key, label, filters[key]["names"]))

    # ---------- 离开设置页时的空名单提醒 ----------

    def warn_empty_filters(self):
        """检查「开着但空着」的名单，弹窗提醒 + 自动关掉白名单。

        用户要求：
          · 弹窗要弹在**应用正中间**
          · 白名单为空 = 识别不到任何内容，文案要提到「去识别里关掉」
            并且**自动把该白名单关掉**（提示语里写「白名单功能已关闭」）
          · 弹完才切页 —— 所以主窗口必须在 setCurrentIndex **之前**调它

        ⚠ 第 9 批之前这是 `PageSettings.on_hide`；现在本体在这个标签页里，
          设置页的 `on_hide` 只负责转发一下（因为它才是「页面」）。
        """
        whites = svc_names.empty_enabled_whitelists(self.cfg.raw)
        blacks = svc_names.empty_enabled_blacklists(self.cfg.raw)
        if not whites and not blacks:
            return

        lines = []
        for key in whites:
            label = svc_names.KEY_LABEL.get(key, key)
            cat = "材料" if key.startswith("material") else "圣遗物"
            enable_key = ("enable_material" if cat == "材料"
                          else "enable_artifact")
            if bool(self.cfg.get(enable_key, True)):
                tip = ("如不需要识别这项内容，可前往「设置 → 识别」里"
                       "将其关闭。")
            else:
                tip = ("如需重新识别这项内容，可前往「设置 → 识别」里"
                       "重新开启。")
            lines.append(f"「{label}」为空，将识别不到{cat}任何内容。\n"
                         f"{tip}\n白名单功能已关闭。")
        for key in blacks:
            label = svc_names.KEY_LABEL.get(key, key)
            cat = "材料" if key.startswith("material") else "圣遗物"
            lines.append(f"「{label}」为空，不会过滤任何{cat}。\n"
                         "（黑名单为空不影响识别，只是不排除任何物品。）")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("名单为空")
        box.setText("检测到名单已开启但没有内容")
        box.setInformativeText("\n\n".join(lines))
        box.setStandardButtons(QMessageBox.Ok)
        box.setStyleSheet(f"""
            QMessageBox {{ background: {T.BG}; }}
            QMessageBox QLabel {{ color: {T.TEXT}; background: transparent; }}
        """)
        self._center_on_app(box)
        box.exec()

        # 白名单：自动关掉（用户要求「白名单功能已关闭」）
        if whites:
            filters = svc_names.get(self.cfg.raw)
            for key in whites:
                filters[key]["enabled"] = False
            self.cfg.set("records.filters", filters)
            for key in whites:
                sw = self.filter_switches.get(key)
                if sw is not None:
                    sw.blockSignals(True)
                    sw.setChecked(False)
                    sw.blockSignals(False)
                acc = self.filter_cfg_accs.get(key)
                if acc is not None:
                    acc.setVisible(False)

    def _center_on_app(self, dlg):
        """把一个弹窗摆到**应用窗口正中间**（用户要求）"""
        try:
            win = self.window()
            dlg.adjustSize()
            g = win.frameGeometry()
            dlg.move(g.center().x() - dlg.width() // 2,
                     g.center().y() - dlg.height() // 2)
        except Exception:
            pass

    # ---------- 识别名单 ----------

    def _make_mat_items(self):
        """识别名单那一组子卡片（挂在「统计」页）"""
        items = []

        # 1) 管理识别名单
        self.name_count_label = QLabel("")
        self.name_count_label.hide()
        edit_btn = small_button("管理…", self._open_material_editor, self.alpha,
                                icon="clipboard-list", width=84, height=30)
        items.append(("clipboard-list", "管理识别名单",
                      "查看、增删名单里的名字", edit_btn, None,
                      "打开名单编辑器，可以搜索、勾选、增删名字，"
                      "也可以把不在名单里的名字加进去。\n"
                      "改完立即生效，不用重启软件。\n"
                      "「材料 N 个 / 圣遗物 N 个」显示的是当前名单规模。"))

        # 2) 恢复默认名单
        reset_btn = small_button("恢复默认", self._reset_names, self.alpha,
                                 kind="danger", icon="refresh-cw", width=104,
                                 height=30)
        items.append(("refresh-cw", "恢复默认名单",
                      "恢复成内置名单", reset_btn, None,
                      "把识别名单还原成程序内置的那一份。\n"
                      "⚠ 你自己加过或删过的名字都会丢失（会先弹窗确认）。\n"
                      "误删导致什么都识别不到时，用这个恢复。"))

        return items

    def _reset_names(self):
        """恢复默认识别名单"""
        import svc_names
        try:
            cur = svc_names.load()
            n = len(cur["materials"]) + len(cur["artifacts"])
        except Exception:
            n = 0
        if QMessageBox.question(
                self, "恢复默认名单",
                "会把识别名单还原成内置的那份。\n\n"
                "你自己加过或删过的名字都会没掉。\n"
                f"当前名单 {n} 个。确定吗？") != QMessageBox.Yes:
            return
        try:
            svc_names.reset_to_default()
            # ⚠ 原来是裸的 `reload_names()` —— 那个名字在 qt_pages 里**根本没定义**
            #   （列表还老是提示"恢复失败：name 'reload_names' is not defined"），
            #   正确入口是 svc_capture.reload_names（下面的"管理…"一直用的是它）。
            svc_capture.reload_names()
            self._refresh_mat_count()
            msg_info(self, "已恢复", "识别名单已还原成内置的。")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"恢复失败：{e}")

    def _refresh_mat_count(self):
        try:
            import svc_names
            d = svc_names.load()
            txt = (f"材料 {len(d['materials'])} 个　"
                   f"圣遗物 {len(d['artifacts'])} 个")
        except Exception:
            txt = "（读取失败）"
        self.name_count_label.setText(txt)
        acc = getattr(self, "mat_acc", None)
        if acc is not None:
            for c in acc.item_cards:
                if c.title_label.text() == "管理识别名单":
                    c.desc_label.setText(txt)

    def _open_material_editor(self):
        from qt_dialogs import MaterialDialog
        dlg = MaterialDialog(self._win, self.alpha)
        dlg.exec()
        # 改完名单立刻生效（detector 里的集合是原地更新的）
        try:
            svc_capture.reload_names()
        except Exception:
            pass
        self._refresh_mat_count()

    def _reset_materials(self):
        """旧名字，保留兼容（现在的入口是「恢复默认名单」）"""
        self._reset_names()

    # ---- 换日刷新 ----

    def _on_mora_cap(self):
        """摩拉单次计数上限：写进设置。

        ⚠ 这里**不用** `apply_live()`：识别器是每次解析时现读
          `settings["mora_max_amount"]` 的（见 `detector._mora_over_limit`），
          所以改完立刻生效，不需要推给正在跑的那个实例。
        """
        try:
            v = int(float(self.mora_cap_entry.text().strip()))
        except Exception:
            v = 3000
        v = max(0, min(9999999, v))
        self.mora_cap_entry.setText(str(v))
        self.cfg.set("mora_max_amount", v)

    def _on_rollover(self):
        try:
            h = int(self.ro_entry.text().strip()) % 24
        except Exception:
            h = 0
        self.ro_entry.setText(str(h))
        self.cfg.set("rollover_hour", h)

    def _on_rollover_enabled(self, v):
        """换日刷新数据的总开关"""
        self.cfg.set("rollover_enabled", bool(v))


class UpgradeTab(SettingsTab):
    """升级：更新渠道 + 检测更新（+ 自动更新那套下载/替换）。

    ⚠ 这一页有两个东西**必须从外面够得着**：
      · `update_dot` —— 检测到新版本时，侧栏/标签上的红点要跟着亮
        （设置页的 `set_update_badge` 找它）
      · `update_row` —— 侧栏点红点要能滚到「版本更新」那一行
        （设置页的 `goto_update` 找它）

    ⚠ 检测更新的结果是从**后台线程**发回来的，所以信号定义在**这个类**上
      （原来定义在 `PageSettings` 上）。后台线程绝对不能直接碰控件。
    """

    update_checked = Signal(object, object)      # 检测更新结果（从后台线程发回来）

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win
        self.update_checked.connect(self._update_result)

        # ---- 版本卡片（hero）----
        # 2026-10-04 改版：原来这一页只有两行、底下大半页空白，用户说"太丑"。
        # 现在把版本号、状态、按钮、进度、更新说明全收进**一张卡片**，
        # 跟新的卡片弹窗一个调性（大号版本号 + 状态胶囊 + 强调色按钮）。
        card = Card(self, alpha=self.alpha)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.ver_label = QLabel(f"StatGI {VERSION}")
        self.ver_label.setStyleSheet(T.title_qss(26))
        top.addWidget(self.ver_label)
        top.addStretch(1)
        self.state_pill = QLabel("还没检测")
        self.state_pill.setStyleSheet(self._pill_qss(T.DIM))
        top.addWidget(self.state_pill, 0, Qt.AlignTop)
        cl.addLayout(top)

        self.detail_label = QLabel("点「检测更新」去网上比对最新版本（需联网）")
        self.detail_label.setStyleSheet(label_qss(T.DIM, 12))
        self.detail_label.setWordWrap(True)
        cl.addWidget(self.detail_label)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.update_btn = QPushButton("检测更新")
        # 用最小宽度而不是固定 130 —— 固定宽度会让按钮比文字宽一大截，
        # 挂在它右上角的红点看着就像挂在卡片上了
        self.update_btn.setMinimumWidth(108)
        self.update_btn.setFixedHeight(34)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setStyleSheet(btn_qss("accent", self.alpha))
        set_btn_icon(self.update_btn, "refresh-cw", 15, color="#08222E")
        self.update_btn.clicked.connect(self._on_check_update)
        btns.addWidget(self.update_btn)

        self.page_btn = QPushButton("打开发布页")
        self.page_btn.setMinimumWidth(108)
        self.page_btn.setFixedHeight(34)
        self.page_btn.setCursor(Qt.PointingHandCursor)
        self.page_btn.setStyleSheet(btn_qss("normal", self.alpha))
        set_btn_icon(self.page_btn, "globe", 15)
        self.page_btn.clicked.connect(self._open_release_page)
        self.page_btn.setEnabled(False)          # 还不知道地址，检测到再亮
        btns.addWidget(self.page_btn)
        btns.addStretch(1)
        cl.addLayout(btns)

        # ---- 下载进度（只有真在下载时才出现）----
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(18)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background:{rgba('#FFFFFF', 20)}; border:none;"
            f" border-radius:9px; text-align:center; color:{T.TEXT};"
            f" font-size:11px; }}"
            f"QProgressBar::chunk {{ background:{T.ACCENT}; border-radius:9px; }}")
        self.progress.hide()
        cl.addWidget(self.progress)

        # ---- 更新说明（发现新版本时才出现）----
        self.notes_box = QFrame()
        self.notes_box.setStyleSheet(
            f"QFrame {{ background:{rgba('#FFFFFF', 12)}; border:none;"
            f" border-radius:10px; }}")
        nl = QVBoxLayout(self.notes_box)
        nl.setContentsMargins(14, 12, 14, 12)
        nl.setSpacing(8)
        self.notes_title = QLabel("")
        self.notes_title.setStyleSheet(label_qss(T.ACCENT, 14, True))
        nl.addWidget(self.notes_title)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notes_label.setStyleSheet(label_qss(T.TEXT, 13))
        nl.addWidget(self.notes_label)
        self.go_btn = QPushButton("立即更新")
        self.go_btn.setFixedHeight(34)
        self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.setStyleSheet(btn_qss("accent", self.alpha))
        self.go_btn.clicked.connect(self._on_go_update)
        nl.addWidget(self.go_btn)
        self.notes_box.hide()
        cl.addWidget(self.notes_box)

        self.add_card(card)
        # ⚠ 侧栏点红点要滚到这一行 —— `update_row` 这个名字必须留着
        self.update_row = card
        # 检测到新版本时挂个红点（挂在**按钮**右上角，不是整张卡片上）
        self.update_dot = RedDot(self.update_btn)

        # ---- 更新渠道 ----
        # 国内用 Gitee 快；GitHub 的 API 有每小时 60 次的限流，
        # 所以版本信息走的是仓库里的 version.json（raw 地址，不限流）。
        self.channel_dd = self._dd([n for n, _v in
                                    __import__("qt_update").CHANNELS], width=170)
        _cur = str(self.cfg.get("update_channel", "auto") or "auto")
        self.channel_dd.setCurrentText(
            {"auto": "自动", "gitee": "Gitee（国内快）",
             "github": "GitHub"}.get(_cur, "自动"))
        self.channel_dd.currentTextChanged.connect(self._on_update_channel)
        self.row("globe", "更新渠道",
                 "更新检测与安装包下载源；国内推荐 Gitee",
                 self.channel_dd,
                 tip="决定「检测更新」走哪个下载源：\n"
                     "· 自动 —— 按网络情况在 Gitee / GitHub 之间挑一个能用的；\n"
                     "· Gitee（国内快）—— 国内下载速度更稳；\n"
                     "· GitHub —— 更新说明与发布页在 GitHub 上时选它。\n"
                     "版本信息本身走仓库里的说明文件，不限流；"
                     "只有下载安装包才走上面选的源。")
        self._info = None            # 最近一次检测结果（「立即更新」要用）

    # ---- 小工具 ----

    @staticmethod
    def _pill_qss(color):
        """状态胶囊（圆角小标签）"""
        return (f"color:{color}; background:{rgba(color, 40)};"
                f" border-radius:10px; padding:4px 12px;"
                f" font-family:'{T.FONT}'; font-size:12px; font-weight:600;")

    def _set_state(self, text, color, detail=""):
        self.state_pill.setText(str(text))
        self.state_pill.setStyleSheet(self._pill_qss(color))
        if detail:
            self.detail_label.setText(str(detail))
            self.detail_label.setStyleSheet(label_qss(T.DIM, 12))

    def _open_release_page(self):
        url = str((self._info or {}).get("url", "") or "").strip()
        if url:
            try:
                __import__("webbrowser").open(url)
            except Exception:
                pass

    def _on_go_update(self):
        """卡片上那个「立即更新」"""
        info = self._info or {}
        try:
            import qt_updater
            up = qt_updater.update_info_from({"update": info.get("update")})
        except Exception:
            up = None
        if up:
            self._do_auto_update(up, info.get("version", ""), info.get("notes", ""))

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_check_update(self):
        self._set_state("正在检测…", T.DIM, "正在联网比对，请稍候…")
        try:
            self.update_btn.setEnabled(False)     # 别让用户连点
        except Exception:
            pass
        import threading
        import qt_update

        ch = str(self.cfg.get("update_channel", "auto") or "auto")

        def _do():
            # 网络活儿在后台线程干，结果用信号发回主线程
            # （后台线程绝对不能直接碰控件）
            try:
                info, used, reason = qt_update.check(ch, bust_cache=True)
            except Exception:
                info, used, reason = None, "", "network"
            self.update_checked.emit(info, reason)

        threading.Thread(target=_do, daemon=True).start()

    def _update_result(self, info, reason):
        import qt_update
        if not info:
            self._set_state("检测失败", "#E06C5A",
                            f"{qt_update.reason_text(reason)}"
                            "　·　点「检测更新」重试")
            self.update_btn.setEnabled(True)
            return
        ver = info.get("version", "")
        used = qt_update.CHANNEL_NAMES.get(info.get("channel", ""), "")
        self._info = info
        self.update_btn.setEnabled(True)
        self.page_btn.setEnabled(bool(str(info.get("url", "") or "").strip()))
        if not info.get("is_newer"):
            # 远端不比本地新（包括远端更旧的情况）—— 都算「已是最新」
            self._set_state("已是最新", "#6CCB5F",
                            f"当前 {VERSION}　·　来自 {used}"
                            f"　·　{time.strftime('%H:%M')} 检测")
            self.notes_box.hide()
            return
        self._set_state(f"发现新版本 {ver}", T.ACCENT,
                        f"当前 {VERSION} → {ver}　·　来自 {used}")
        self._show_update_available(info)

    def _show_update_available(self, info):
        """发现新版本 —— **就在卡片里展开说明**，不再弹一个朴素对话框。

        2026-10-04 改版：原来发现新版本会弹 QDialog，跟新界面风格不搭；
        现在信息直接铺在卡片上（更新说明可选中复制），按钮也在这张卡片里。
        """
        ver = info.get("version", "")
        notes = str(info.get("notes", "") or "").strip()
        try:
            import qt_updater
            up = qt_updater.update_info_from({"update": info.get("update")})
        except Exception:
            up = None

        size_txt = ""
        if up and up.get("size"):
            size_txt = f"（安装包约 {up['size'] / 1024 / 1024:.0f} MB）"
        self.notes_title.setText(f"新版本 {ver} 更新内容{size_txt}")
        self.notes_label.setText(notes or "（这次没有写更新说明）")
        # 没有自动更新信息（version.json 里没带分卷地址）→ 只能去发布页手动下
        self.go_btn.setVisible(bool(up))
        if not up:
            self.detail_label.setText(
                f"当前 {VERSION} → {ver}　·　点右边「打开发布页」手动下载")
        self.notes_box.show()

    def _ask_update(self, info):
        """兼容旧调用：现在不弹窗了，直接在卡片里展开"""
        self._show_update_available(info)

    def _do_auto_update(self, up, ver, notes=""):
        """下载 → 合并 → 校验 → 解压 → 交给「更新.bat」去替换

        下载在**后台线程**跑，进度通过信号发回主线程更新界面 ——
        后台线程绝对不能直接碰控件。
        """
        import qt_updater
        from PySide6.QtCore import QObject, Signal

        class Sig(QObject):
            progress = Signal(int, int)
            msg = Signal(str)
            done = Signal(bool, str)

        dlg = self._make_progress_dialog(ver, (up or {}).get("size", 0),
                                         notes)
        sig = Sig()
        state = {"dir": None, "cancel": False, "msg": "准备中…", "prog": (0, 0)}
        # ⚠ 「取消」以前是**假的**：点了只是把窗关掉，下载线程照样跑完，
        #   然后照样问你"现在开始更新？"、照样关软件 —— 点取消反而更懵。
        #   现在真的取消：拒绝即置位，`on_fin` 看到就掉头。
        dlg.rejected.connect(lambda: state.__setitem__("cancel", True))

        def on_p(p, t):
            # 进度、速度、MB 都在弹窗里自己算（它内部有采样窗口）
            dlg.set_progress(p, t)

        def on_msg(s):
            # 更新器说的话（正在校验 / 正在解压…）—— 直接显示在速度那一行；
            # 下载中紧接着的进度回调会把它盖回"速度 …"，所以不会打架
            state["msg"] = str(s)
            dlg.set_status(str(s))

        sig.progress.connect(on_p)
        sig.msg.connect(on_msg)

        def work():
            try:
                d = qt_updater.prepare(up, on_log=lambda s: sig.msg.emit(str(s)),
                                       on_progress=lambda a, b: sig.progress.emit(int(a), int(b)))
                state["dir"] = d
                sig.done.emit(True, "")
            except Exception as e:
                sig.done.emit(False, str(e))

        def on_fin(ok, err):
            if state["cancel"]:
                return                    # 用户取消了，什么都别做
            if not ok:
                QMessageBox.warning(self, "更新没做成",
                                    f"{err}\n\n当前版本不受影响，可稍后重试，"
                                    "或点击「打开下载页」手动下载。")
                dlg.reject()
                return
            try:
                bat = qt_updater.write_updater(state["dir"])
            except Exception as e:
                QMessageBox.warning(self, "更新没做成", f"准备更新脚本失败：{e}")
                dlg.reject()
                return
            dlg.accept()
            if not self._make_ready_dialog(ver):
                return
            if not qt_updater.launch_updater(bat):
                QMessageBox.warning(self, "启动更新失败",
                                    f"请手动双击这个文件完成更新：\n{bat}")
                dlg.reject()
                return
            dlg.accept()
            # 关掉自己，让更新脚本接手。
            # 三步走，越往后越狠：
            try:
                self._win.hide()         # 先藏窗口，别让用户盯着一个卡住的界面
            except Exception:
                pass
            try:
                self._win._shutdown()    # 停监测 / 关子窗口 / 停接口
            except Exception:
                pass
            qt_updater.force_quit_soon(3)   # 兜底：3 秒后强杀自己
            QApplication.quit()

        sig.done.connect(on_fin)

        import threading
        threading.Thread(target=work, daemon=True).start()
        dlg.exec()

    def _make_progress_dialog(self, ver, size=0, notes=""):
        """下载进度弹窗（旋转图标 + 进度条 + 速度 + 上面轮播公告/宝典）。

        2026-10-04 按用户草图重做；抽成方法是为了能**单独渲染/测试** ——
        不然它藏在「点立即更新 → 后台线程 → 信号」这条链路里，谁也看不见。
        """
        from qt_update_progress import UpdateProgressDialog
        return UpdateProgressDialog(self, alpha=self.alpha, ver=ver,
                                    size=size, notes=notes)

    def _make_ready_dialog(self, ver):
        """下载完 → 问「现在开始更新吗」（也是卡片式，跟前面一致）"""
        dlg = self._build_ready_dialog(ver)
        return dlg.exec() == QDialog.Accepted

    def _build_ready_dialog(self, ver):
        """只搭不显示 —— 方便单独渲染/测试"""
        dlg = CardDialog(self, alpha=self.alpha, title="更新已准备好",
                         width=340)
        dlg.set_subtitle(f"新版本 {ver} 已经下载好了。")
        body = QLabel("点「现在更新」之后：\n"
                      "· 软件自动关闭\n"
                      "· 自动完成替换（会弹出一个命令行窗口，别关它）\n"
                      "· 更新完自动重新打开\n\n"
                      "设置与收益数据不会被覆盖。")
        body.setWordWrap(True)
        body.setStyleSheet(label_qss(T.TEXT, 13))
        dlg.add_widget(body)
        dlg.add_secondary("稍后再说", dlg.reject)
        dlg.add_confirm("现在更新")
        dlg.fit_to_subtitle(0.85)
        return dlg

    def _on_update_channel(self, text):
        val = {"自动": "auto", "Gitee（国内快）": "gitee",
               "GitHub": "github"}.get(text, "auto")
        self.cfg.set("update_channel", val)
        # 换渠道后状态就不准了 —— 复位成"还没检测"
        self._set_state("还没检测", T.DIM, "换了渠道，点「检测更新」重新比对")


class DevTab(SettingsTab):
    """开发：开发者模式 + 开发者选项（样本采集那几样）。

    ⚠ 「模拟检测到新版本」这个开关（`sim_update`）**设置页还要用** ——
      切走「开发」标签页时要把它自动关掉（见 `PageSettings._on_tab`），
      所以它必须是个能从外面拿到的属性（`_tab_attr("开发", "sim_update")`）。
    """

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win

        self.dev_enabled = Switch(self, bool(self.cfg.get("developer_mode", False)))
        self.dev_enabled.toggled.connect(self._on_developer_mode)
        self.row("wrench", "开发者模式",
                 "开启后显示下方维护工具", self.dev_enabled,
                 tip="打开后才会显示下面的「开发者选项」（样本采集等维护工具）。\n"
                     "普通使用不需要开启；关闭后已采集的样本文件不会被删除。")

        # ---- 识别日志（一次运行一个文件，放在 data/识别日志/）----
        # ⚠ 这几行**不放进「开发者选项」里** —— 它们是给普通用户反馈问题用的，
        #   藏进开发者模式就等于没有。
        log_open = small_button("打开文件夹", self._open_log_dir, self.alpha,
                                icon="folder-open", width=104)
        log_clear = small_button("清空", self._on_clear_logs, self.alpha,
                                 kind="danger", icon="trash", width=76)
        self.log_row = self.row(
            "file-text", "识别日志",
            "每次启动生成一个日志文件；目录超过 20 MB 自动清理最早文件",
            right_wrap(log_open, log_clear),
            tip="识别日志记的是**每一次判断**：认出了什么、原始文字是什么、"
                "这一笔有没有入账。查「为什么没统计到 / 为什么统计多了」全靠它。\n"
                "· 每次启动软件生成一个新文件（文件名就是启动时刻）；\n"
                "· 整个文件夹超过 20 MB 会从最老的开始自动清理；\n"
                "· 「清空」会删掉全部日志（正在识别也不受影响，下次写入会重建）。\n"
                "日志只写在本机，不会上传。")

        # ---- 一键收集问题信息 ----
        diag_btn = small_button("打包诊断信息", self._make_diagnose, self.alpha,
                                icon="activity", width=140)
        self.row("activity", "出了问题怎么办",
                 "打包版本、设置、报错日志与识别日志，用于问题反馈",
                 diag_btn,
                 tip="点一下会生成一个 zip，里面是：\n"
                     "· 环境概况（版本 / 系统 / 屏幕缩放 / 关键设置 / 数据文件大小）；\n"
                     "· 当前设置；\n"
                     "· 报错日志和最近一次识别日志的**末尾 400 行**。\n"
                     "默认存到桌面，把它发给作者就能定位问题。\n"
                     "包里的路径是本机路径，介意的话可以自己删掉几条再发。")

        # ---- 设置备份（导出 / 导入）----
        exp_btn = small_button("导出…", self._export_settings, self.alpha,
                               icon="file-text", width=92)
        imp_btn = small_button("导入…", self._import_settings, self.alpha,
                               icon="folder-open", width=92)
        self.row("database", "设置备份",
                 "导出设置、识别名单与悬浮窗配置，用于迁移或重装后恢复",
                 right_wrap(exp_btn, imp_btn),
                 tip="**导出**：把设置 / 识别名单 / 悬浮窗配置（含预设）/ 收藏夹"
                     "打包成一个 zip，换电脑、重装、给朋友一份配置都用它。\n"
                     "**导入**：从这样的 zip 恢复。导入前会先把现在这份**原样备份**"
                     "到 data/导入前备份_<时间>/，导错了还能自己拷回来。\n"
                     "⚠ 导入后建议重启软件，让全部设置生效。")

        # ---- 精确模式（外部数据源模块）----
        # ⚠ 主程序**不注入、不读游戏内存**：模块是用户自己另外下载的独立进程，
        #   风险由使用者自担（设计见 `_morph\外部数据源模块_设计.md`）。
        #   默认关；不装模块的话这一行只表示"有这么个东西"。
        precise_btn = small_button("管理…", self._open_precise, self.alpha,
                                   icon="plug", width=92)
        self.precise_row = self.row(
            "plug", "精确模式（需另装模块）",
            self._precise_desc(),
            precise_btn,
            tip="另装一个**独立模块**后，可以直接读取游戏内的掉落事件：\n"
                "· 数据精确到每一笔（材料 / 狗粮 / 摩拉），不再依赖截图识别；\n"
                "· 模块在线时识别会**自动暂停**（省 CPU），掉线 30 秒自动恢复。\n\n"
                "⚠ 该模块会读取游戏进程，属于第三方软件行为、违反游戏用户协议，"
                "**存在账号被封禁的可能，风险由使用者自行承担**。\n"
                "本程序自己不注入、不读内存；不装模块一切照旧（识别模式，零风险）。\n"
                "模块可以在本程序里直接下载安装，也可以随时卸载。")

        # ---- 开发者选项：折叠卡片，每一项一张子卡片 ----
        self.dev_acc = Accordion(self, "flask-conical", "开发者选项",
                                 "采集识别样本用于优化识别准确度；仅保存在本机，不上传、不入账",
                                 items=self._make_dev_items(), alpha=self.alpha,
                                 tip="这里的工具用于收集识别样本、排查识别问题，"
                                     "面向开发者与问题定位。\n"
                                     "所有截图**只保存在本机**，不会上传到任何服务器，"
                                     "也不参与收益统计。")
        self.add_card(self.dev_acc)
        self.dev_acc.setVisible(bool(self.cfg.get("developer_mode", False)))
        self._refresh_log_desc()

    # ------------------------------------------------------------ 精确模式
    def _precise_desc(self):
        """「精确模式」那一行的说明 —— 把**当前状态**写进去，不用点开就知道。

        ⚠ 每次读状态都要碰文件（心跳 / 安装记录），所以只在建行和关弹窗时调，
          不做定时刷新（设置页没必要每秒读盘）。
        """
        try:
            import svc_module
            st = svc_module.status()
            if st.get("state") == "online":
                return f"模块正在供数（{st.get('mod') or '模块'}）—— 识别已暂停"
            if svc_module.module_running():
                return "模块进程在跑，等待心跳…"
            if svc_module.installed():
                return "已安装模块，未运行 —— 当前是识别模式"
            return "未安装 —— 当前是识别模式（截图识别，零风险）"
        except Exception:
            return "未安装 —— 当前是识别模式（截图识别，零风险）"

    def _open_precise(self):
        """打开精确模式弹窗（风险告知 + 下载 / 启动 / 卸载）"""
        try:
            from qt_dlg_precise import PreciseModeDialog
            dlg = PreciseModeDialog(self._win, self.alpha,
                                    settings=self._win.state.settings)
            dlg.exec()
        except Exception:
            try:
                import errlog
                errlog.log_exc("精确模式弹窗")
            except Exception:
                pass
        try:
            self.precise_row.set_text(desc=self._precise_desc())
        except Exception:
            pass

        # 折叠卡片里的「保存目录」和「已采集样本」两行要动态更新，
        # 建完之后按标题把卡片找出来存好
        for c in self.dev_acc.item_cards:
            t = c.title_label.text()
            if t == "样本保存目录":
                self.dev_path_card = c
            elif t == "已采集样本":
                self.dev_stats_card = c
        self._set_dev_path(self.cfg.get("dataset_path", ""))
        self._refresh_dev_stats()

    # ---------- 开发者选项 ----------
    def _make_dev_items(self):
        """开发者选项的每一项（Accordion 会给每项包一张子卡片）"""
        DEFAULT_PATH = svc_capture.dataset_default_path()

        items = []

        # 1) 启用样本采集
        # 注意：DatasetCollector 读的键是 dataset_enabled，
        # 不是 dataset_collect —— 键名写错了这个开关就是空的。
        self.dev_switch = Switch(self,
                                 bool(self.cfg.get("dataset_enabled", False)))
        self.dev_switch.toggled.connect(
            lambda v: self.cfg.set("dataset_enabled", bool(v)))
        items.append(("flask-conical", "启用样本采集",
                      "开启后每次确认拾取都会存一张截图", self.dev_switch, None,
                      "确认拾取时，把当时的画面连同识别到的名字一起存成样本，"
                      "供后续改进识别用。\n"
                      "开启后会持续写入磁盘（受下方目录与容量限制），"
                      "平时建议关闭。"))

        # 2) 保存目录（长路径放说明里，太长会省略，完整路径在鼠标提示里）
        browse = small_button("浏览…", self._on_choose_dataset_path, self.alpha,
                              icon="folder-open", width=84)
        items.append(("folder-open", "样本保存目录",
                      "截图只存在这个文件夹里，不会上传", browse, None,
                      "样本截图的存放位置，默认放在用户数据目录下。\n"
                      "可以改到空间更大的磁盘。改动只影响之后新采集的样本，"
                      "已存在的文件不会被搬动。"))

        # 3) 已采集样本（统计数字写在说明里）
        self.dev_stats_label = QLabel("")     # 留着兼容，实际显示在子卡片的说明里
        self.dev_stats_label.hide()
        open_btn = small_button("打开", self._on_open_dataset, self.alpha,
                                icon="image", width=76)
        items.append(("database", "已采集样本", "", open_btn, None,
                      "已采集的数量与占用空间，超出上限时程序会自动清理最早的样本。\n"
                      "点「打开」在文件管理器里查看这些截图。"))

        # 4) 清空样本
        clear_btn = small_button("清空", self._on_clear_dataset, self.alpha,
                                 kind="danger", icon="trash", width=76)
        items.append(("trash", "清空样本",
                      "删掉全部已采集的截图，不影响收益数据", clear_btn, None,
                      "删除样本目录下**全部**已采集的截图。\n"
                      "只影响样本文件，**收益记录与统计不受影响**，且不可恢复。"))

        # 5) 预览「检测到新版本」的效果
        self.sim_update = Switch(self, False)
        self.sim_update.toggled.connect(self._on_sim_update)
        items.append(("eye", "模拟检测到新版本",
                      "预览左下角闪烁与设置红点的提示效果", self.sim_update, None,
                      "纯预览开关：打开后立刻模拟「检测到新版本」的提示效果，"
                      "用于确认提示是否明显。\n"
                      "离开「开发」标签页时会自动关闭，不会真的联网或更新。"))

        # ⚠ 这里原来有一组「弹窗预览」（标题/数字/材料/弹出来看看），
        #   2026-09-29 用户看过之后说**删掉** —— 不需要，别再加回来。
        #
        # ⚠ 也别在这里加「压测：生成假收益记录」这类按钮 ——
        #   用户明确说了不要这种功能，他只是想知道记录多了卡不卡。
        #   想量性能请用 `_morph\test_records_stress.py`（在临时目录里灌数据）。
        return items

    # ---------- 识别日志 / 诊断 / 设置备份 ----------

    def _refresh_log_desc(self):
        """把「本次多少行 / 一共几个文件多大」写到那一行的说明里"""
        try:
            import svc_diag
            st = svc_diag.log_stats()
            self.log_row.desc_label.setText(
                f"本次 {st['lines']} 行　·　共 {st['files']} 个文件 / "
                f"{svc_diag.human_size(st['bytes'])}　·　超过 20 MB 自动删最早的")
        except Exception:
            pass

    def _open_log_dir(self):
        try:
            self._win.open_log_dir()
        except Exception:
            pass

    def _on_clear_logs(self):
        import svc_diag
        try:
            st = svc_diag.log_stats()
        except Exception:
            st = {}
        if QMessageBox.question(
                self, "确认",
                f"清空识别日志？\n\n"
                f"会删掉 {st.get('files', 0)} 个日志文件"
                f"（{svc_diag.human_size(st.get('bytes', 0))}），包括本次的。\n"
                "正在识别不受影响，下次写入会自动重建。\n\n这个操作不能撤销。"
        ) != QMessageBox.Yes:
            return
        n, freed = svc_diag.clear_logs()
        self._refresh_log_desc()
        msg_info(self, "已清空",
                 f"删掉了 {n} 个日志文件，腾出 {svc_diag.human_size(freed)}。")

    def _make_diagnose(self):
        import svc_diag
        p = svc_diag.collect_diagnose()
        if p is None:
            msg_info(self, "打包失败", "诊断信息打包失败了，可以到 data 文件夹里手动找日志。")
            return
        msg_info(self, "打包好了",
                 f"诊断信息已保存到：\n{p}\n\n"
                 "把它发给作者就能定位问题（里面是本机路径和最近的日志）。")

    def _export_settings(self):
        import svc_diag
        from PySide6.QtWidgets import QFileDialog
        default = f"StatGI设置备份_{time.strftime('%Y%m%d')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "导出设置备份", default,
                                              "压缩包 (*.zip)")
        if not path:
            return
        p = svc_diag.export_settings(path)
        if p is None:
            msg_info(self, "导出失败", "导出失败了，换个位置再试试。")
            return
        msg_info(self, "导出好了",
                 f"设置备份已保存到：\n{p}\n\n"
                 "里面有设置、识别名单、悬浮窗配置和收藏夹。")

    def _import_settings(self):
        import svc_diag
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "导入设置备份", "",
                                              "压缩包 (*.zip)")
        if not path:
            return
        if QMessageBox.question(
                self, "确认导入",
                "导入会**覆盖**当前的设置、识别名单和悬浮窗配置。\n\n"
                "导入前会自动把现在这份备份到 data/导入前备份_xxx/，\n"
                "确定继续吗？"
        ) != QMessageBox.Yes:
            return
        try:
            done, backup = svc_diag.import_settings(path)
        except Exception as e:
            msg_info(self, "导入失败", f"这个文件读不了：{e}")
            return
        # 名单能立刻生效，其它设置（外观/缩放）建议重启
        try:
            svc_capture.reload_names()
        except Exception:
            pass
        self._refresh_log_desc()
        msg_info(self, "导入完成",
                 f"已导入：{'、'.join(done)}\n\n"
                 f"导入前的旧文件备份在：\n{backup}\n\n"
                 "建议重启软件，让全部设置生效。")

    def _set_dev_path(self, path):
        """把样本目录显示到子卡片的说明上（太长就省略，完整路径放提示气泡）"""
        full = str(path or "") or str(svc_capture.dataset_default_path())
        card = getattr(self, "dev_path_card", None)
        if card is not None:
            short = full if len(full) <= 32 else full[:15] + "…" + full[-14:]
            card.desc_label.setText(short)
            card.desc_label.setToolTip(full)
            card.setToolTip(full)

    def _on_sim_update(self, v):
        """开发者选项：把「检测到新版本」的提示效果开/关（纯粹为了看效果）"""
        self._win.set_update_available(bool(v), "9.9")

    def _on_developer_mode(self, v):
        self.cfg.set("developer_mode", bool(v))
        acc = getattr(self, "dev_acc", None)
        if acc is not None:
            acc.setVisible(bool(v))
        if v:
            self._refresh_dev_stats()

    def _refresh_dev_stats(self):
        try:
            st = svc_capture.dataset_stats(self.cfg.raw)
            txt = (f"共 {st.get('total', 0)} 张"
                   f"（正面 {st.get('gameplay', 0)} / 反面 {st.get('non_gameplay', 0)}）"
                   f"　占用 {st.get('size_mb', 0)} / {st.get('max_mb', 100)} MB")
        except Exception:
            txt = "（无法读取样本统计）"
        self.dev_stats_label.setText(txt)
        card = getattr(self, "dev_stats_card", None)
        if card is not None:
            card.desc_label.setText(txt)

    def _on_choose_dataset_path(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择样本保存位置")
        if not d:
            return
        self.cfg.set("dataset_path", d)
        self._set_dev_path(d)

    def _on_open_dataset(self):
        import os
        d = (self.cfg.get("dataset_path", "")
             or str(svc_capture.dataset_default_path()))
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)               # noqa  Windows 专用
        except Exception as e:
            QMessageBox.warning(self, "失败", f"打不开文件夹：{e}")

    def _on_clear_dataset(self):
        if QMessageBox.question(self, "确认", "确定清空所有采集的样本吗？\n（不可恢复）"
                                ) != QMessageBox.Yes:
            return
        try:
            svc_capture.dataset_clear(self.cfg.raw)
            self._refresh_dev_stats()
            QMessageBox.information(self, "已清空", "样本已清空。")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"清空失败：{e}")


class AppearanceTab(SettingsTab):
    """外观：卡片透明度 / 背景压暗 / 背景图 / 背景色 / 强调色 / 毛玻璃 / 统计条图标。

    ⚠ 这是唯一一个**要拿主窗口**的标签页（`win` 参数）。它要做的事
      （换背景图、压暗、毛玻璃、重建界面、遍历所有 Card 改透明度）全是
      窗口级操作，一个个包成回调反而看不清谁是谁。
      注意拿的是**主窗口**，不是 `AppState` —— 那个上面挂着 `toggle()`，
      **会启动识别**，设置页不该碰（第 8 批刚摘掉的东西，别在这儿请回来）。
    """

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win
        # 颜色下拉框的两道闸（原来住在 PageSettings 上）：
        #   `_color_busy`   —— 静默设置下拉框期间，别真的去应用颜色
        #   `_colors_ready` —— 界面还没建完时不要应用（应用会重建界面）
        self._color_busy = False
        self._colors_ready = False

        op = int(float(self.cfg.get("panel_opacity", 0.5) or 0.5) * 100)
        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setRange(0, 100)
        self.alpha_slider.setValue(op)
        self.alpha_slider.setFixedWidth(180)
        self.alpha_slider.setStyleSheet(slider_qss())
        self.alpha_label = QLabel(f"{op}%")
        self.alpha_label.setFixedWidth(46)
        self.alpha_label.setStyleSheet(label_qss(T.ACCENT, 13))
        self.alpha_slider.valueChanged.connect(self._on_alpha)
        self.row("contrast", "卡片透明度",
                 "卡片、侧边栏与按钮的统一不透明度；0% 为全透明",
                 right_wrap(self.alpha_slider, self.alpha_label),
                 tip="统一控制卡片、侧边栏、按钮的不透明度。\n"
                     "设成 0% 时几乎全透明（只剩文字），适合把窗口叠在游戏上；\n"
                     "设得高一些更清晰，但会挡住更多画面。\n"
                     "只改外观，不影响识别与统计。")

        dim = int(float(self.cfg.get("bg_dim", 0.0) or 0.0) * 100)
        self.dim_slider = QSlider(Qt.Horizontal)
        self.dim_slider.setRange(0, 60)
        self.dim_slider.setValue(dim)
        self.dim_slider.setFixedWidth(180)
        self.dim_slider.setStyleSheet(slider_qss())
        self.dim_label = QLabel(f"{dim}%")
        self.dim_label.setFixedWidth(46)
        self.dim_label.setStyleSheet(label_qss(T.ACCENT, 13))
        self.dim_slider.valueChanged.connect(self._on_dim)
        self.row("moon", "背景压暗",
                 "背景图压暗强度；对比度过高时可调高以提升可读性，0% 不压暗",
                 right_wrap(self.dim_slider, self.dim_label),
                 tip="给背景图盖一层暗色，让上面的文字更清楚。\n"
                     "风景、亮色照片类背景图通常需要 20%~40%；"
                     "纯色背景不需要调。\n"
                     "上限 60%，不会把背景压成纯黑。")

        pic = set_btn_icon(QPushButton("选择图片"), "image", 15)
        clr = set_btn_icon(QPushButton("清除"), "x", 15)
        for b, kind, cb in ((pic, "normal", self._choose_bg), (clr, "danger", self._clear_bg)):
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
        cur = self.cfg.get("bg_image") or ""
        self.bg_name = QLabel("")
        self.bg_name.setStyleSheet(label_qss(T.DIM, 12))
        # 长文件名会把整张卡片撑宽 —— 限宽 + 中间省略，完整名字放提示气泡里
        self.bg_name.setMaximumWidth(150)
        self._set_bg_name(cur)
        self.row("image", "自定义背景图片",
                 "设为窗口背景图；卡片区域自动转为半透明",
                 right_wrap(pic, clr, self.bg_name),
                 tip="选一张本地图片当窗口背景。设置后卡片区域转为半透明，"
                     "整体更贴近游戏画面。\n"
                     "建议用与游戏色调相近、对比不高的图；"
                     "太花会让文字难认（配合上面的「背景压暗」使用）。\n"
                     "图片只从本机读取，不会上传；点「清除」恢复纯色背景。")

        import theme as _theme_mod      # 只为了取预设名字列表
        bg_items = list(getattr(_theme_mod, "BG_PRESETS", {"经典深黑": "#1C1C1C"}).keys())
        ac_items = list(getattr(_theme_mod, "ACCENT_PRESETS", {"经典蓝": "#4CC2FF"}).keys())
        self.bg_dd = self._dd(bg_items + [CUSTOM_COLOR])
        self.accent_dd = self._dd(ac_items + [CUSTOM_COLOR])
        self._set_combo_silently(self.bg_dd, self.cfg.get("bg_color", "经典深黑"))
        self._set_combo_silently(self.accent_dd, self.cfg.get("accent_color", "经典蓝"))
        self.bg_dd.currentTextChanged.connect(self._on_bg_color)
        self.accent_dd.currentTextChanged.connect(self._on_accent_color)
        self.row("palette", "背景颜色",
                 "窗口背景色；可选预设或自定义", self.bg_dd,
                 tip="整个窗口的底色。选预设名即可；"
                     "选「自定义颜色…」会打开取色器。\n"
                     "改完立即生效（界面会重建一次，属于正常现象）。")
        self.row("rainbow", "强调色",
                 "按钮、选中项与数值高亮色；可选预设或自定义", self.accent_dd,
                 tip="按钮、开关、选中项、数值高亮用的主色调。\n"
                     "与背景色搭配使用：深色背景配亮一点的强调色更清楚。\n"
                     "同样支持「自定义颜色…」，改完立即生效。")

        self.sidebar_glass = Switch(self, bool(self.cfg.get("sidebar_glass", True)))
        self.sidebar_glass.toggled.connect(self._on_sidebar_glass)
        self.row("eye-off", "左侧栏毛玻璃效果",
                 "对侧边栏做模糊与压暗处理；需先设置背景图", self.sidebar_glass,
                 tip="对左侧栏做模糊 + 压暗，做出磨砂玻璃质感（需要先设置背景图）。\n"
                     "关掉则左侧栏用纯色。\n"
                     "模糊有轻微性能开销，低配机器可以关掉。")

        # 「统计条图标」放在这里（从「直播」挪过来的）
        icon_btn = QPushButton("打开图标管理")
        icon_btn.setFixedHeight(34)
        icon_btn.setCursor(Qt.PointingHandCursor)
        icon_btn.setStyleSheet(btn_qss("normal", self.alpha))
        icon_btn.clicked.connect(self._win.open_icon_manager)
        self.row("image", "统计条图标",
                 "统计条各格图标（摩拉 / 材料 / 狗粮）", icon_btn,
                 tip="打开图标管理器，给桌面统计条每一格挑图标，"
                     "也可以用自己的图片替换。\n"
                     "改动只影响显示，不影响统计结果。")

        # ---- 界面缩放（改完要重启）----
        self.scale_dd = self._dd(["100%（默认）", "110%", "125%"], width=140)
        _sc = float(self.cfg.get("ui_scale", 1.0) or 1.0)
        self.scale_dd.setCurrentText(
            {1.0: "100%（默认）", 1.1: "110%", 1.25: "125%"}.get(
                round(_sc, 2), "100%（默认）"))
        self.scale_dd.currentTextChanged.connect(self._on_ui_scale)
        self.row("monitor", "界面缩放",
                 "整体缩放界面；高分屏字体过小时使用，重启后生效", self.scale_dd,
                 tip="把整个界面（文字、按钮、间距）一起放大，"
                     "适合 2K / 4K 笔记本上觉得字太小的情况。\n"
                     "· 100%（默认）—— 原始大小；\n"
                     "· 110% / 125% —— 逐级放大。\n"
                     "⚠ **改完要重启软件才生效**（Qt 只在启动那一刻读这个值）。\n"
                     "放大后同屏显示的内容会变少，也建议先从 110% 试。")

        # ---- 停止监测时的小结 ----
        self.stop_sum = Switch(self, bool(self.cfg.get("stop_summary", True)))
        self.stop_sum.toggled.connect(
            lambda v: self.cfg.set("stop_summary", bool(v)))
        self.row("chart-bar", "停止监测时显示小结",
                 "停止监测后弹窗汇总本次时长与收益", self.stop_sum,
                 tip="点「停止监测」后弹一个小窗，汇总**本次**这一段：\n"
                     "时长、摩拉、材料（总数 + 前几名）、狗粮。\n"
                     "数据是这次开始到停止之间的增量，跟当日累计无关。\n"
                     "觉得每次弹窗烦可以关掉。")

        # 界面建完了，之后的下拉框变化才真的去应用颜色
        self._colors_ready = True

    def _on_ui_scale(self, text):
        """界面缩放：写设置 + 提示要重启。

        ⚠ 这个值 Qt **只在启动那一刻读**（main.py 里设 QT_SCALE_FACTOR），
          所以这里只能存下来、提示重启，没法立刻生效。
        """
        v = {"100%（默认）": 1.0, "110%": 1.1, "125%": 1.25}.get(text, 1.0)
        old = float(self.cfg.get("ui_scale", 1.0) or 1.0)
        self.cfg.set("ui_scale", v)
        if abs(v - old) > 0.001:
            msg_info(self, "重启后生效",
                     f"界面缩放已设为 {text}。\n\n"
                     "这个设置需要**重启软件**才会生效。")

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_alpha(self, v):
        self.alpha_label.setText(f"{v}%")
        self.cfg.set("panel_opacity", v / 100.0)
        a = int(v / 100 * 255)
        for c in self._win.findChildren(Card):      # 只改背景色，不重建控件
            c.set_alpha(a)

    def _on_dim(self, v):
        self.dim_label.setText(f"{v}%")
        self.cfg.set("bg_dim", v / 100.0)
        self._win.apply_bg_dim()

    def _set_bg_name(self, path):
        """显示背景图文件名。

        这个标签在卡片的右边，**文件名太长会把整张卡片撑宽** —— 撑宽之后
        外观栏看着就像被"拉长"了。所以限宽 + 中间省略，
        完整文件名放进鼠标提示里。
        """
        import os as _os
        name = _os.path.basename(path) if path else ""
        if not name:
            self.bg_name.setText("未设置（纯色背景）")
            self.bg_name.setToolTip("")
            return
        short = name if len(name) <= 16 else name[:7] + "…" + name[-6:]
        self.bg_name.setText(short)
        self.bg_name.setToolTip(name)

    def _choose_bg(self):
        from PySide6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not p:
            return
        try:
            from PIL import Image
            Image.open(p).verify()
        except Exception:
            msg_info(self, "失败", "该文件不是有效的图片，请重新选择。",
                     icon=QMessageBox.Warning)
            return
        self.cfg.set("bg_image", p)
        self._set_bg_name(p)
        self._win.set_background_image(p)
        msg_info(self, "成功", "背景图片已应用。")

    def _clear_bg(self):
        self.cfg.set("bg_image", "")
        self._set_bg_name("")
        self._win.set_background_image(None)

    def _on_sidebar_glass(self, v):
        self.cfg.set("sidebar_glass", bool(v))
        self._win.set_sidebar_glass(bool(v))

    # ---------- 背景色 / 强调色：改完立即生效 ----------

    @staticmethod
    def _combo_show_color(combo, value):
        """把设置里存的颜色显示到下拉框上。

        预设存的是名字（"经典深黑"），自定义存的是 "#RRGGBB" —— 后者
        下拉框里本来没有，得先插一项再选上，否则会显示成空白。
        """
        v = str(value or "")
        if v.startswith("#"):
            label = f"自定义 {v}"
            if combo.findText(label) < 0:
                combo.insertItem(max(0, combo.count() - 1), label)
            combo.setCurrentText(label)
        else:
            combo.setCurrentText(v)

    def _set_combo_silently(self, combo, value):
        """改下拉框，但**不触发** currentTextChanged。

        ⚠ 不加这个会出事：setCurrentText 会发信号 → 又走一遍「应用颜色」
          → 把下拉框上显示的**标签文字**当成颜色存进去，还会重复重建界面
          （重建会把控件删掉，紧跟着访问就崩）。
        """
        self._color_busy = True
        try:
            self._combo_show_color(combo, value)
        finally:
            self._color_busy = False

    def _pick_custom_color(self, key, combo):
        """开取色器选一个自定义颜色"""
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog

        cur = str(self.cfg.raw.get(key, "") or "")
        init = QColor(cur) if QColor.isValidColorName(cur) else QColor(T.ACCENT)
        col = QColorDialog.getColor(init, self._win, "选择颜色")
        if not col.isValid():
            # 取消了 → 下拉框回到当前实际值，别停在「自定义颜色…」上
            self._set_combo_silently(combo, self.cfg.raw.get(key, ""))
            return
        hexv = col.name()
        self._set_combo_silently(combo, hexv)
        self._apply_colors(key, hexv, display=f"自定义 {hexv}")

    def _apply_colors(self, key, value, display=None):
        self.cfg.set(key, value)
        T.reload_colors(self.cfg.raw)
        # ⚠ 先把主窗口记下来：rebuild_ui() 会把旧页面从窗口上摘掉，
        #   之后就找不到主窗口了，弹窗会跑到屏幕角落去。
        win = self._win
        win.rebuild_ui()
        msg_info(win, "已应用", f"颜色已切换为「{display or value}」。")

    def _on_bg_color(self, v):
        if getattr(self, "_color_busy", False):
            return
        if v == CUSTOM_COLOR:
            self._pick_custom_color("bg_color", self.bg_dd)
            return
        if getattr(self, "_colors_ready", False):
            self._apply_colors("bg_color", v)

    def _on_accent_color(self, v):
        if getattr(self, "_color_busy", False):
            return
        if v == CUSTOM_COLOR:
            self._pick_custom_color("accent_color", self.accent_dd)
            return
        if getattr(self, "_colors_ready", False):
            self._apply_colors("accent_color", v)


GROUP_REFRESH_MARK = "\u21bb \u5237\u65b0\u7ec4\u540d\u5217\u8868"


class GroupCombo(QComboBox):
    """配置组用的下拉框（可编辑）。

    为什么要这个子类：老代码和测试都用的是 `.text()` / `.setText()`（原来是
    QLineEdit）。这里给下拉补上同样名字的方法，两边就都不用改了。
    「↻ 刷新组名列表」这一项不算组名，`text()` 里会被过滤掉。
    """

    def text(self):
        t = self.currentText()
        return "" if t == GROUP_REFRESH_MARK else t

    def setText(self, value):
        self.setCurrentText(str(value or ""))


class AutostartTab(SettingsTab):
    """定时启动：到点自动拉起外部程序（默认 BetterGI），并可自动开始/停止监测。

    移植自用户自己的 `E:\\开门助手`（界面风格照本项目设置页重做，逻辑走
    `svc_autostart`）。**实打实修掉了原工具的一个 bug**：排除日期原来没生效
    （见 `svc_autostart.build_bat_text` 的说明）。

    ⚠ 本页只是**拉起用户指定的第三方程序**（默认 BetterGI 的配置组），
      主程序自己不注入、不读游戏内存、不模拟键鼠。目标程序路径由用户填。
    """

    def __init__(self, parent, cfg, alpha, win):
        super().__init__(parent, cfg, alpha)
        self._win = win
        self._c = svc_autostart.cfg(self.cfg.raw)
        # 模块界面统一在公共设置创建完成后加载一次，避免 BGI 重复建卡。
        self._mod_ui_list = []   # 模块界面登记表（置顶用，通用）
        self._module_ui = {}
        self._busy = False

        # ---------- ① 总开关 ----------
        self.switch_on = Switch(self, bool(self._c.get("enabled", False)))
        self.switch_on.toggled.connect(bind_cb(self._on_enabled))
        self.row_on = self.row(
            "clock", "启用定时任务",
            "按计划执行已启用模块；停用后移除系统任务",
            self.switch_on,
                 tip="启用并保存后创建 Windows 计划任务。\n停用并保存后移除计划任务。\n创建或移除任务需要管理员权限。")

        # ★ 2026-10-13 用户要求：放在「启用自动运行」**正下方**，
        #   每天是否把 StatGI 自己拉起来，由用户自己决定 ✓
        self.switch_self = Switch(self, bool(self._c.get("start_self", True)))
        self.switch_self.toggled.connect(bind_cb(self._on_behavior))
        self.row_self = self.row(
            "power", "自动启动 StatGI",
            "任务执行时启动 StatGI；已运行时激活现有窗口",
            self.switch_self,
            tip="启用：任务执行时启动 StatGI。\n"
                "停用：仅执行模块动作。\n"
                "程序已运行时仅激活现有窗口。")

        # ---------- ② 时间 ----------
        self.time_entry = QLineEdit(str(self._c.get("time", "03:58")))
        self.time_entry.setFixedWidth(90)
        self.time_entry.setAlignment(Qt.AlignCenter)
        self.time_entry.setStyleSheet(entry_qss())
        self.time_entry.editingFinished.connect(bind_cb(self._on_time))
        self.row("timer", "执行时间",
                 "每日任务执行时间",
                 self.time_entry,
                 tip="格式：HH:MM，例如 03:58。\n修改后点击“保存并应用”。")

        # ---------- ③ 星期几 ----------
        # 用户 2026-10-12：「原来那排勾选框太丑了」→ 改成**胶囊按钮**（选中＝强调色实底）。
        # 跟「每日收益」页上面那两个切换按钮、以及设置页的标签栏是同一种观感。
        # ⚠ 仍然用 `setCheckable(True)`，所以 `isChecked()/setChecked()` 照旧能用
        #   （测试和别的代码不用改）。
        self.wd_boxes = []
        wd_wrap = QWidget()
        wd_wrap.setStyleSheet("background: transparent;")
        wd_lay = QHBoxLayout(wd_wrap)
        wd_lay.setContentsMargins(0, 0, 0, 0)
        wd_lay.setSpacing(6)
        for i, name in enumerate(svc_autostart.WEEKDAY_NAMES):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(bool(self._c["weekdays"][i]))
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(30)
            # ⚠ 宽度要能**压**：最小 38px（两个字够用），窗口宽了就自动变宽。
            #   写死 52 的话，窗口缩到最小（760）时整行最小宽度会超过可视区，
            #   右边那个「周日」就被裁掉了（量出来卡片 707 > 可视区 526）。
            b.setMinimumWidth(38)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.toggled.connect(bind_cb(self._on_weekdays))
            self._style_day(b)
            wd_lay.addWidget(b, 1)
            self.wd_boxes.append(b)
        self.row_day = self.row(
            "calendar", "运行日期", self._weekdays_desc(), wd_wrap,
            tip="选中日期表示执行。\n修改后点击“保存并应用”。")

        # ---------- ④ 排除日期（折叠 + **可加可删的行**，跟配置组一个形式）----------
        # 用户 2026-10-12：跟「连续执行哪几个配置组」一样能添加/删除，
        # 不要那个又大又空的多行框（难看）。
        ex_body = QWidget()
        ex_body.setStyleSheet("background: transparent;")
        ex_bl = QVBoxLayout(ex_body)
        ex_bl.setContentsMargins(0, 0, 0, 0)
        ex_bl.setSpacing(6)
        self._date_rows = []          # [(行控件, 输入框, 序号标签), ...]
        self.dates_lay = QVBoxLayout()
        self.dates_lay.setContentsMargins(0, 0, 0, 0)
        self.dates_lay.setSpacing(6)
        ex_bl.addLayout(self.dates_lay)
        self.b_add_date = small_button("添加日期", self._add_date_clicked,
                                       self.alpha, icon="plus", width=124)
        # ⚠ 不设成 Fixed 的话 QVBoxLayout 会把它拉成整条宽（896px 的大横条，
        #   跟"小按钮"的观感完全不搭）。Fixed = 只占它自己的自然宽度。
        self.b_add_date.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        ex_bl.addWidget(self.b_add_date, 0, Qt.AlignLeft)
        self.excl_acc = Accordion(
            self, "x", "排除日期", self._excl_desc(),
            body_widget=ex_body, alpha=self.alpha,
            tip="排除日期优先于运行日期。\n点击“添加日期”选择日期，点击删除按钮移除。\n支持格式：2026-10-01、2026/10/01、20261001。")
        self.add_card(self.excl_acc)
        for d in (self._c.get("exclude_dates") or []):
            self._add_date_row(d)
        # ⚠ 不再"没填就补一行空位" —— 用户要能**全删光**（见 _remove_date_row）
        self._sync_excl_desc()

        # ---------- ⑤ 连续执行配置组：把 BGI 里的组**全列出来，勾选** ----------
        # 用户 2026-10-13：不要下拉、不要手输 —— 探测到 BGI 之后，
        # 把它调度器里的组**全部显示出来**，我自己勾要跑哪几个。
        g_body = QWidget()
        g_body.setStyleSheet("background: transparent;")
        g_bl = QVBoxLayout(g_body)
        g_bl.setContentsMargins(0, 0, 0, 0)
        g_bl.setSpacing(6)
        # ---------- ⑥ 更多设置（路径等）----------
        self.switch_wake = Switch(self, bool(self._c.get("wake_to_run", False)))
        self.switch_wake.toggled.connect(bind_cb(self._on_behavior))
        self.row_wake = self.row("power", "睡眠唤醒",
                 "睡眠状态下唤醒执行",
                 self.switch_wake,
                 tip="启用 WakeToRun，在睡眠状态唤醒执行。\n电池供电时可能增加耗电。")

        # 模块设置由 modules/<key>/ui.py 提供；公共页只放通用的调度项。
        try:
            import modules as _registry
            for _mod in _registry.load_all():
                _res = self._build_module_ui(_mod["key"])
                if _res:
                    self._module_ui[_mod["key"]] = _res
        except Exception as _exc:
            print("[模块界面] 加载模块列表失败：", _exc, flush=True)
        self._reorder_tail()
        self._apply_module_visibility()
        self._reregister_modules()

        # 状态概览和常用操作；低频工具单独折叠，避免横向拥挤。
        st = Card(self, alpha=self.alpha)
        self.st_card = st
        stv = QVBoxLayout(st)
        stv.setContentsMargins(16, 16, 16, 16)
        stv.setSpacing(12)
        header = QHBoxLayout()
        self.st_title = QLabel("任务状态")
        self.st_title.setStyleSheet(label_qss(T.TEXT, 14, True))
        header.addWidget(self.st_title)
        header.addStretch(1)
        self.st_badge = QLabel("")
        header.addWidget(self.st_badge)
        stv.addLayout(header)
        self.st_next = QLabel("")
        self.st_next.setWordWrap(True)
        self.st_next.setStyleSheet(label_qss(T.TEXT, 16, True))
        stv.addWidget(self.st_next)
        self.st_label = QLabel("")
        self.st_label.setWordWrap(True)
        self.st_label.setStyleSheet(label_qss(T.DIM, 12))
        stv.addWidget(self.st_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.b_apply = QPushButton("保存并应用")
        self.b_apply.setFixedHeight(36)
        self.b_apply.setCursor(Qt.PointingHandCursor)
        self.b_apply.setStyleSheet(btn_qss("accent", self.alpha))
        self.b_apply.clicked.connect(bind_cb(self._apply))
        btn_row.addWidget(self.b_apply, 1)
        run_button = QPushButton("立即执行")
        run_button.setFixedHeight(36)
        run_button.setCursor(Qt.PointingHandCursor)
        run_button.setStyleSheet(btn_qss("normal", self.alpha))
        run_button.clicked.connect(bind_cb(self._run_once))
        btn_row.addWidget(run_button, 1)
        stv.addLayout(btn_row)
        self.log_label = QLabel("")
        self.log_label.setWordWrap(True)
        self.log_label.setStyleSheet(label_qss(T.DIM, 11))
        self.log_label.hide()
        stv.addWidget(self.log_label)
        self.add_card(st)

        tools_body = QWidget()
        tools_body.setStyleSheet("background: transparent;")
        tools_layout = QVBoxLayout(tools_body)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(14)

        def add_tool_group(title, actions):
            label = QLabel(title)
            label.setStyleSheet(label_qss(T.DIM, 12, True))
            tools_layout.addWidget(label)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            for index, (text, callback) in enumerate(actions):
                button = QPushButton(text)
                button.setFixedHeight(34)
                button.setCursor(Qt.PointingHandCursor)
                button.setStyleSheet(btn_qss("normal", self.alpha))
                button.clicked.connect(bind_cb(callback))
                grid.addWidget(button, index // 2, index % 2)
            tools_layout.addLayout(grid)

        add_tool_group("模块管理", [
            ("打开模块目录", self._open_dir),
            ("模块仓库", self._module_repo_dialog),
            ("添加模块", self._add_module_dialog),
            ("卸载模块", self._uninstall_module_dialog),
        ])
        tool_actions = [("查看命令", self._show_cmd)]
        try:
            import modules as _registry
            for _module in _registry.load_all():
                _ui = _registry.load_ui(_module["key"])
                if _ui and hasattr(_ui, "module_tools"):
                    tool_actions.extend(_ui.module_tools(self))
        except Exception as _exc:
            print("[模块工具] 加载失败：", _exc, flush=True)
        add_tool_group("运行工具", tool_actions)
        self.tools_card = Accordion(
            self, "settings", "模块与工具", "模块目录、仓库、导入、卸载及命令查看",
            body_widget=tools_body, alpha=self.alpha)
        self.add_card(self.tools_card)
        self._reorder_tail()

        self._refresh_state()
        self._sync_desc()

    # ------------------------------------------------------------ 星期几 / 排除日期
    def _style_day(self, b):
        """星期几那块胶囊按钮：选中＝强调色实底，未选＝普通描边"""
        try:
            b.setStyleSheet(btn_qss("accent" if b.isChecked() else "normal",
                                    self.alpha))
        except Exception:
            pass

    def _weekdays_desc(self):
        """「哪几天运行」那行的说明 —— **必须极短**。

        用户 2026-10-12：写成"运行日：周一、周二、…、周日"会把右边那排
        胶囊按钮挤掉。所以这里最多就几个字：具体哪几天**看按钮本身**（点亮的
        就是会跑的那几天），说明只回答"一共几天 / 有没有选"。
        """
        on = [svc_autostart.WEEKDAY_NAMES[i]
              for i, b in enumerate(self.wd_boxes) if b.isChecked()]
        if len(on) == 7:
            return "每日"
        if not on:
            return "未选择日期"
        if len(on) <= 2:
            return "、".join(on)              # 一两个就把名字写出来（很短）
        return f"每周 {len(on)} 天"

    def _excl_desc(self):
        n = len(self._c.get("exclude_dates") or [])
        if not n:
            return "未设置"
        ds = self._c["exclude_dates"]
        head = "、".join(ds[:4]) + ("…" if len(ds) > 4 else "")
        return f"{n} 个日期：{head}"

    # ------------------------------------------------------------ 可加可删的行
    # 「配置组」和「跳过日期」长得一样（序号 + 输入框 + 垃圾桶 + 底部添加按钮），
    # 所以只有一份实现 —— 两处各写一遍迟早长歪。
    MAX_GROUPS = 12                   # 配置组上限（再多 BGI 命令行也太长了）
    MAX_DATES = 30                    # 跳过日期上限

    def _dyn_row(self, layout, rows, value, placeholder, on_change, on_remove,
                 max_rows=0, mode="text", on_click=None,
                 items=None, on_refresh=None):
        """往 `layout` 里加一行：序号 + 输入框 + 垃圾桶。返回控件。

        `mode="text"`：普通输入框（配置组用）
        `mode="date"`：**只读的日期按钮**，点一下弹日历（跳过日期用）——
                       用户 2026-10-12：不许手输，点出来选。
        """
        if max_rows and len(rows) >= max_rows:
            return None
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        num = QLabel(str(len(rows) + 1))
        num.setFixedWidth(18)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet(label_qss(T.DIM, 11))
        if mode == "group":
            # 下拉（可编辑）：列出 BGI 里真实存在的组名，最后一项是「刷新」
            entry = GroupCombo()
            entry.setEditable(True)
            entry.setInsertPolicy(QComboBox.NoInsert)
            entry.setStyleSheet(combo_qss())
            entry.setMinimumWidth(150)
            entry.setMaximumWidth(260)
            entry.addItem(str(value) if value else "")
            for nm in (items or []):
                if nm and nm != value:
                    entry.addItem(nm)
            if items:
                entry.addItem(self.GROUP_REFRESH)
            entry.setCurrentText(str(value) if value else "")
            entry.activated.connect(bind_cb(self._on_groups))  # 配置组已改成勾选框，这里只兜底
            entry.lineEdit().editingFinished.connect(bind_cb(on_change))
        elif mode == "date":
            entry = QPushButton(str(value) or self.DATE_HINT)
            entry.setCursor(Qt.PointingHandCursor)
            entry.setMinimumWidth(180)
            entry.setFixedHeight(30)
            entry.setStyleSheet(
                f"QPushButton {{ background:{rgba('#FFFFFF', 14)}; color:{T.TEXT};"
                f" border:1px solid {rgba('#FFFFFF', 30)}; border-radius:8px;"
                f" padding:2px 10px; text-align:left; font-size:12px; }}"
                f"QPushButton:hover {{ border:1px solid {T.ACCENT}; }}")
            entry.clicked.connect(bind_cb(on_click or on_change, w))
        else:
            entry = QLineEdit(str(value))
            entry.setStyleSheet(entry_qss())
            entry.setMinimumWidth(180)
            entry.setPlaceholderText(placeholder)
            entry.editingFinished.connect(bind_cb(on_change))
        del_btn = small_button("", bind_cb(on_remove, w), self.alpha,
                               icon="trash", kind="danger", width=34)
        lay.addWidget(num)
        lay.addWidget(entry, 1)
        lay.addWidget(del_btn)
        layout.addWidget(w)
        rows.append((w, entry, num))
        return entry

    def _drop_dyn_row(self, rows, w):
        """删掉某一行，并给剩下的重新编号"""
        keep = []
        for row in rows:
            if row[0] is w:
                row[0].setParent(None)
                try:
                    row[0].deleteLater()
                except Exception:
                    pass
            else:
                keep.append(row)
        rows[:] = keep
        for i, (_w, _e, num) in enumerate(rows, 1):
            num.setText(str(i))

    # ------------------------------------------------------------ 模块界面注册
    def _module_installed(self, key):
        """通用 UI 辅助：注册表中是否有这个模块。"""
        try:
            import svc_autostart as _A
            return bool(_A.module_installed(key))
        except Exception:
            return True

    def _register_module_ui(self, key, res):
        """模块交回来的界面登记一下。

        约定：模块的 ui.py 里 build(tab) 返回
            {"key": ..., "card": 开关那张卡片, "box": 选项区, "switch": 开关}
        置顶功能只认 (card, box)，**不认具体是哪个模块** ✓
        """
        if not res:
            return
        card = res.get("card") or res.get("switch")
        box = res.get("box")
        if card is None or box is None:
            return
        if not hasattr(self, "_mod_ui_list"):
            self._mod_ui_list = []
        self._mod_ui_list.append((card, box))
        self._mod_ui_seen = getattr(self, "_mod_ui_seen", set())
        self._mod_ui_seen.add(key)

    def _build_module_ui(self, key):
        """按模块名搭它的界面（没有 ui.py 就算了）—— 通用，不写死任何模块。"""
        try:
            import modules as _mods
            ui = _mods.load_ui(key)
            if ui is None:
                return None
            # 所有模块开关使用同一入口；模块无需在主页面注册专属回调。
            if hasattr(ui, "toggle"):
                try:
                    ui.bind_toggle(self)
                except AttributeError:
                    pass
            res = ui.build(self)
            self._register_module_ui(key, res)
            return res
        except Exception as _e:
            import traceback
            print("[模块界面] 构建失败：", key, type(_e).__name__, _e, flush=True)
            traceback.print_exc()
            return None


    def _reregister_modules(self):
        """兜底登记：界面全建好后再登记一遍（修"BGI 置顶没了"）✓

        BGI 的界面建得早，登记时它的"选项区"还没准备好 → 置顶登记里少了 BGI ✗；
        这里在最后按约定（row_xxx_mod + xxx_box）再登记一次 ✓，重复的跳过 ✓。
        """
        lst = getattr(self, "_mod_ui_list", None)
        if lst is None:
            return
        have = {id(c) for c, _b in lst}
        for k, res in getattr(self, "_module_ui", {}).items():
            card, box = res.get("card"), res.get("box")
            if card is None or box is None or id(card) in have:
                continue
            lst.append((card, box))
            print("[置顶] 兜底登记:", k, flush=True)
        self._sticky_refresh()

    def setup_sticky_cards(self, scroll):
        """把滚动区交给置顶功能（PageAutostart 建好页面后调一次）"""
        try:
            import qt_sticky
            self._sticky = qt_sticky.StickyCardHeader(
                scroll, lambda: list(getattr(self, "_mod_ui_list", [])))
            self._sticky.update()
        except Exception:
            self._sticky = None

    def _sticky_refresh(self):
        try:
            if getattr(self, "_sticky", None) is not None:
                self._sticky.update()
        except Exception:
            pass

    # ------------------------------------------------------------ 跳过日期
    DATE_HINT = "选择日期"

    def _add_date_row(self, value=""):
        if len(self._date_rows) >= self.MAX_DATES:
            self._log(f"跳过日期最多 {self.MAX_DATES} 个。")
            return None
        return self._dyn_row(self.dates_lay, self._date_rows,
                             value or "",
                             "选择日期",
                             self._on_dates,
                             lambda w: self._remove_date_row(w),
                             max_rows=self.MAX_DATES,
                             mode="date",
                             on_click=self._pick_date)

    def _pick_date(self, w):
        """点日期行 → 弹日历选一个（用户要求：不能手输）"""
        import datetime as _dt
        from qt_dlg_calendar import CalendarDialog
        cur = None
        for (rw, e, _n) in self._date_rows:
            if rw is w:
                try:
                    cur = _dt.date.fromisoformat(e.text().strip())
                except Exception:
                    cur = None
                break
        dlg = CalendarDialog(self._win, self.alpha, date=cur)
        if dlg.exec() == QDialog.Accepted:
            for (rw, e, _n) in self._date_rows:
                if rw is w:
                    e.setText(dlg.selected_text())
                    break
        self._on_dates()

    def _add_date_clicked(self):
        if self._add_date_row(""):
            self._on_dates()

    def _remove_date_row(self, w):
        # 同上：能全删光（全删光 = 不跳过任何日期）
        self._drop_dyn_row(self._date_rows, w)
        self._on_dates()

    def _date_values(self):
        """行里填的日期（规范化 + 过滤看不懂的）。返回 (合法, 非法)

        ⚠ 日期行现在是**只读按钮**（点开弹日历），所以除了真实日期就只有
          `DATE_HINT` 这个占位字 —— 它要当"没填"处理，不能报成非法。
        """
        raw = []
        for (_w, e, _n) in self._date_rows:
            t = e.text().strip()
            if t and t != self.DATE_HINT:
                raw.append(t)
        return svc_autostart.parse_exclude_dates(raw)

    def _sync_excl_desc(self):
        try:
            self.excl_acc.desc_label.setText(self._excl_desc())
        except Exception:
            pass

    # ------------------------------------------------------------ 直播
    def _on_module_config_changed(self, key):
        """模块设置发生变化：公共页只保存通用配置、刷新状态和调用模块摘要。"""
        self._collect()
        self._save()
        result = getattr(self, "_module_ui", {}).get(key)
        if result:
            try:
                import modules as _registry
                ui = _registry.load_ui(key)
                if ui is not None and hasattr(ui, "desc"):
                    result["card"].set_text(desc=ui.desc(self))
            except Exception:
                pass
        self._refresh_state()

    # ------------------------------------------------------------ 模块
    def _reorder_tail(self):
        """通用调度设置在前，每个模块的开关与选项相邻，状态和工具在末尾。"""
        order = [getattr(self, "row_wake", None)]
        for res in getattr(self, "_module_ui", {}).values():
            order.extend(w for w in (res.get("card"), res.get("box"))
                         if w is not None)
        order.extend((getattr(self, "st_card", None),
                      getattr(self, "tools_card", None)))
        order = [w for w in order if w is not None]
        for w in order:
            self.v.removeWidget(w)
        base = self.v.indexOf(self.excl_acc) + 1
        for i, w in enumerate(order):
            self.v.insertWidget(base + i, w)

    def _apply_module_visibility(self):
        """让各模块根据自己的规则设置卡片、选项区的显示状态。"""
        try:
            import modules as _registry
            for _mod in _registry.load_all():
                _ui = _registry.load_ui(_mod["key"])
                if _ui is not None and hasattr(_ui, "apply"):
                    _ui.apply(self, bool((self._c.get("modules") or {}).get(
                        _mod["key"], True)))
        except Exception as _exc:
            print("[模块界面] 更新显隐失败：", _exc, flush=True)
        self._sticky_refresh()

    def _uninstall_module_dialog(self, *_a):
        """页尾「卸载模块」：列出已安装的模块，点一下卸载"""
        from qt_dlg_card import CardDialog
        dlg = CardDialog(self._win, self.alpha, title="卸载模块", width=360)
        dlg.set_subtitle("已安装的模块")
        any_mod = False
        for m in svc_autostart._load_modules():
            if not svc_autostart.mod_on(self._c, m["key"]):
                continue
            any_mod = True
            row = QLabel(f"<b>{m['name']}</b><br>{m['desc']}")
            row.setWordWrap(True)
            row.setStyleSheet(label_qss(T.TEXT, 12))
            dlg.add_widget(row)
            if m["builtin"]:
                note = QLabel("内置模块，只能在上方卡片里开关，不能卸载")
                note.setStyleSheet(label_qss(T.DIM, 11))
                dlg.add_widget(note)
                continue
            else:
                b = small_button(f"卸载{m['name']}", self._uninstall_from_dialog,
                                 self.alpha, icon="trash", kind="danger",
                                 width=120)
                b.clicked.connect(bind_cb(self._uninstall_from_dialog,
                                          m["key"]))
                dlg.add_widget(b)
        # 自己导入的模块也能在这里卸（文件保留，可以再装回来）
        import svc_modules
        exts = [m for m in svc_modules.external_modules()
                if (self._c.get("external_on") or {}).get(m["key"])]
        if exts:
            any_mod = True
            head = QLabel("<b>已导入的模块</b>")
            head.setStyleSheet(label_qss(T.TEXT, 12))
            dlg.add_widget(head)
            for m in exts:
                row = QLabel(f"<b>{m['name']}</b><br>{len(m['actions'])} 个动作")
                row.setWordWrap(True)
                row.setStyleSheet(label_qss(T.TEXT, 12))
                dlg.add_widget(row)
                b = small_button(f"停用{m['name']}", self._install_module,
                                 self.alpha, icon="trash", kind="danger",
                                 width=120)
                b.clicked.connect(bind_cb(self._install_module, m["key"], False))
                dlg.add_widget(b)
                b2 = small_button(f"彻底删除{m['name']}", self._delete_module_file,
                                  self.alpha, icon="trash", kind="danger",
                                  width=140)
                b2.clicked.connect(bind_cb(self._delete_module_file, m["key"]))
                dlg.add_widget(b2)
        if not any_mod:
            lbl = QLabel("现在没有装任何可卸载的模块。")
            lbl.setStyleSheet(label_qss(T.DIM, 12))
            dlg.add_widget(lbl)
        dlg.add_confirm("知道了")
        dlg.exec()

    def _uninstall_from_dialog(self, key, *_a):
        self._do_uninstall_module(key)

    def _on_module_toggle(self, key, on):
        self._c.setdefault("modules", {})[key] = bool(on)
        _ui = None
        try:
            import modules as _registry
            _ui = _registry.load_ui(key)
        except Exception:
            pass
        if _ui is not None and hasattr(_ui, "toggle"):
            try:
                _ui.toggle(self, bool(on))
                return
            except Exception as _exc:
                print("[模块开关] 模块回调失败：", key, _exc, flush=True)
        self._collect()
        self._apply_module_visibility()
        self._save()
        self._refresh_state()
        self._log(f"{svc_autostart.module_info(key)['name']}："
                  f"{'已启用' if on else '已停用'}")

    def _module_repo_dialog(self, *_a):
        """「模块仓库」：浏览 / 下载 / 安装别人做好的模块（Gitee+GitHub 双源）"""
        try:
            import qt_module_repo
            dlg = qt_module_repo.ModuleRepoDialog(self._win or self, self.alpha)
            dlg.exec()
            self._log("已打开模块仓库。")
        except Exception as e:
            self._log(f"模块仓库打不开：{type(e).__name__}: {e}")

    def _add_module_dialog(self, *_a):
        """「添加模块」：列出所有可用模块，没装的可以直接装。

        以后新增模块只要往 `svc_autostart.MODULES` 加一条，这里自动出现。
        """
        from qt_dlg_card import CardDialog
        import svc_modules
        dlg = CardDialog(self._win, self.alpha, title="添加模块", width=380)
        dlg.set_subtitle("可用模块列表")
        for m in svc_autostart._load_modules():
            # ⚠ 内置模块**不是"未安装"** —— 它一直就在，只是开关可能关着。
            #   之前这里写"未安装"还给了安装按钮，用户看到「BetterGI 模块 未安装」
            #   一头雾水（2026-10-13 反馈）。
            if m["builtin"]:
                state = "已启用" if svc_autostart.mod_on(self._c, m["key"]) \
                    else "内置 · 已停用"
                row = QLabel(f"<b>{m['name']}　内置</b><br>{m['desc']}<br>{state}")
                row.setWordWrap(True)
                row.setStyleSheet(label_qss(T.TEXT, 12))
                dlg.add_widget(row)
                continue
            on = svc_autostart.mod_on(self._c, m["key"])
            row = QLabel(f"<b>{m['name']}　"
                         f"{'已启用' if on else '已停用'}</b><br>{m['desc']}")
            row.setWordWrap(True)
            row.setStyleSheet(label_qss(T.TEXT, 12))
            dlg.add_widget(row)
            b = small_button(f"{'停用' if on else '启用'}{m['name']}",
                             self._install_module, self.alpha,
                             icon="toggle-right" if on else "toggle-left",
                             width=120)
            b.clicked.connect(bind_cb(self._install_module, m["key"], not on))
            dlg.add_widget(b)
        # 外部导入的模块
        exts = svc_modules.external_modules()
        if exts:
            head = QLabel("<b>已导入的模块</b>")
            head.setStyleSheet(label_qss(T.TEXT, 12))
            dlg.add_widget(head)
            for m in exts:
                on = bool((self._c.get("external_on") or {}).get(m["key"]))
                row = QLabel(f"<b>{m['name']}　"
                             f"{'已安装' if on else '未安装'}</b><br>"
                             f"{m['desc'] or '（没有说明）'}"
                             f"<br>{len(m['actions'])} 个动作")
                row.setWordWrap(True)
                row.setStyleSheet(label_qss(T.TEXT, 12))
                dlg.add_widget(row)
                if not on:
                    b = small_button(f"安装{m['name']}", self._install_module,
                                     self.alpha, icon="plus", width=120)
                    b.clicked.connect(bind_cb(self._install_module, m["key"], True))
                    dlg.add_widget(b)
        b_imp = small_button("导入模块…", self._import_module_clicked,
                             self.alpha, icon="plus", width=120)
        dlg.add_widget(b_imp)
        note = QLabel("模块文件格式为 `.sgmod.json`，仅包含程序启动或网址打开动作，不包含代码。\n"
                      "点击“导入模块”选择文件。")
        note.setWordWrap(True)
        note.setStyleSheet(label_qss(T.DIM, 11))
        dlg.add_widget(note)
        dlg.add_confirm("知道了")
        dlg.exec()

    def _import_module_clicked(self, *_a):
        """导入一个 .sgmod.json 模块文件"""
        import svc_modules
        p, _ = QFileDialog.getOpenFileName(
            self._win, "选择模块文件", "",
            f"StatGI 模块 (*{svc_modules.MODULE_SUFFIX});;JSON (*.json)")
        if not p:
            return
        try:
            info, msg = svc_modules.import_module_file(p)
        except Exception as e:
            self._log(f"导入失败：{e}")
            return
        self._c.setdefault("external_on", {})[info["key"]] = True
        self._save()
        self._log(msg + "。保存并应用后生效。")

    def _delete_module_file(self, key, *_a):
        """彻底删除一个外部模块文件"""
        import svc_modules
        ok = svc_modules.remove_module_file(key)
        self._c.setdefault("external_on", {}).pop(key, None)
        self._save()
        self._log("模块文件已删除。" if ok else "删除失败，文件可能已不存在。")

    def _install_module(self, key, on=True, *_a):
        """启用或停用一个模块；具体配置由模块自己的 UI 管理。"""
        if str(key).startswith("ext:"):
            self._c.setdefault("external_on", {})[key] = bool(on)
            self._save()
            self._log(f"外部模块：{'已启用' if on else '已停用'}")
            return
        self._c.setdefault("modules", {})[key] = bool(on)
        try:
            import modules as _registry
            ui = _registry.load_ui(key)
            if ui is not None and hasattr(ui, "toggle"):
                ui.toggle(self, bool(on))
                return
        except Exception as exc:
            print("[模块开关] 模块安装回调失败：", key, exc, flush=True)
        self._save()
        self._apply_module_visibility()
        self._refresh_state()
        info = svc_autostart.module_info(key) or {"name": key}
        self._log(f"{info['name']}：{'已启用' if on else '已停用'}")

    def _do_uninstall_module(self, key):
        """停用模块并清除它自己的配置；内置模块只能停用、不能删除文件。"""
        info = svc_autostart.module_info(key)
        if not info:
            self._log("模块不存在或已移除。")
            return
        if info.get("builtin"):
            self._c.setdefault("modules", {})[key] = False
            self._collect()
            self._save()
            self._apply_module_visibility()
            self._refresh_state()
            self._log(f"{info['name']}为内置模块，已停用，无法卸载。")
            return
        self._c.setdefault("modules", {})[key] = False
        result = getattr(self, "_module_ui", {}).get(key) or {}
        switch = result.get("switch")
        if switch is not None:
            switch.blockSignals(True)
            switch.setChecked(False)
            switch.blockSignals(False)
        try:
            import modules as _registry
            ui = _registry.load_ui(key)
            if ui is not None and hasattr(ui, "reset"):
                ui.reset(self, self._c)
        except Exception as exc:
            self._log(f"模块清理配置失败：{type(exc).__name__}: {exc}")
        self._save()
        self._apply_module_visibility()
        self._log(f"{info['name']}：已卸载（相关配置已清空，"
                  f"可通过“添加模块”重新导入。）")

    # ------------------------------------------------------------ 小工具
    def _log(self, text):
        self.log_label.setText(str(text))
        self.log_label.setVisible(bool(text))

    def _side_effect_note(self):
        if not svc_autostart.is_admin():
            return "保存时请求管理员权限"
        return "管理员权限已获取"

    def _refresh_state(self):
        c = self._c
        nr = svc_autostart.next_run(c) if c.get("enabled") else None
        info = svc_autostart.query_task(c.get("task_name") or svc_autostart.DEFAULT_TASK)
        head = "已启用" if c.get("enabled") else "未启用"
        days = "".join("一二三四五六日"[i]
                       for i in svc_autostart.active_weekdays(c))
        self.st_badge.setText(head)
        color = T.ACCENT if c.get("enabled") else T.DIM
        self.st_badge.setStyleSheet(
            f"QLabel {{ color:{color}; background:{rgba(color, 24)};"
            " border-radius:9px; padding:4px 10px; font-size:12px; }")
        self.st_next.setText(
            "下次执行：" + (nr.strftime("%m月%d日 %H:%M") if nr else "未安排"))
        lines = [f"执行时间：{c.get('time')}　·　运行日期：{days or '未选择'}",
                 f"系统任务：{'已创建' if info['exists'] else '未创建'}"]
        if info.get("last_run"):
            lines.append(f"上次执行：{info['last_run']}")
        if svc_autostart.skipped_today(c):
            lines.append("今日为排除日期")
        lines.append(self._side_effect_note())
        self.st_label.setText("\n".join(lines))
        self.b_apply.setEnabled(not self._busy)

    def _sync_desc(self):
        """把当前状态写进「启用自动运行」那一行的说明里

        ⚠ 这里的文案跟 `__init__` 里建行时那句**必须一致** —— 建完行马上会调
          本方法覆盖一次，两边不一致的话界面上看到的是这里的版本
          （踩过：改了建行的文案，界面还是老话）。
        """
        try:
            c = self._c
            if not c.get("enabled"):
                txt = "按计划执行已启用模块；停用后移除计划任务"
            else:
                nr = svc_autostart.next_run(c)
                txt = (f"每日 {c.get('time')} 执行"
                       + (f"，下次 {nr.strftime('%m-%d %H:%M')}" if nr else "")
                       + "；停用后移除计划任务")
            self.row_on.set_text(desc=txt)
        except Exception:
            pass

    # ------------------------------------------------------------ 收集 & 保存
    def _collect(self):
        """把界面上的值收进 self._c（不落盘）"""
        self._c["enabled"] = bool(self.switch_on.isChecked())
        self._c["time"] = (self.time_entry.text() or "").strip()
        self._c["weekdays"] = [bool(cb.isChecked()) for cb in self.wd_boxes]
        self._c["wake_to_run"] = bool(self.switch_wake.isChecked())
        # 模块专属设置由各自的 ui.collect() 管理，不在公共页面维护字段细节。
        try:
            import modules as _registry
            module_states = {}
            for _mod in _registry.load_all():
                _ui = _registry.load_ui(_mod["key"])
                if _ui is not None and hasattr(_ui, "collect"):
                    collected = _ui.collect(self, self._c)
                    if isinstance(collected, dict):
                        self._c.update(collected)
                _res = getattr(self, "_module_ui", {}).get(_mod["key"])
                _switch = (_res or {}).get("switch")
                if _switch is not None:
                    module_states[_mod["key"]] = bool(_switch.isChecked())
            self._c["modules"] = module_states
        except Exception as _exc:
            print("[模块配置] 收集模块设置失败：", _exc, flush=True)
        good, bad = self._date_values()
        self._c["exclude_dates"] = good
        return bad

    def _save(self):
        self.cfg.set("autostart", dict(self._c))

    def _apply(self):
        """保存 → 写 bat → 建/删任务 → 刷新状态（会弹一次 UAC 建任务）"""
        bad = self._collect()
        if svc_autostart.parse_time(self._c["time"]) is None:
            self._log("时间格式无效（应为 HH:MM），已恢复原值。")
            self._c["time"] = svc_autostart.DEFAULT["time"]
            self.time_entry.setText(self._c["time"])
        if not svc_autostart.active_weekdays(self._c):
            self._log("未选择运行日期，任务不会执行。")
            return
        self._save()
        if bad:
            self._log(f"以下日期格式无效，已忽略：{'、'.join(bad)}")
        # 定时服务不验证任何具体模块字段，由模块自行决定是否提供动作。
        if self._c["enabled"] and not svc_autostart.live_steps(self._c):
            self._log("没有可执行模块，请检查模块设置。")
            return

        self._busy = True
        self._refresh_state()
        try:
            bat = svc_autostart.write_bat(self._c)
            self._log(f"执行脚本已生成：{bat.name}")
            QApplication.processEvents()
            name = self._c.get("task_name") or svc_autostart.DEFAULT_TASK
            if self._c["enabled"]:
                ok, msg = svc_autostart.create_task(self._c, bat)
            else:
                ok, msg = svc_autostart.delete_task(name)
            self._log(msg + ("　✓" if ok else "　✗"))
        except Exception as e:
            self._log(f"操作失败：{type(e).__name__}: {e}")
        finally:
            self._busy = False
            self._refresh_state()
            self._sync_desc()

    # ------------------------------------------------------------ 各控件回调
    def _on_enabled(self, *_a):
        # ⚠ 参数别指望信号传进来：这些回调统一用 `bind_cb` 包的，
        #   它会把信号参数吃掉（`bind_cb` = lambda *a: fn(*args)）。
        #   所以一律**从控件读状态**，不要 `def _on_enabled(self, v)`。
        self._c["enabled"] = bool(self.switch_on.isChecked())
        self._sync_desc()
        self._refresh_state()

    def _on_time(self):
        t = (self.time_entry.text() or "").strip()
        if svc_autostart.parse_time(t) is None:
            self._log("时间格式无效（应为 HH:MM），已恢复原值。")
            self.time_entry.setText(str(self._c.get("time", "03:58")))
        else:
            self._c["time"] = t
        self._refresh_state()

    def _on_weekdays(self, *_a):
        self._c["weekdays"] = [bool(b.isChecked()) for b in self.wd_boxes]
        for b in self.wd_boxes:          # 胶囊按钮要跟着重画（选中态换了）
            self._style_day(b)
        try:
            self.row_day.set_text(desc=self._weekdays_desc())
        except Exception:
            pass
        self._refresh_state()

    def _on_dates(self):
        """跳过日期那一行改完 —— 校验 + 更新折叠区说明"""
        good, bad = self._date_values()
        self._c["exclude_dates"] = good
        if bad:
            self._log(f"以下日期格式无效，已忽略：{'、'.join(bad)}")
        else:
            n = len(good)
            self._log(f"排除日期：{n} 个（保存后生效）" if n else "排除日期：无")
        self._sync_excl_desc()
        self._refresh_state()

    def _on_behavior(self, *_a):
        self._collect()

    def _on_monitor(self, *_a):
        self._collect()
        self._save()

    def _run_once(self):
        self._collect()
        ok, msg = svc_autostart.launch_target(self._c)
        self._log(msg)

    def _show_cmd(self):
        self._collect()
        try:
            text = svc_autostart.build_bat_text(self._c)
        except Exception as e:
            self._log(f"生成命令失败：{e}")
            return
        dlg = CardDialog(self._win, self.alpha, title="将要执行的命令", width=460)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(label_qss(T.TEXT, 11))
        dlg.add_widget(lab)
        dlg.add_confirm("知道了")
        dlg.exec()

    def _modules_dir_for_open(self):
        """「打开目录」要打开的路径。

        ⚠ 2026-10-13：这个改动我做过一次，结果被"删重复类"时连带删掉了（当时改的
          恰好是被删掉的那一份）→ 用户反馈"还是打开主目录"。这里重写，并加测试钉住。
        优先 `module_files/`（三个模块实际所在目录），
        再检查程序旁模块目录和用户导入目录。
        """
        cands = []
        # ① 程序旁边那个 modules 文件夹（用户看得见、能删的），没有就建一个
        try:
            import paths as _paths
            d = Path(_paths.app_dir()) / "modules"
            if not d.is_dir():
                d.mkdir(parents=True, exist_ok=True)
            cands.append(str(d))
        except Exception:
            pass
        # ② 源码里的模块文件夹（内置模块所在）
        try:
            import modules as _m
            cands.insert(0, str(_m.MODULE_FILES))
        except Exception:
            pass
        # ③ 用户导入的模块文件所在
        try:
            import svc_modules
            cands.append(str(svc_modules.modules_dir()))
        except Exception:
            pass

        def _has_modules(p):
            try:
                d = Path(p)
                if not d.is_dir():
                    return False
                for sub in d.iterdir():
                    if sub.is_dir() and (sub / "module.py").is_file():
                        return True
                for f in d.iterdir():
                    if f.is_file() and f.name.endswith(".sgmod.json"):
                        return True
            except Exception:
                pass
            return False

        # 1) 先找一个"里面真的有模块"的文件夹（用户要的就是这个）
        for p in cands:
            if _has_modules(p):
                return p
        # 2) 退一步：任何存在的候选目录
        for p in cands:
            try:
                if p and Path(p).is_dir():
                    return p
            except Exception:
                continue
        return ""

    def _open_dir(self):
        """打开**模块文件夹**（不是程序主目录）"""
        p = self._modules_dir_for_open()
        if not p:
            self._log("未找到模块目录。")
            return
        ok, msg = svc_autostart.open_in_explorer(p)
        if not ok:
            self._log(msg)
        else:
            self._log(f"已打开模块目录：{p}")
