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
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from qt_theme import (btn_qss, entry_qss, label_qss, rgba, slider_qss)
import qt_theme as T
import config_manager
import svc_capture
import svc_names
from qt_widgets import (Accordion, Card, RedDot, SettingRow, Switch,
                        SwitchAccordion, level_name, level_value, make_combo,
                        msg_info, right_wrap, set_btn_icon, small_button)
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
                 "为 OBS 及直播页面提供数据；关闭后直播端无数据",
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
                 "在 OBS 中添加「浏览器源」并粘贴该地址（建议 340×200）",
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
                 "修改后即时生效；OBS 端地址需同步更新", self.api_entry,
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

        self.tick_entry = QLineEdit(str(self.cfg.get("tick_interval", 50)))
        self.tick_entry.setFixedWidth(90)
        self.tick_entry.setAlignment(Qt.AlignCenter)
        self.tick_entry.setStyleSheet(entry_qss())
        self.tick_entry.editingFinished.connect(self._on_tick)
        self.row("timer", "检测间隔",
                 "画面检测间隔，单位毫秒（10~5000，默认 50）", self.tick_entry,
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
                 "文字识别间隔，越快响应越及时、越慢越省电", self.ocr_dd,
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
                 "画面变化判定阈值，越灵敏响应越快、耗电越高", self.change_dd,
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
                 "同一提示消失超过该时长后再次出现，计为新掉落", self.event_dd,
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
                                  "勾选需要识别的物品种类",
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
                 "仅原神处于前台时识别，切出后自动暂停", self.only_fg,
                 tip="开启后，原神窗口不在前台时直接跳过这一轮：不截图、不识别，"
                     "既省性能，也避免把浏览器/聊天窗口上的文字当成掉落。\n"
                     "关掉它＝任何窗口在前台都照常识别，只在多开或特殊录屏场景下需要。")

        self.close_dd = self._dd(["每次询问", "最小化到托盘", "直接退出"])
        self.close_dd.setCurrentText({
            "ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"
        }.get(str(self.cfg.get("close_behavior", "ask")), "每次询问"))
        self.close_dd.currentTextChanged.connect(self._on_close_behavior)
        self.row("x", "点右上角 ✕ 时", "点击关闭按钮时的行为", self.close_dd,
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
                                    "全局生效，游戏内也可触发",
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
                      "单次识别读数超过该值即判为误读并丢弃；0 表示不限制",
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
                                "按设定时间归档当日数据并重新开始统计",
                                items=ro_items, alpha=self.alpha,
                                tip="换日＝把当日统计归档，并从零开始累计新的一天。\n"
                                    "归档后的历史仍可在「收益记录」页查到，不会被删除。")
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
            cfg_btn = small_button(
                "配置名单", lambda k=key: self._open_filter(k), self.alpha,
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
                 "更新检测与下载页来源（国内推荐 Gitee）",
                 self.channel_dd,
                 tip="决定「检测更新」走哪个下载源：\n"
                     "· 自动 —— 按网络情况在 Gitee / GitHub 之间挑一个能用的；\n"
                     "· Gitee（国内快）—— 国内下载速度更稳；\n"
                     "· GitHub —— 更新说明与发布页在 GitHub 上时选它。\n"
                     "版本信息本身走仓库里的说明文件，不限流；"
                     "只有下载安装包才走上面选的源。")

        # ---- 检测更新 ----
        upd_row = QWidget()
        ul = QHBoxLayout(upd_row)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(8)
        self.update_btn = QPushButton("检测更新")
        # 用最小宽度而不是固定 130 —— 固定宽度会让按钮比文字宽一大截，
        # 挂在它右上角的红点看着就像挂在卡片上了
        self.update_btn.setMinimumWidth(108)
        self.update_btn.setFixedHeight(32)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setStyleSheet(btn_qss("normal", self.alpha))
        set_btn_icon(self.update_btn, "search", 15)
        self.update_btn.clicked.connect(self._on_check_update)
        self.update_status = QLabel("")
        self.update_status.setStyleSheet(label_qss(T.DIM, 12))
        ul.addWidget(self.update_btn)
        ul.addWidget(self.update_status)
        self.update_row = self.row("refresh-cw", "版本更新",
                                   f"当前版本 v{VERSION}，检测需联网", upd_row,
                                   tip="点「检测更新」会去网上比对最新版本（需联网）。\n"
                                       "发现新版本时可以一键更新：程序自动下载、"
                                       "校验、替换并重新启动。\n"
                                       "**设置与收益数据不会被覆盖**。\n"
                                       "检测到新版本时，左下角会闪红光提示。")
        # 检测到新版本时挂个红点 —— 挂在**「检测更新」按钮**的右上角，
        # 不是整张卡片的右上角（挂卡片上离按钮太远，指不准是哪个）
        self.update_dot = RedDot(self.update_btn)

    # ---- 处理器（原来混在 PageSettings 文件尾部那一堆里）----

    def _on_check_update(self):
        self.update_status.setText("正在检测…")
        self.update_status.setStyleSheet(label_qss(T.DIM, 12))
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
            self.update_status.setText(f"检测失败：{qt_update.reason_text(reason)}")
            self.update_status.setStyleSheet(label_qss("#E06C5A", 12))
            return
        ver = info.get("version", "")
        used = qt_update.CHANNEL_NAMES.get(info.get("channel", ""), "")
        if not info.get("is_newer"):
            # 远端不比本地新（包括远端更旧的情况）—— 都算「已是最新」
            self.update_status.setText(f"已是最新版本（{VERSION}）· 来自 {used}")
            self.update_status.setStyleSheet(label_qss("#6CCB5F", 12))
            return
        self.update_status.setText(f"发现新版本 {ver}（来自 {used}）")
        self.update_status.setStyleSheet(label_qss(T.ACCENT, 12))
        self._ask_update(info)

    def _ask_update(self, info):
        """发现新版本。

        有自动更新信息（version.json 里带了分卷地址）→ 给「立即更新」；
        没带 → 只给「打开下载页」，跟以前一样。
        """
        ver = info.get("version", "")
        notes = str(info.get("notes", "") or "").strip()
        try:
            import qt_updater
            up = qt_updater.update_info_from({"update": info.get("update")})
        except Exception:
            up = None

        dlg = QDialog(self)
        dlg.setWindowTitle("发现新版本")
        dlg.setMinimumWidth(470)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        t = QLabel(f"发现新版本 {ver}")
        t.setStyleSheet(label_qss(T.ACCENT, 18, True))
        v.addWidget(t)

        size_txt = ""
        if up and up.get("size"):
            size_txt = f"（安装包约 {up['size']/1024/1024:.0f} MB）"
        body = QLabel(f"当前版本 {VERSION}　→　{ver} {size_txt}\n\n"
                      + (f"更新内容：\n{notes}" if notes else ""))
        body.setWordWrap(True)
        body.setStyleSheet(label_qss(T.TEXT, 13))
        v.addWidget(body)

        if up:
            tip = QLabel("点击「立即更新」将自动下载并完成替换：\n"
                         "程序自动退出 → 完成替换 → 自动重新启动。\n"
                         "设置与收益数据不会被覆盖。")
            tip.setWordWrap(True)
            tip.setStyleSheet(label_qss(T.DIM, 12))
            v.addWidget(tip)

        row = QHBoxLayout()
        url = str(info.get("url", "") or "").strip()
        if url:
            b_page = QPushButton("打开下载页")
            b_page.setFixedHeight(34)
            b_page.setCursor(Qt.PointingHandCursor)
            b_page.setStyleSheet(btn_qss("normal", self.alpha))
            b_page.clicked.connect(lambda: __import__("webbrowser").open(url))
            row.addWidget(b_page)
        row.addStretch(1)
        b_later = QPushButton("以后再说")
        b_later.setFixedHeight(34)
        b_later.setCursor(Qt.PointingHandCursor)
        b_later.setStyleSheet(btn_qss("normal", self.alpha))
        b_later.clicked.connect(dlg.reject)
        row.addWidget(b_later)
        if up:
            b_go = QPushButton("立即更新")
            b_go.setFixedHeight(34)
            b_go.setMinimumWidth(120)
            b_go.setCursor(Qt.PointingHandCursor)
            b_go.setStyleSheet(btn_qss("accent", self.alpha))
            b_go.clicked.connect(dlg.accept)
            row.addWidget(b_go)
        v.addLayout(row)

        if dlg.exec() == QDialog.Accepted and up:
            self._do_auto_update(up, ver)

    def _do_auto_update(self, up, ver):
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

        dlg = QDialog(self)
        dlg.setWindowTitle("正在更新")
        dlg.setMinimumWidth(470)
        dlg.setWindowFlag(Qt.WindowCloseButtonHint, False)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        lb = QLabel(f"正在下载 StatGI {ver}…")
        lb.setStyleSheet(label_qss(T.TEXT, 14))
        v.addWidget(lb)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setFixedHeight(18)
        bar.setStyleSheet(
            f"QProgressBar {{ background:{rgba('#FFFFFF', 20)}; border:none;"
            f" border-radius:9px; text-align:center; color:{T.TEXT}; font-size:11px; }}"
            f"QProgressBar::chunk {{ background:{T.ACCENT}; border-radius:9px; }}")
        v.addWidget(bar)

        log = QLabel("准备中…")
        log.setWordWrap(True)
        log.setStyleSheet(label_qss(T.DIM, 12))
        v.addWidget(log)

        sig = Sig()
        state = {"dir": None}

        def on_p(p, t):
            if t > 0:
                pct = max(0, min(100, int(p * 100 / t)))
                bar.setValue(pct)
                bar.setFormat(f"{pct}%　{p/1024/1024:.0f} / {t/1024/1024:.0f} MB")

        sig.progress.connect(on_p)
        sig.msg.connect(log.setText)

        def work():
            try:
                d = qt_updater.prepare(up, on_log=lambda s: sig.msg.emit(str(s)),
                                       on_progress=lambda a, b: sig.progress.emit(int(a), int(b)))
                state["dir"] = d
                sig.done.emit(True, "")
            except Exception as e:
                sig.done.emit(False, str(e))

        def on_fin(ok, err):
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
            if QMessageBox.question(
                    self, "更新已准备好",
                    f"新版本 {ver} 已经下载好了。\n\n"
                    "点「确定」后：\n"
                    "  · 软件会自动关闭\n"
                    "  · 自动完成替换（将弹出命令行窗口，请勿关闭）\n"
                    "  · 更新完自动重新打开\n\n"
                    "设置与收益数据不会被覆盖。\n\n现在开始更新？"
            ) != QMessageBox.Yes:
                dlg.reject()
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

    def _on_update_channel(self, text):
        val = {"自动": "auto", "Gitee（国内快）": "gitee",
               "GitHub": "github"}.get(text, "auto")
        self.cfg.set("update_channel", val)
        self.update_status.setText("")


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
                 "开启后显示下方的维护工具", self.dev_enabled,
                 tip="打开后才会显示下面的「开发者选项」（样本采集等维护工具）。\n"
                     "普通使用不需要开启；关闭后已采集的样本文件不会被删除。")

        # ---- 识别日志（一次运行一个文件，放在 data/识别日志/）----
        # ⚠ 这三行**不放进「开发者选项」里** —— 它们是给普通用户反馈问题用的，
        #   藏进开发者模式就等于没有。
        log_open = small_button("打开文件夹", self._open_log_dir, self.alpha,
                                icon="folder-open", width=104)
        log_clear = small_button("清空", self._on_clear_logs, self.alpha,
                                 kind="danger", icon="trash", width=76)
        self.log_row = self.row(
            "file-text", "识别日志",
            "每启动一次软件生成一个日志文件；文件夹超过 20 MB 自动删最早的",
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
                 "把版本、设置、报错日志、识别日志打成一个包，方便反馈",
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
                 "把设置、识别名单、悬浮窗配置打包；换电脑或重装时导入",
                 right_wrap(exp_btn, imp_btn),
                 tip="**导出**：把设置 / 识别名单 / 悬浮窗配置（含预设）/ 收藏夹"
                     "打包成一个 zip，换电脑、重装、给朋友一份配置都用它。\n"
                     "**导入**：从这样的 zip 恢复。导入前会先把现在这份**原样备份**"
                     "到 data/导入前备份_<时间>/，导错了还能自己拷回来。\n"
                     "⚠ 导入后建议重启软件，让全部设置生效。")

        # ---- 开发者选项：折叠卡片，每一项一张子卡片 ----
        self.dev_acc = Accordion(self, "flask-conical", "开发者选项",
                                 "收集识别样本用于后续优化识别准确度；"
                                 "截图只存本地，不上传、不入库",
                                 items=self._make_dev_items(), alpha=self.alpha,
                                 tip="这里的工具用于收集识别样本、排查识别问题，"
                                     "面向开发者与问题定位。\n"
                                     "所有截图**只保存在本机**，不会上传到任何服务器，"
                                     "也不参与收益统计。")
        self.add_card(self.dev_acc)
        self.dev_acc.setVisible(bool(self.cfg.get("developer_mode", False)))
        self._refresh_log_desc()

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
                 "卡片、侧边栏与按钮的统一不透明度（0% 为全透明）",
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
                 "背景图对比度过高时调高，提升文字可读性（0% 不压暗）",
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
                 "设为窗口背景图，卡片区域转为半透明",
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
                 "窗口背景色；可选预设，也可以自己调一个颜色", self.bg_dd,
                 tip="整个窗口的底色。选预设名即可；"
                     "选「自定义颜色…」会打开取色器。\n"
                     "改完立即生效（界面会重建一次，属于正常现象）。")
        self.row("rainbow", "强调色",
                 "按钮、选中项与数值高亮色；可选预设，也可以自己调", self.accent_dd,
                 tip="按钮、开关、选中项、数值高亮用的主色调。\n"
                     "与背景色搭配使用：深色背景配亮一点的强调色更清楚。\n"
                     "同样支持「自定义颜色…」，改完立即生效。")

        self.sidebar_glass = Switch(self, bool(self.cfg.get("sidebar_glass", True)))
        self.sidebar_glass.toggled.connect(self._on_sidebar_glass)
        self.row("eye-off", "左侧栏毛玻璃效果",
                 "需先设置背景图；对侧边栏做模糊与压暗处理", self.sidebar_glass,
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
                 "自定义统计条各格图标（摩拉 / 材料 / 狗粮）", icon_btn,
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
                 "整体放大界面，高分屏字太小时用；重启后生效", self.scale_dd,
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
                 "停止后弹窗汇总本次时长与收益", self.stop_sum,
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
