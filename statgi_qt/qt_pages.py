# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 五个页面

启动 / 收益统计条 / 收益记录 / 设置 / 公告。
（今日统计不单独一页了，收在启动页「开始监测」那张折叠卡片里。）

刷新原则（很重要）：
  · 页面只订阅 state 的信号，数据真变了才动
  · 只改变化的那一个标签，绝不重建控件
  · 不可见的页面一律不刷（记脏标记，显示出来时再补）
"""
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QComboBox, QLineEdit, QSlider,
                               QScrollArea, QFrame, QMessageBox, QFileDialog,
                               QStackedWidget, QDialog, QApplication,
                               QProgressBar)

from qt_theme import (panel_alpha, label_qss, btn_qss, entry_qss, combo_qss,
                      slider_qss, scroll_qss, rgba)
import qt_theme as T
import config_manager
import qt_notice
import sessions
from qt_widgets import (Card, SettingRow, Switch, Accordion, heading,
                        level_name, level_value, set_btn_icon, small_button,
                        IconButton, msg_info, RedDot)
from qt_icon import IconWidget, attach_hover

VERSION = "0.9"

# 颜色下拉框里那一项「自定义颜色…」（选了会开取色器）
CUSTOM_COLOR = "自定义颜色…"


def fmt_seconds(sec):
    """秒 -> 时:分:秒"""
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class BasePage(QWidget):
    """所有页面的共同部分：标题 + 内容区，带内边距"""

    title = ""
    subtitle = ""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.alpha = win.alpha

        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(22, 18, 22, 18)
        self.v.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(heading(self.title))
        if self.subtitle:
            sub = QLabel(self.subtitle)
            sub.setStyleSheet(label_qss(T.DIM, 12))
            sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            head.addStretch(1)
            head.addWidget(sub)
        self.v.addLayout(head)

    def on_show(self):
        """切到本页时调用（各页按需要覆盖）"""

    def add(self, w, stretch=0):
        self.v.addWidget(w, stretch)
        return w

    def stretch(self):
        self.v.addStretch(1)


# ============================================================
#  启动
# ============================================================
class PageLaunch(BasePage):
    title = "启动"

    def __init__(self, win):
        super().__init__(win)
        self.state = win.state

        # 大标题卡片
        c = Card(self, alpha=self.alpha)
        v = QVBoxLayout(c)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.logo_icon = IconWidget(c, name="🍃", size=24, role="ACCENT")
        head.addWidget(self.logo_icon)
        t = QLabel("StatGI")
        t.setStyleSheet(label_qss(T.TEXT, 20, True))
        head.addWidget(t)
        head.addStretch(1)
        v.addLayout(head)

        self.status_label = QLabel("● 未框选（自动检测游戏窗口）")
        self.status_label.setStyleSheet(label_qss(T.DIM, 13))
        v.addWidget(self.status_label)

        last_row = QHBoxLayout()
        last_row.setSpacing(7)
        self.last_icon = IconWidget(c, name="clock", size=15, role="DIM")
        last_row.addWidget(self.last_icon)
        self.last_label = QLabel("最后识别：—")
        self.last_label.setStyleSheet(label_qss(T.DIM, 12))
        last_row.addWidget(self.last_label)
        last_row.addStretch(1)
        v.addLayout(last_row)
        attach_hover(c, self.logo_icon)
        self.add(c)

        # 公告不在这儿了 —— 挪到左侧栏做一个独立入口（未读时挂红点），
        # 点一下由 MainWindow.show_notice() 弹窗显示。

        # ---- 开始监测 ----
        # 尺寸跟下面的「清空」按钮**完全一致**（都是 110×38），
        # 而且都贴着卡片的右边距，所以两个按钮上下对齐。
        self.start_btn = QPushButton("开始")
        self.start_btn.setFixedSize(110, 38)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet(btn_qss("accent", self.alpha))
        self.start_btn.clicked.connect(self._on_start)
        self.add(SettingRow(self, "play", "开始监测",
                            "自动找到游戏窗口并识别掉落收益",
                            right_wrap(self.start_btn), alpha=self.alpha))

        # ---- 本次挂机（独立一张卡片，**只在监测时出现**）----
        # 四个数字**直接摆在这张卡片里**，里面不再套小框了 ——
        # 卡片本身就是那个框（上一版里外两层框，又丑又挤）。
        self.stat_card = Card(self, alpha=self.alpha)
        cb = QHBoxLayout(self.stat_card)
        cb.setContentsMargins(18, 14, 18, 14)
        cb.setSpacing(8)
        self.stat_labels = {}
        self._stat_txt = {}          # 上次写进去的文字，一样就不重复写
        for key, title in (("time", "监测时间"), ("mora", "摩拉"),
                           ("materials", "材料"), ("artifact", "狗粮")):
            col = QVBoxLayout()
            col.setSpacing(3)
            lb = QLabel(title)
            lb.setStyleSheet(label_qss(T.DIM, 12))
            val = QLabel("—")
            val.setStyleSheet(label_qss(T.ACCENT, 19, True))
            col.addWidget(lb)
            col.addWidget(val)
            self.stat_labels[key] = val
            cb.addLayout(col, 1)
        self.stat_card.setVisible(False)      # 一开始不显示
        self.add(self.stat_card)
        self._last_monitoring = False

        # 清空
        self.clear_dd = QComboBox()
        self.clear_dd.addItems(["清空今日数据", "清空监测时间", "全部清空（数据+时间）"])
        self.clear_dd.setFixedWidth(180)
        self.clear_dd.setStyleSheet(combo_qss())
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedSize(110, 38)          # <-- 跟「开始」一样大
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.clear_btn.clicked.connect(self._on_clear)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(self.clear_dd)
        rl.addWidget(self.clear_btn)
        self.add(SettingRow(self, "trash", "清空",
                            "选择清空范围后点击右侧按钮，不影响收益记录",
                            row, alpha=self.alpha))

        # 重新框选（折叠区）
        self.reselect = Accordion(
            self, "crosshair", "重新框选", "手动指定识别区域，通常无需设置",
            items=[
                ("crosshair", "重新框选区域", "在屏幕上手动框出掉落提示所在的区域",
                 small_button("框选", self._on_reselect, self.alpha,
                              icon="crosshair", width=90)),
                ("camera", "诊断截图", "存一张识别区域的截图，用来确认框得对不对",
                 small_button("截图", self._on_debug_screenshot, self.alpha,
                              icon="camera", width=90)),
            ],
            alpha=self.alpha)
        self.add(self.reselect)
        # 撑开：把上面几张卡片顶到上面去，多余空间全留在最底下。
        # 少了这一行，布局会把多余空间摊到每张卡片上 ——
        # 表现就是「重新框选那张卡莫名其妙变高了」。
        self.stretch()

        # 订阅状态：文字变了才改，**不重建控件**
        self.state.status_changed.connect(self._on_status)
        self.state.event_happened.connect(self._on_event)
        self.state.stats_changed.connect(self._sync_button)
        # 统计卡片里的四个数字要**实时**跟着走。
        # （之前只在「开始/停止」那一下刷一次，所以监测过程中数字是死的 ——
        #   得停了再开才会更新。）
        self.state.stats_changed.connect(self._on_stats_tick)

    def _on_status(self, text, color):
        self.status_label.setText(f"● {text}")
        self.status_label.setStyleSheet(label_qss(color, 13))

    def _on_event(self, desc, ts):
        self.last_label.setText(
            f"最后识别：{desc}  ({time.strftime('%H:%M:%S', time.localtime(ts))})")

    def _on_start(self):
        # 正在监测 -> 停止；否则 -> 开始
        # （之前这里无条件调 start()，所以按钮显示「停止」时按下去
        #   实际上是又开了一个识别线程，永远停不下来）
        if self.state.monitoring:
            self.state.stop()
        else:
            self.state.start(on_error=lambda msg: QMessageBox.information(self, "提示", msg))
        self._sync_button()

    def _sync_button(self):
        txt = "停止" if self.state.monitoring else "开始"
        if self.start_btn.text() != txt:       # 只有真的不一样才 setText
            self.start_btn.setText(txt)
        # 统计卡片跟着监测状态显示/隐藏：开始 -> 出现；停止 -> 消失。
        # 只在**状态真的变了**的时候动它，不用每次刷新都算一遍。
        now = bool(self.state.monitoring)
        if now != getattr(self, "_last_monitoring", False):
            self._last_monitoring = now
            self._stat_shown = now
            self.stat_card.setVisible(now)
            if now:
                self.refresh_stats()

    def _on_stats_tick(self):
        """数据变了 —— 卡片正显示着就更一下那四个数字

        看的是 _stat_shown（自己记的开关状态），不是 isVisible()：
        窗口最小化时 isVisible() 会是 False，那段时间就不刷了，
        等恢复出来数字还是旧的。
        """
        if getattr(self, "_stat_shown", False):
            self.refresh_stats()

    def refresh_stats(self):
        """只改变化的那几个数字，别的控件一个字都不动"""
        try:
            snap = self.state.snapshot()
            mats = snap.get("materials") or {}
            mat_total = sum(int(v) for v in mats.values())
            vals = {
                "time": fmt_seconds(snap["seconds"]),
                "mora": f"{int(snap['mora']):,}",
                "materials": f"×{mat_total:,}",
                "artifact": f"×{int(snap['artifact']):,}",
            }
        except Exception:
            return
        for k, txt in vals.items():
            lb = self.stat_labels.get(k)
            if lb is not None and self._stat_txt.get(k) != txt:
                self._stat_txt[k] = txt
                lb.setText(txt)

    def _on_clear(self):
        kind = self.clear_dd.currentText()
        st = self.state.stats
        if kind.startswith("清空今日"):
            if QMessageBox.question(self, "确认", "确定清空今日全部收益数据？\n（历史记录不受影响）"
                                    ) != QMessageBox.Yes:
                return
            st.clear_today()
            msg = "今天的收益已清空"
        elif kind.startswith("清空监测时间"):
            if QMessageBox.question(self, "确认", "确定清空今日监测时间？\n（摩拉、材料等收益不受影响）"
                                    ) != QMessageBox.Yes:
                return
            st.clear_running_seconds()
            if self.state.monitoring:
                self.state.reset_monitor_start()
            msg = "监测时间已清空"
        else:
            if QMessageBox.question(self, "确认", "确定清空今日收益数据与监测时间？\n（收益记录不受影响）"
                                    ) != QMessageBox.Yes:
                return
            st.clear_today()
            st.clear_running_seconds()
            if self.state.monitoring:
                self.state.reset_monitor_start()
            msg = "今日数据和监测时间已清空"
        self.state.force_refresh()
        QMessageBox.information(self, "已清空", msg)

    # ---------- 重新框选 / 诊断截图 ----------
    def _on_reselect(self):
        """把主窗口先藏起来，让用户能看到游戏画面，然后全屏拖框"""
        from qt_dialogs import select_region
        from PySide6.QtWidgets import QApplication as _A
        import time as _t
        QMessageBox.information(
            self, "重新框选",
            "屏幕将暂时变暗。\n\n"
            "· 用鼠标在游戏画面的「掉落提示」区域拖一个框\n"
            "· 松开鼠标完成框选；按 Esc 取消\n"
            "· 框得越贴近提示文字越好")
        self.win.hide()
        _A.processEvents()
        _t.sleep(0.45)              # 等窗口真的消失，别把主界面也截进去
        _A.processEvents()
        rect = select_region(self)
        self.win.show()
        self.win.raise_()
        self.win.activateWindow()
        if rect is None or rect.width() < 5 or rect.height() < 5:
            return
        self.state.set_setting("region", {
            "x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()})
        QMessageBox.information(
            self, "已保存",
            f"识别区域已保存：\n{rect.width()} × {rect.height()}\n\n"
            "建议点击「诊断截图」确认识别区域是否正确。")

    def _on_debug_screenshot(self):
        """截一张识别区域的画面并存下来，顺便 OCR 看看识别到什么"""
        region = self.state.settings.get("region")
        if not region:
            QMessageBox.information(
                self, "提示",
                "尚未手动指定识别区域。\n\n程序默认自动检测游戏窗口；\n"
                "如需手动指定，请先点击「重新框选区域」。")
            return
        try:
            from capture import ScreenCapture
            from PIL import Image as PILImage
            c = ScreenCapture()
            try:
                frame = c.grab(region)
            finally:
                c.close()
            img = PILImage.fromarray(frame[:, :, :3][:, :, ::-1])
            d = paths.app_dir() / "data" / "debug"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"manual_{time.strftime('%Y%m%d_%H%M%S')}.png"
            img.save(f)

            texts = ""
            try:
                from ocr_engine import OcrEngine
                lines = OcrEngine().recognize(frame)
                if lines:
                    texts = "\n".join(f"· {t}" for t, _s in lines[:6])
            except Exception:
                pass
            if texts:
                QMessageBox.information(
                    self, "截图已保存",
                    f"截图已保存：\n{f}\n\n画面里识别到的内容：\n{texts}\n\n"
                    "若显示掉落提示（如「破损的面具 ×1」），说明区域设置正确。")
            else:
                QMessageBox.information(
                    self, "截图已保存",
                    f"截图已保存：\n{f}\n\n画面里没有识别到文字。\n"
                    "若掉落提示出现时此处仍为空白，说明识别区域设置有误。")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"截图失败：{e}")

    def on_show(self):
        self._sync_button()

    def on_show(self):
        pass
class PageBar(BasePage):
    title = "收益统计条"

    def __init__(self, win):
        super().__init__(win)
        self.state = win.state
        bar = self.state.settings.get("stat_bar") or {}

        self.open_btn = QPushButton("打开统计条")
        self.open_btn.setFixedSize(150, 38)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setStyleSheet(btn_qss("accent", self.alpha))
        set_btn_icon(self.open_btn, "chart-column", 15, color="#08222E")
        self.open_btn.clicked.connect(self._toggle_bar)
        self.add(SettingRow(self, "monitor", "桌面悬浮窗",
                            "常驻桌面的小窗口：摩拉 / 材料 / 狗粮 三个格子，图标在上、数量在下",
                            right_wrap(self.open_btn), alpha=self.alpha))

        # 透明度（改完立即生效：直接设统计条窗口的 alpha）
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(int(float(bar.get("opacity", 1.0)) * 100))
        self.opacity.setFixedWidth(180)
        self.opacity.setStyleSheet(slider_qss())
        self.opacity_label = QLabel(f"{self.opacity.value()}%")
        self.opacity_label.setFixedWidth(46)
        self.opacity_label.setStyleSheet(label_qss(T.ACCENT, 13))
        self.opacity.valueChanged.connect(self._on_opacity)
        self.add(SettingRow(self, "contrast", "统计条透明度",
                            "向左调节透明度更高，减少对游戏画面的遮挡",
                            right_wrap(self.opacity, self.opacity_label), alpha=self.alpha))

        # 显示项目：折叠区，每一项一张子卡片（图标 + 标题 + 说明 + 开关）
        self.slot_switches = {}
        slot_items = []
        for key, ic_name, name, desc in (
                ("slot1", "coins", "摩拉", "统计条上显示摩拉那一格"),
                ("slot2", "swords", "材料", "统计条上显示材料那一格"),
                ("slot3", "gem", "狗粮", "统计条上显示圣遗物那一格")):
            sw = Switch(self, bool(bar.get("show_" + key, True)))
            sw.toggled.connect(lambda v, k=key: self._on_slots_changed())
            self.slot_switches[key] = sw
            slot_items.append((ic_name, name, desc, sw))
        self.slot_acc = Accordion(self, "layout-dashboard", "显示项目",
                                  "勾选统计条显示项，修改后即时生效",
                                  items=slot_items, alpha=self.alpha)
        self.add(self.slot_acc)
        self._sync_slot_desc()
        self.stretch()

    def _sync_slot_desc(self):
        names = [n for k, n in (("slot1", "摩拉"), ("slot2", "材料"), ("slot3", "狗粮"))
                 if self.slot_switches[k].isChecked()]
        self.slot_acc.desc_label.setText(
            f"当前显示：{'、'.join(names) if names else '（都不显示）'}")

    def _on_slots_changed(self):
        for key, sw in self.slot_switches.items():
            self.state.set_setting(f"stat_bar.show_{key}", bool(sw.isChecked()))
        self._sync_slot_desc()
        if self.win.bar_window is not None:
            self.win.bar_window.apply_appearance()

    def _toggle_bar(self):
        if self.win.bar_window is not None:
            self.win.bar_window.close()
            self.win.bar_window = None
        else:
            self.win.open_stat_bar()
        self._sync_btn()

    def _sync_btn(self):
        txt = "关闭统计条" if self.win.bar_window is not None else "打开统计条"
        if self.open_btn.text() != txt:
            self.open_btn.setText(txt)

    def _on_opacity(self, v):
        self.opacity_label.setText(f"{v}%")
        self.state.set_setting("stat_bar.opacity", v / 100.0)
        if self.win.bar_window is not None:
            self.win.bar_window.apply_appearance()

    def on_show(self):
        self._sync_btn()


# ============================================================
#  收益记录
# ============================================================
class PageRecords(BasePage):
    title = "收益记录"

    def __init__(self, win):
        super().__init__(win)
        self.state = win.state
        self._open = set()          # 展开了明细的记录 key
        self._cards = {}
        self._view = "normal"       # normal = 收益记录 / fav = 收藏夹
        self._edit = False          # 编辑模式（勾选多条批量操作）
        self._checked = set()       # 编辑模式下勾选的记录 key

        # ---------- 顶部按钮 ----------
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addStretch(1)

        self.edit_btn = IconButton(self, icon="pencil", text="编辑",
                                   alpha=self.alpha)
        self.edit_btn.clicked.connect(self._toggle_edit)
        head.addWidget(self.edit_btn)

        self.fav_btn = IconButton(self, icon="star", text="收藏夹",
                                  alpha=self.alpha)
        self.fav_btn.clicked.connect(self._toggle_view)
        head.addWidget(self.fav_btn)

        self.clear_btn = IconButton(self, icon="trash", text="清空记录",
                                    alpha=self.alpha, kind="danger")
        self.clear_btn.clicked.connect(self._on_clear)
        head.addWidget(self.clear_btn)
        self.v.addLayout(head)

        # ---------- 编辑模式的批量操作条 ----------
        self.edit_bar = QWidget()
        eb = QHBoxLayout(self.edit_bar)
        eb.setContentsMargins(0, 0, 0, 0)
        eb.setSpacing(8)
        self.sel_label = QLabel("已选 0 条")
        self.sel_label.setStyleSheet(label_qss(T.DIM, 13))
        eb.addWidget(self.sel_label)
        eb.addStretch(1)
        self.all_btn = IconButton(self.edit_bar, icon="square-check", text="全选",
                                  alpha=self.alpha)
        self.all_btn.clicked.connect(self._toggle_all)
        eb.addWidget(self.all_btn)
        self.batch_fav_btn = IconButton(self.edit_bar, icon="star", text="收藏",
                                        alpha=self.alpha)
        self.batch_fav_btn.clicked.connect(self._batch_favorite)
        eb.addWidget(self.batch_fav_btn)
        self.batch_del_btn = IconButton(self.edit_bar, icon="trash", text="删除",
                                        alpha=self.alpha, kind="danger")
        self.batch_del_btn.clicked.connect(self._batch_delete)
        eb.addWidget(self.batch_del_btn)
        self.edit_bar.setVisible(False)
        self.v.addWidget(self.edit_bar)

        # ---------- 列表 ----------
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setStyleSheet(scroll_qss())
        sc.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.rec_list = QVBoxLayout(inner)
        self.rec_list.setContentsMargins(0, 0, 10, 0)
        self.rec_list.setSpacing(10)
        sc.setWidget(inner)
        self.add(sc, 1)

        self.empty_label = QLabel("（暂无记录）\n开始并停止一次监测后，将自动生成一条记录。")
        self.empty_label.setStyleSheet(label_qss(T.DIM, 14))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.rec_list.addWidget(self.empty_label)
        self.rec_list.addStretch(1)

        self._sync_head()

    def on_show(self):
        self.refresh()

    # ================= 顶部状态 =================

    def _sync_head(self):
        fav = (self._view == "fav")
        self.fav_btn.set_text("全部记录" if fav else "收藏夹")
        self.fav_btn.set_active(fav)
        self.edit_btn.set_text("完成" if self._edit else "编辑")
        self.edit_btn.set_active(self._edit)
        self.clear_btn.set_text("清空收藏夹" if fav else "清空记录")
        self.edit_bar.setVisible(self._edit)
        n = len(self._checked)
        self.sel_label.setText(f"已选 {n} 条")

    def _current_items(self):
        """当前视图要显示的记录（列表顺序：新的在上面）"""
        if self._view == "fav":
            return list(reversed(sessions.load_favorites()))
        return list(reversed(sessions.load_sessions()))

    def refresh(self):
        """重建列表 —— 只在切页 / 视图切换 / 增删改之后发生"""
        items = self._current_items()
        for w in list(self._cards.values()):
            self.rec_list.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._cards = {}

        if self._view == "fav":
            self.empty_label.setText("（收藏夹是空的）\n"
                                     "在收益记录里点一条记录右边的「收藏」，就会复制到这里。")
        else:
            self.empty_label.setText("（暂无记录）\n开始并停止一次监测后，将自动生成一条记录。")
        self.empty_label.setVisible(not items)

        for idx, item in enumerate(items):
            c = self._make_card(item, fav=(self._view == "fav"))
            self._cards[sessions.record_key(item)] = c
            self.rec_list.insertWidget(idx, c)
        self._sync_head()

    # ================= 视图 / 编辑模式 =================

    def _toggle_view(self):
        self._view = "fav" if self._view == "normal" else "normal"
        self._open.clear()
        self._checked.clear()
        self.refresh()

    def _toggle_edit(self):
        self._edit = not self._edit
        if not self._edit:
            self._checked.clear()
        self.refresh()

    def _toggle_check(self, key):
        if key in self._checked:
            self._checked.discard(key)
        else:
            self._checked.add(key)
        self.refresh()

    def _toggle_all(self):
        keys = {sessions.record_key(i) for i in self._current_items()}
        if keys and keys <= self._checked:
            self._checked.clear()
        else:
            self._checked |= keys
        self.refresh()

    # ================= 单条操作 =================

    def _favorite_one(self, item):
        sessions.add_favorite(item)
        self.refresh()

    def _unfavorite_one(self, item):
        sessions.remove_favorite(item)
        self.refresh()

    def _delete_one(self, item):
        key = sessions.record_key(item)
        left = [r for r in sessions.load_sessions()
                if sessions.record_key(r) != key]
        sessions.save_sessions(left)
        self._checked.discard(key)
        self.refresh()

    # ================= 批量操作 =================

    def _batch_favorite(self):
        if not self._checked:
            QMessageBox.information(self, "提示", "先勾选要收藏的记录")
            return
        n = 0
        for item in self._current_items():
            if sessions.record_key(item) in self._checked:
                sessions.add_favorite(item)
                n += 1
        self._checked.clear()
        self.refresh()
        QMessageBox.information(self, "已收藏", f"{n} 条记录已复制到收藏夹")

    def _batch_delete(self):
        if not self._checked:
            QMessageBox.information(self, "提示", "先勾选要删除的记录")
            return
        if self._view == "fav":
            if QMessageBox.question(self, "确认",
                                    f"从收藏夹移除选中的 {len(self._checked)} 条？"
                                    ) != QMessageBox.Yes:
                return
            for key in list(self._checked):
                sessions.remove_favorite(key)
        else:
            if QMessageBox.question(
                    self, "确认",
                    f"删除选中的 {len(self._checked)} 条收益记录？\n"
                    "（已收藏的副本会留在收藏夹里，不受影响）"
            ) != QMessageBox.Yes:
                return
            left = [r for r in sessions.load_sessions()
                    if sessions.record_key(r) not in self._checked]
            sessions.save_sessions(left)
        self._checked.clear()
        self.refresh()

    # ================= 卡片 =================

    @staticmethod
    def _when_parts(item):
        """把记录里的时间拆成 (日期, 开始时刻, 结束时刻)

        ⚠ 记录是 sessions.make_record() 写的，字段叫 **start / end**
          （完整的 "2026-09-20 14:30:00"）。
          这里以前读的是 date / time —— 那两个字段根本不存在，
          所以每条记录的日期时间都是空的。顺手兼容一下旧数据。
        """
        start = str(item.get("start", "") or "").strip()
        end = str(item.get("end", "") or "").strip()
        if not start:
            d = str(item.get("date", "") or "").strip()
            t = str(item.get("time", "") or "").strip()
            start = (d + " " + t).strip()
        date, t1 = (start.split(" ", 1) + [""])[:2] if start else ("", "")
        t2 = end.split(" ", 1)[1] if " " in end else ""
        return date, t1, t2

    def _make_card(self, item, fav=False):
        key = sessions.record_key(item)
        c = Card(self, alpha=self.alpha)
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)

        # 编辑模式：最左边一个勾选框
        if self._edit:
            sel = IconButton(c, height=28, icon_size=17,
                             icon="square-check" if key in self._checked else "square",
                             alpha=self.alpha)
            sel.clicked.connect(lambda _=None, k=key: self._toggle_check(k))
            top.addWidget(sel)

        dur = fmt_duration(item.get("seconds", 0))
        date, t1, t2 = self._when_parts(item)
        when = date if date else "——"
        if t1:
            when += f"　{t1}"
            if t2:
                when += f" → {t2}"
        top.addWidget(IconWidget(c, name="calendar", size=16, role="DIM"))
        t = QLabel(f"{when}　　时长 {dur}")
        t.setStyleSheet(label_qss(T.TEXT, 14, True))
        top.addWidget(t)
        top.addStretch(1)

        # 「查看明细」
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 4, 0, 0)
        mats = item.get("materials") or {}
        if mats:
            for name, cnt in sorted(mats.items(), key=lambda kv: -kv[1]):
                r = QHBoxLayout()
                a = QLabel(name)
                a.setStyleSheet(label_qss(T.TEXT, 13))
                b = QLabel(f"×{cnt}")
                b.setStyleSheet(label_qss(T.DIM, 13))
                r.addWidget(a)
                r.addStretch(1)
                r.addWidget(b)
                dl.addLayout(r)
        else:
            lb = QLabel("（这条记录没有材料）")
            lb.setStyleSheet(label_qss(T.DIM, 13))
            dl.addWidget(lb)
        detail.setVisible(key in self._open)

        det_btn = IconButton(c, icon="file-text", text="查看明细",
                             alpha=self.alpha, height=28, icon_size=15)
        top.addWidget(det_btn)

        # 「收藏 / 取消收藏」（纯图标，鼠标悬停会弹）
        is_fav = sessions.is_favorite(item)
        fav_btn = IconButton(c, icon="star", alpha=self.alpha, height=28,
                             icon_size=16, active=is_fav)
        if fav:
            fav_btn.setToolTip("从收藏夹移出（不影响原来的收益记录）")
            fav_btn.clicked.connect(
                lambda _=None, it=item: self._unfavorite_one(it))
        else:
            fav_btn.setToolTip("已收藏，点击移出" if is_fav else "收藏到收藏夹")
            fav_btn.clicked.connect(
                lambda _=None, it=item, f=is_fav:
                (self._unfavorite_one(it) if f else self._favorite_one(it)))
        top.addWidget(fav_btn)

        # 「删除」（纯图标；收藏夹里不提供，用上面的星星移出）
        if not fav:
            del_btn = IconButton(c, icon="trash", kind="danger",
                                 alpha=self.alpha, height=28, icon_size=16)
            del_btn.setToolTip("删除这条收益记录（收藏夹里的副本不受影响）")
            del_btn.clicked.connect(
                lambda _=None, it=item: self._delete_one(it))
            top.addWidget(del_btn)

        v.addLayout(top)

        nums = QHBoxLayout()
        for label, val in (("摩拉", f"{item.get('mora', 0):,}"),
                           ("狗粮", f"×{item.get('artifact', 0)}")):
            lb = QLabel(f"{label} {val}")
            lb.setStyleSheet(label_qss(T.ACCENT, 15, True))
            nums.addWidget(lb)
            nums.addSpacing(20)
        nums.addStretch(1)
        v.addLayout(nums)
        v.addWidget(detail)

        def _toggle(_=None, k=key, d=detail, b=det_btn):
            if k in self._open:
                self._open.discard(k)
                d.setVisible(False)
                b.set_text("查看明细")
            else:
                self._open.add(k)
                d.setVisible(True)
                b.set_text("收起明细")

        det_btn.clicked.connect(_toggle)
        if key in self._open:
            det_btn.set_text("收起明细")
        return c

    def _on_clear(self):
        if self._view == "fav":
            if QMessageBox.question(self, "确认",
                                    "确定清空整个收藏夹吗？") != QMessageBox.Yes:
                return
            sessions.clear_favorites()
            self._checked.clear()
            self.refresh()
            QMessageBox.information(self, "已清空", "收藏夹已清空")
            return
        if QMessageBox.question(self, "确认",
                                "确定清空所有收益记录吗？\n"
                                "（今日的统计数据不受影响；收藏夹也不受影响）"
                                ) != QMessageBox.Yes:
            return
        sessions.clear_sessions()
        self._checked.clear()
        self.refresh()
        QMessageBox.information(self, "已清空", "收益记录已清空，收藏夹未受影响")


def fmt_duration(sec):
    sec = int(max(0, sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return f"{h}小时{m}分"
    if m:
        return f"{m}分{s}秒"
    return f"{s}秒"


# ============================================================
#  设置
# ============================================================
class PageSettings(BasePage):
    """设置页：分成 6 个标签，不用在一长条里翻来翻去

    标签是自己画的一排按钮 + QStackedWidget，每个标签里一个滚动区。
    所有设置改完**立即生效 + 立即存盘**，没有保存按钮。
    """

    title = "设置"
    update_checked = Signal(object, object)      # 检测更新结果（从后台线程发回来）

    TABS = ["外观", "识别", "行为", "统计", "直播", "升级", "开发"]

    def __init__(self, win):
        super().__init__(win)
        self.state = win.state
        s = self.state.settings
        self.update_checked.connect(self._update_result)

        # ---------- 标签栏 ----------
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 6)
        bl.setSpacing(6)
        self._tab_btns = []
        self._tab_dots = {}          # 标签名 -> 小红点（检测到新版本时挂在「升级」上）
        for i, name in enumerate(self.TABS):
            b = QPushButton(name)
            b.setFixedHeight(34)
            b.setMinimumWidth(76)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, x=i: self._on_tab(x))
            bl.addWidget(b)
            self._tab_btns.append(b)
            self._tab_dots[name] = RedDot(b)
        bl.addStretch(1)
        self.add(bar)

        # ---------- 每个标签一个滚动区 ----------
        self.tabs = QStackedWidget()
        self._inner = {}
        self._lay = {}
        self._scroll = {}
        for name in self.TABS:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setStyleSheet(scroll_qss())
            sc.viewport().setAutoFillBackground(False)
            inner = QWidget()
            inner.setStyleSheet("background: transparent;")
            lay = QVBoxLayout(inner)
            lay.setContentsMargins(0, 0, 10, 0)
            lay.setSpacing(10)
            lay.addStretch(1)
            sc.setWidget(inner)
            self.tabs.addWidget(sc)
            self._inner[name] = inner
            self._lay[name] = lay
            self._scroll[name] = sc
        self.add(self.tabs, 1)

        # ---------- 各标签的内容 ----------
        self._build_appearance(s)
        self._build_recognize(s)
        self._build_behavior(s)
        self._build_stats(s)
        self._build_live(s)
        self._build_upgrade(s)
        self._build_dev(s)

        self._on_tab(0)

        # 热键捕获（要能收键盘，必须 StrongFocus）
        self.setFocusPolicy(Qt.StrongFocus)
        self._capturing = False
        self.keyPressEvent = self._on_key_press
        self._colors_ready = True

    # ================= 小工具 =================
    def _row(self, tab, icon, title, desc, right=None, height=70):
        row = SettingRow(self._inner[tab], icon, title, desc, right,
                         alpha=self.alpha, height=height)
        self._lay[tab].insertWidget(self._lay[tab].count() - 1, row)
        return row

    def _dd(self, items, width=150):
        d = QComboBox()
        d.addItems([str(x) for x in items])
        d.setFixedWidth(width)
        d.setStyleSheet(combo_qss())
        return d

    def _on_tab(self, idx):
        self.tabs.setCurrentIndex(idx)
        for i, b in enumerate(self._tab_btns):
            on = (i == idx)
            b.setStyleSheet(
                f"QPushButton {{ background:{rgba(T.ACCENT, 60) if on else 'transparent'};"
                f" color:{T.ACCENT if on else T.TEXT}; border:none; border-radius:8px;"
                f" font-family:'Microsoft YaHei UI'; font-size:14px;"
                f"{' font-weight:600;' if on else ''} }}"
                f"QPushButton:hover {{ background: rgba(255,255,255,28); }}")

    # ================= 外观 =================
    def _build_appearance(self, s):
        tb = "外观"
        op = int(float(s.get("panel_opacity", 0.5) or 0.5) * 100)
        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setRange(0, 100)
        self.alpha_slider.setValue(op)
        self.alpha_slider.setFixedWidth(180)
        self.alpha_slider.setStyleSheet(slider_qss())
        self.alpha_label = QLabel(f"{op}%")
        self.alpha_label.setFixedWidth(46)
        self.alpha_label.setStyleSheet(label_qss(T.ACCENT, 13))
        self.alpha_slider.valueChanged.connect(self._on_alpha)
        self._row(tb, "contrast", "卡片透明度",
                  "卡片、侧边栏与按钮的统一不透明度（0% 为全透明）",
                  right_wrap(self.alpha_slider, self.alpha_label))

        dim = int(float(s.get("bg_dim", 0.0) or 0.0) * 100)
        self.dim_slider = QSlider(Qt.Horizontal)
        self.dim_slider.setRange(0, 60)
        self.dim_slider.setValue(dim)
        self.dim_slider.setFixedWidth(180)
        self.dim_slider.setStyleSheet(slider_qss())
        self.dim_label = QLabel(f"{dim}%")
        self.dim_label.setFixedWidth(46)
        self.dim_label.setStyleSheet(label_qss(T.ACCENT, 13))
        self.dim_slider.valueChanged.connect(self._on_dim)
        self._row(tb, "moon", "背景压暗",
                  "背景图对比度过高时调高，提升文字可读性（0% 不压暗）",
                  right_wrap(self.dim_slider, self.dim_label))

        pic = set_btn_icon(QPushButton("选择图片"), "image", 15)
        clr = set_btn_icon(QPushButton("清除"), "x", 15)
        for b, kind, cb in ((pic, "normal", self._choose_bg), (clr, "danger", self._clear_bg)):
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
        cur = s.get("bg_image") or ""
        self.bg_name = QLabel("")
        self.bg_name.setStyleSheet(label_qss(T.DIM, 12))
        # 长文件名会把整张卡片撑宽 —— 限宽 + 中间省略，完整名字放提示气泡里
        self.bg_name.setMaximumWidth(150)
        self._set_bg_name(cur)
        self._row(tb, "image", "自定义背景图片",
                  "设为窗口背景图，卡片区域转为半透明",
                  right_wrap(pic, clr, self.bg_name))

        import theme as _theme_mod      # 只为了取预设名字列表
        bg_items = list(getattr(_theme_mod, "BG_PRESETS", {"经典深黑": "#1C1C1C"}).keys())
        ac_items = list(getattr(_theme_mod, "ACCENT_PRESETS", {"经典蓝": "#4CC2FF"}).keys())
        self.bg_dd = self._dd(bg_items + [CUSTOM_COLOR])
        self.accent_dd = self._dd(ac_items + [CUSTOM_COLOR])
        self._set_combo_silently(self.bg_dd, s.get("bg_color", "经典深黑"))
        self._set_combo_silently(self.accent_dd, s.get("accent_color", "经典蓝"))
        self.bg_dd.currentTextChanged.connect(self._on_bg_color)
        self.accent_dd.currentTextChanged.connect(self._on_accent_color)
        self._row(tb, "palette", "背景颜色",
                  "窗口背景色；可选预设，也可以自己调一个颜色", self.bg_dd)
        self._row(tb, "rainbow", "强调色",
                  "按钮、选中项与数值高亮色；可选预设，也可以自己调", self.accent_dd)

        self.sidebar_glass = Switch(self._inner[tb], bool(s.get("sidebar_glass", True)))
        self.sidebar_glass.toggled.connect(self._on_sidebar_glass)
        self._row(tb, "eye-off", "左侧栏毛玻璃效果",
                  "需先设置背景图；对侧边栏做模糊与压暗处理", self.sidebar_glass)

        # 「统计条图标」放在这里（从「直播」挪过来的）
        icon_btn = QPushButton("打开图标管理")
        icon_btn.setFixedHeight(34)
        icon_btn.setCursor(Qt.PointingHandCursor)
        icon_btn.setStyleSheet(btn_qss("normal", self.alpha))
        icon_btn.clicked.connect(self.win.open_icon_manager)
        self._row(tb, "image", "统计条图标",
                  "自定义统计条各格图标（摩拉 / 材料 / 狗粮）", icon_btn)

    # ================= 识别 =================
    def _build_recognize(self, s):
        tb = "识别"
        self.tick_entry = QLineEdit(str(s.get("tick_interval", 50)))
        self.tick_entry.setFixedWidth(90)
        self.tick_entry.setAlignment(Qt.AlignCenter)
        self.tick_entry.setStyleSheet(entry_qss())
        self.tick_entry.editingFinished.connect(self._on_tick)
        self._row(tb, "timer", "检测间隔",
                  "画面检测间隔，单位毫秒（10~5000，默认 50）", self.tick_entry)

        # 文字识别频率：性能 / 标准 / 省电 / 极致省电（越小越频繁）
        self.ocr_dd = self._dd([name for name, _v in config_manager.OCR_LEVELS])
        self.ocr_dd.setCurrentText(
            level_name(config_manager.OCR_LEVELS,
                       int(s.get("ocr_interval", 150) or 150), config_manager.DEFAULT_OCR_LEVEL))
        self.ocr_dd.currentTextChanged.connect(self._on_ocr_interval)
        self._row(tb, "search", "文字识别频率",
                  "文字识别间隔，越快响应越及时、越慢越省电", self.ocr_dd)

        # 画面变化灵敏度：同一套名字，数值是变化阈值（越小越灵敏）
        #
        # 注意：识别核心读的是 change_threshold，不是 change_level。
        # Tk 版在这儿有个 bug：下拉框按 change_level 显示、保存却只写
        # change_threshold，于是 change_level 永远是老值，**看到的值跟
        # 实际用的值对不上**。这里按 change_threshold 反推显示，并且两个都写。
        self.change_dd = self._dd([name for name, _v in config_manager.CHANGE_LEVELS])
        try:
            _cur_thr = float(s.get("change_threshold", 2.0))
        except Exception:
            _cur_thr = 2.0
        self.change_dd.setCurrentText(
            level_name(config_manager.CHANGE_LEVELS, _cur_thr,
                       config_manager.DEFAULT_CHANGE_LEVEL))
        self.change_dd.currentTextChanged.connect(self._on_change_level)
        self._row(tb, "sliders-horizontal", "画面变化灵敏度",
                  "画面变化判定阈值，越灵敏响应越快、耗电越高", self.change_dd)

        ev = str(s.get("event_end_window", 1.5)).replace("秒", "").strip()
        self.event_dd = self._dd(["1.0 秒", "1.5 秒", "2.5 秒"])
        self.event_dd.setCurrentText((f"{ev} 秒" if f"{ev} 秒" in ("1.0 秒", "1.5 秒", "2.5 秒")
                                      else "1.5 秒"))
        self.event_dd.currentTextChanged.connect(self._on_event_window)
        self._row(tb, "repeat", "防重复窗口",
                  "同一提示消失超过该时长后再次出现，计为新掉落", self.event_dd)

        # 识别哪几样：折叠区，每一项一张子卡片
        self.kind_switches = {}
        kind_items = []
        for key, ic_name, name, desc in (
                ("enable_mora", "coins", "摩拉", "识别并统计拾取到的摩拉"),
                ("enable_material", "swords", "材料", "识别并统计怪物掉落的素材"),
                ("enable_artifact", "gem", "狗粮", "识别并统计拾取的圣遗物")):
            sw = Switch(self._inner[tb], bool(s.get(key, True)))
            sw.toggled.connect(lambda v, k=key: self._on_kinds_changed(k, v))
            self.kind_switches[key] = sw
            kind_items.append((ic_name, name, desc, sw))
        self.kind_acc = Accordion(self._inner[tb], "target", "识别哪几样",
                                  "勾选需要识别的物品种类",
                                  items=kind_items, alpha=self.alpha)
        self._lay[tb].insertWidget(self._lay[tb].count() - 1, self.kind_acc)
        self._sync_kind_desc()

    def _sync_kind_desc(self):
        names = [n for k, n in (("enable_mora", "摩拉"), ("enable_material", "材料"),
                                ("enable_artifact", "狗粮"))
                 if self.kind_switches[k].isChecked()]
        self.kind_acc.desc_label.setText(
            f"当前识别：{'、'.join(names) if names else '（都不识别）'}"
            "　·　展开后勾选；不需要统计的取消勾选")

    def _on_kinds_changed(self, key, val):
        self.state.set_setting(key, bool(val))
        self._sync_kind_desc()
        self.state.apply_live_settings()

    def _on_change_level(self, v):
        """灵敏度：写进识别核心真正读的 change_threshold

        档位：性能 1.0 / 标准 2.0 / 省电 4.0 / 极致省电 8.0（越小越灵敏）
        """
        thr = level_value(config_manager.CHANGE_LEVELS, v, 2.0)
        self.state.set_setting("change_threshold", thr)
        self.state.set_setting("change_level", v)      # 一起写，避免显示/实际不一致
        self.state.apply_live_settings()

    def _on_event_window(self, v):
        try:
            sec = float(str(v).replace("秒", "").strip())
        except Exception:
            return
        self.state.set_setting("event_end_window", sec)
        self.state.apply_live_settings()

    def _on_ocr_interval(self, v):
        """频率：性能 100 / 标准 150 / 省电 250 / 极致省电 500（毫秒）"""
        ms = level_value(config_manager.OCR_LEVELS, v, 150)
        self.state.set_setting("ocr_interval", ms)
        self.state.apply_live_settings()

    # ================= 行为 =================
    def _build_behavior(self, s):
        tb = "行为"
        self.only_fg = Switch(self._inner[tb], bool(s.get("only_foreground", True)))
        self.only_fg.toggled.connect(
            lambda v: self.state.set_setting("only_foreground", bool(v)))
        self._row(tb, "crosshair", "只在原神前台时识别",
                  "仅原神处于前台时识别，切出后自动暂停", self.only_fg)

        self.close_dd = self._dd(["每次询问", "最小化到托盘", "直接退出"])
        self.close_dd.setCurrentText({
            "ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"
        }.get(str(s.get("close_behavior", "ask")), "每次询问"))
        self.close_dd.currentTextChanged.connect(self._on_close_behavior)
        self._row(tb, "x", "点右上角 ✕ 时", "点击关闭按钮时的行为", self.close_dd)

        # ---- 全局热键（收成一张折叠卡片）----
        # 每个动作一个按钮，点按钮后按下想用的键即可录制。
        # _hotkey_btns 记着「设置里的键名 -> 按钮」，录制时按名字找按钮。
        self._hotkey_btns = {}
        self._capturing = None
        hk_items = []
        for key, ic_name, title, desc in (
                ("hotkey", "play", "开始 / 停止监测",
                 "按下即开始监测；再次按下停止"),
                ("hotkey_bar", "chart-column", "显示 / 隐藏统计条",
                 "按下显示统计条；再次按下隐藏")):
            btn = small_button(str(s.get(key, "关闭")), None, self.alpha,
                               width=120, height=30)
            btn.clicked.connect(lambda _=False, k=key: self._start_hotkey_capture(k))
            self._hotkey_btns[key] = btn
            hk_items.append((ic_name, title, desc, btn))

        hk_tip = QLabel("点击右侧按钮后按下目标按键即可设置，Esc 取消；不使用则保持「关闭」")
        hk_tip.setStyleSheet(label_qss(T.DIM, 12))
        hk_tip.setWordWrap(True)

        self.hotkey_acc = Accordion(self._inner[tb], "keyboard", "全局热键",
                                    "全局生效，游戏内也可触发",
                                    items=hk_items, footer=hk_tip,
                                    alpha=self.alpha)
        self._lay[tb].insertWidget(self._lay[tb].count() - 1, self.hotkey_acc)

    # ================= 统计 =================
    def _build_stats(self, s):
        tb = "统计"

        # ---- 换日刷新数据（折叠卡片，默认收起）----
        # 展开里面两组：总开关 + 换日时间，每组下面紧跟一句说明。
        # 关掉开关就**完全不换日**，数据一直累着，直到手动清空。
        #
        # 排版：说明要跟它那一行贴在一起（组内 2px），两组之间才留大间距（14px）。
        # 以前每样都是 12px 平铺，说明就飘在两行正中间，看着空隙特别大。
        self.ro_switch = Switch(self._inner[tb],
                                bool(s.get("rollover_enabled", True)))
        self.ro_switch.toggled.connect(self._on_rollover_enabled)

        self.ro_entry = QLineEdit(str(int(s.get("rollover_hour", 0) or 0)))
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
             "关闭后不再自动换日，数据持续累计", self.ro_switch),
            ("clock", "换日时间（整点 0~23）",
             "跨零点挂机可适当延后，避免中途重新统计", hour_box),
        ]
        self.ro_acc = Accordion(self._inner[tb], "sunrise", "换日刷新数据",
                                "按设定时间归档当日数据并重新开始统计",
                                items=ro_items, alpha=self.alpha)
        self._lay[tb].insertWidget(self._lay[tb].count() - 1, self.ro_acc)

        # ---- 识别名单 ----
        # 放「统计」里（不放「开发」）—— 这个是日常要用的：
        # 识别到什么材料都按这个名单判定，名字错了或者漏了要能随时改。
        warn = QLabel("⚠ 名单里的名字才会被统计。全删光了就什么都识别不到，"
                      "点「恢复默认名单」可以还原。")
        warn.setWordWrap(True)
        warn.setStyleSheet(label_qss("#E06C5A", 12, True))
        self.mat_acc = Accordion(
            self._inner[tb], "clipboard-list", "识别名单",
            "认得出什么由这份名单决定；不在名单里的不记账（只写进识别日志）",
            items=self._make_mat_items(), alpha=self.alpha, footer=warn)
        self._lay[tb].insertWidget(self._lay[tb].count() - 1, self.mat_acc)
        self._refresh_mat_count()

    # ================= 直播 =================
    def _build_live(self, s):
        tb = "直播"

        # ---- 直播数据接口总开关 ----
        # 这个是**真的开关**：关掉就把接口停掉（OBS 那个浏览器源会没数据），
        # 打开就重新起来。以前它只存了个值、什么都不干。
        self.obs_sw = Switch(self._inner[tb], bool(s.get("obs_api_enabled", True)))
        self.obs_sw.toggled.connect(self._on_obs)
        self._row(tb, "radio", "直播数据接口",
                  "为 OBS 及直播页面提供数据；关闭后直播端无数据",
                  self.obs_sw)

        # ---- 收益条地址 ----
        # 注意给的是 /bar（**只有收益条**：摩拉/材料/狗粮/监测时间）。
        # /overlay 那个是整块竖屏覆盖层，上面一半是弹幕区，不是纯收益条。
        api_port = int(s.get("api_port", 8765) or 8765)
        self.obs_addr = QLabel(self._bar_url(api_port))
        self.obs_addr.setStyleSheet(label_qss(T.TEXT, 13))
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(60, 28)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(btn_qss("normal", self.alpha))
        copy_btn.clicked.connect(self._copy_obs)
        self._row(tb, "monitor", "收益条地址",
                  "在 OBS 中添加「浏览器源」并粘贴该地址（建议 340×200）",
                  right_wrap(self.obs_addr, copy_btn))

        # ---- 端口 ----
        self.api_entry = QLineEdit(str(api_port))
        self.api_entry.setFixedWidth(90)
        self.api_entry.setAlignment(Qt.AlignCenter)
        self.api_entry.setStyleSheet(entry_qss())
        self.api_entry.editingFinished.connect(self._on_api_port)
        self._row(tb, "plug", "接口端口",
                  "修改后即时生效；OBS 端地址需同步更新", self.api_entry)

    @staticmethod
    def _bar_url(port):
        return f"http://127.0.0.1:{int(port)}/bar"

    # ================= 升级 =================
    def _build_upgrade(self, s):
        tb = "升级"

        # ---- 更新渠道 ----
        # 国内用 Gitee 快；GitHub 的 API 有每小时 60 次的限流，
        # 所以版本信息走的是仓库里的 version.json（raw 地址，不限流）。
        self.channel_dd = self._dd([n for n, _v in
                                    __import__("qt_update").CHANNELS], width=170)
        _cur = str(s.get("update_channel", "auto") or "auto")
        self.channel_dd.setCurrentText(
            {"auto": "自动", "gitee": "Gitee（国内快）",
             "github": "GitHub"}.get(_cur, "自动"))
        self.channel_dd.currentTextChanged.connect(self._on_update_channel)
        self._row(tb, "globe", "更新渠道",
                  "更新检测与下载页来源（国内推荐 Gitee）",
                  self.channel_dd)

        # ---- 检测更新 ----
        upd_row = QWidget()
        ul = QHBoxLayout(upd_row)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(8)
        self.update_btn = QPushButton("检测更新")
        self.update_btn.setFixedSize(130, 32)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setStyleSheet(btn_qss("normal", self.alpha))
        set_btn_icon(self.update_btn, "search", 15)
        self.update_btn.clicked.connect(self._on_check_update)
        self.update_status = QLabel("")
        self.update_status.setStyleSheet(label_qss(T.DIM, 12))
        ul.addWidget(self.update_btn)
        ul.addWidget(self.update_status)
        self.update_row = self._row(tb, "refresh-cw", "版本更新",
                                    f"当前版本 v{VERSION}，检测需联网", upd_row)
        # 检测到新版本时，这一行右上角也挂个红点
        self.update_dot = RedDot(self.update_row)

    # ================= 开发 =================
    def _build_dev(self, s):
        tb = "开发"

        self.dev_enabled = Switch(self._inner[tb], bool(s.get("developer_mode", False)))
        self.dev_enabled.toggled.connect(self._on_developer_mode)
        self._row(tb, "wrench", "开发者模式",
                  "开启后显示下方样本采集与材料库工具", self.dev_enabled)

        # ---- 开发者选项：折叠卡片，每一项一张子卡片 ----
        self.dev_acc = Accordion(self._inner[tb], "flask-conical", "开发者选项",
                                 "收集识别样本用于后续优化识别准确度；"
                                 "截图只存本地，不上传、不入库",
                                 items=self._make_dev_items(), alpha=self.alpha)
        self._lay[tb].insertWidget(self._lay[tb].count() - 1, self.dev_acc)
        self.dev_acc.setVisible(bool(s.get("developer_mode", False)))

        # 折叠卡片里的「保存目录」和「已采集样本」两行要动态更新，
        # 建完之后按标题把卡片找出来存好
        for c in self.dev_acc.item_cards:
            t = c.title_label.text()
            if t == "样本保存目录":
                self.dev_path_card = c
            elif t == "已采集样本":
                self.dev_stats_card = c
        self._set_dev_path(self.state.get_setting("dataset_path", ""))
        self._refresh_dev_stats()

    # ---------- 识别名单 ----------
    def _make_mat_items(self):
        """识别名单那一组子卡片（挂在「统计」页）"""
        items = []

        # 1) 管理识别名单
        self.name_count_label = QLabel("")
        self.name_count_label.hide()
        edit_btn = small_button("管理…", self._open_material_editor, self.alpha,
                                icon="clipboard-list", width=84)
        items.append(("clipboard-list", "管理识别名单",
                      "查看、增删名单里的名字", edit_btn))

        # 2) 恢复默认名单
        reset_btn = small_button("恢复默认", self._reset_names, self.alpha,
                                 kind="danger", icon="refresh-cw", width=96)
        items.append(("refresh-cw", "恢复默认名单",
                      "改乱了可以一键还原成内置名单", reset_btn))

        # 3) 识别日志开关
        self.log_switch = Switch(self._inner["统计"],
                                 bool(self.state.get_setting("log_detections", True)))
        self.log_switch.toggled.connect(
            lambda v: self.state.set_setting("log_detections", bool(v)))
        items.append(("file-text", "记录识别日志",
                      "每统计一笔都记下来，包含原始识别文字，方便查错",
                      self.log_switch))

        # 4) 打开日志
        open_log = small_button("打开日志", self._open_detect_log, self.alpha,
                                icon="file-text", width=96)
        items.append(("file-text", "识别日志",
                      "每笔统计的时间、名字、数量和原始文字", open_log))

        return items

    def _open_detect_log(self):
        """打开识别日志（没有就提示一句）"""
        import os
        try:
            import detect_log
            p = detect_log.LOG_FILE
        except Exception:
            QMessageBox.warning(self, "失败", "找不到日志模块。")
            return
        if not p.exists():
            msg_info(self, "还没有日志",
                     "还没有记录过。先点「开始监测」跑一会儿，\n"
                     "统计到东西之后这里就会有日志了。")
            return
        try:
            os.startfile(str(p))                     # noqa  Windows 专用
        except Exception as e:
            QMessageBox.warning(self, "打不开", f"打不开日志文件：{e}\n\n位置：\n{p}")

    def _reset_names(self):
        """恢复默认识别名单"""
        import names_db
        try:
            cur = names_db.load()
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
            names_db.reset_to_default()
            reload_names()
            self._refresh_mat_count()
            msg_info(self, "已恢复", "识别名单已还原成内置的。")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"恢复失败：{e}")

    def _refresh_mat_count(self):
        try:
            import names_db
            d = names_db.load()
            txt = (f"材料 {len(d['materials'])} 个　"
                   f"圣遗物 {len(d['artifacts'])} 个")
        except Exception:
            txt = "（读取失败）"
        self.name_count_label.setText(txt)
        acc = getattr(self, "mat_acc", None)
        if acc is not None:
            for c in acc.item_cards:
                if c.title_label.text() == "管理识别名单":
                    c.desc_label.setText(txt + "　点右边可以增删")

    def _open_material_editor(self):
        from qt_dialogs import MaterialDialog
        dlg = MaterialDialog(self.win, self.alpha)
        dlg.exec()
        # 改完名单立刻生效（detector 里的集合是原地更新的）
        try:
            from detector import reload_names
            reload_names()
        except Exception:
            pass
        self._refresh_mat_count()

    def _reset_materials(self):
        """旧名字，保留兼容（现在的入口是「恢复默认名单」）"""
        self._reset_names()

    # ---------- 开发者选项 ----------
    def _make_dev_items(self):
        """开发者选项的每一项（Accordion 会给每项包一张子卡片）"""
        from dataset_collector import DEFAULT_PATH

        items = []

        # 1) 启用样本采集
        # 注意：DatasetCollector 读的键是 dataset_enabled，
        # 不是 dataset_collect —— 键名写错了这个开关就是空的。
        self.dev_switch = Switch(self._inner["开发"],
                                 bool(self.state.get_setting("dataset_enabled", False)))
        self.dev_switch.toggled.connect(
            lambda v: self.state.set_setting("dataset_enabled", bool(v)))
        items.append(("flask-conical", "启用样本采集",
                      "开启后每次确认拾取都会存一张截图", self.dev_switch))

        # 2) 保存目录（长路径放说明里，太长会省略，完整路径在鼠标提示里）
        browse = small_button("浏览…", self._on_choose_dataset_path, self.alpha,
                              icon="folder-open", width=84)
        items.append(("folder-open", "样本保存目录",
                      "截图只存在这个文件夹里，不会上传", browse))

        # 3) 已采集样本（统计数字写在说明里）
        self.dev_stats_label = QLabel("")     # 留着兼容，实际显示在子卡片的说明里
        self.dev_stats_label.hide()
        open_btn = small_button("打开", self._on_open_dataset, self.alpha,
                                icon="image", width=76)
        items.append(("database", "已采集样本", "", open_btn))

        # 4) 清空样本
        clear_btn = small_button("清空", self._on_clear_dataset, self.alpha,
                                 kind="danger", icon="trash", width=76)
        items.append(("trash", "清空样本",
                      "删掉全部已采集的截图，不影响收益数据", clear_btn))

        # 5) 预览「检测到新版本」的效果
        self.sim_update = Switch(self._inner["开发"], False)
        self.sim_update.toggled.connect(self._on_sim_update)
        items.append(("eye", "模拟检测到新版本",
                      "预览左下角闪烁与设置红点的提示效果", self.sim_update))

        return items

    def _set_dev_path(self, path):
        """把样本目录显示到子卡片的说明上（太长就省略，完整路径放提示气泡）"""
        from dataset_collector import DEFAULT_PATH
        full = str(path or "") or str(DEFAULT_PATH)
        card = getattr(self, "dev_path_card", None)
        if card is not None:
            short = full if len(full) <= 32 else full[:15] + "…" + full[-14:]
            card.desc_label.setText(short)
            card.desc_label.setToolTip(full)
            card.setToolTip(full)

    def _on_sim_update(self, v):
        """开发者选项：把「检测到新版本」的提示效果开/关（纯粹为了看效果）"""
        self.win.set_update_available(bool(v), "9.9")

    def _on_developer_mode(self, v):
        self.state.set_setting("developer_mode", bool(v))
        acc = getattr(self, "dev_acc", None)
        if acc is not None:
            acc.setVisible(bool(v))
        if v:
            self._refresh_dev_stats()

    def _refresh_dev_stats(self):
        try:
            from dataset_collector import DatasetCollector
            st = DatasetCollector(self.state.settings).stats()
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
        d = QFileDialog.getExistingDirectory(self, "选择样本保存位置")
        if not d:
            return
        self.state.set_setting("dataset_path", d)
        self._set_dev_path(d)

    def _on_open_dataset(self):
        import os
        from dataset_collector import DEFAULT_PATH
        d = self.state.get_setting("dataset_path", "") or str(DEFAULT_PATH)
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
            from dataset_collector import DatasetCollector
            DatasetCollector(self.state.settings).clear_all()
            self._refresh_dev_stats()
            QMessageBox.information(self, "已清空", "样本已清空。")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"清空失败：{e}")

    # ---------- 检测更新 ----------
    def _on_check_update(self):
        self.update_status.setText("正在检测…")
        self.update_status.setStyleSheet(label_qss(T.DIM, 12))
        import threading
        import qt_update

        ch = str(self.state.get_setting("update_channel", "auto") or "auto")

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

    # ---------- 自动更新 ----------
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
                self.win.hide()          # 先藏窗口，别让用户盯着一个卡住的界面
            except Exception:
                pass
            try:
                self.win._shutdown()     # 停监测 / 关子窗口 / 停接口
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
        self.state.set_setting("update_channel", val)
        self.update_status.setText("")

    # ---------- 各项回调 ----------
    # ---------- 检测到新版本的提示 ----------

    def set_update_badge(self, on):
        """检测到新版本：「升级」标签 + 「版本更新」那一行都挂红点"""
        dot = self._tab_dots.get("升级")
        if dot is not None:
            dot.set_on(on)
        dot2 = getattr(self, "update_dot", None)
        if dot2 is not None:
            dot2.set_on(on)

    def goto_update(self):
        """跳到「升级」标签，并滚到「版本更新」那一行"""
        try:
            self._on_tab(self.TABS.index("升级"))
        except Exception:
            return
        sc = self._scroll.get("升级")
        row = getattr(self, "update_row", None)
        if sc is not None and row is not None:
            sc.ensureWidgetVisible(row, 0, 90)

    def _on_alpha(self, v):
        self.alpha_label.setText(f"{v}%")
        self.state.set_setting("panel_opacity", v / 100.0)
        a = int(v / 100 * 255)
        for c in self.win.findChildren(Card):      # 只改背景色，不重建控件
            c.set_alpha(a)

    def _on_dim(self, v):
        self.dim_label.setText(f"{v}%")
        self.state.set_setting("bg_dim", v / 100.0)
        self.win.apply_bg_dim()

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
        self.state.set_setting("bg_image", p)
        self._set_bg_name(p)
        self.win.set_background_image(p)
        msg_info(self, "成功", "背景图片已应用。")

    def _clear_bg(self):
        self.state.set_setting("bg_image", "")
        self._set_bg_name("")
        self.win.set_background_image(None)

    def _on_tick(self):
        try:
            v = max(10, min(5000, int(self.tick_entry.text().strip())))
        except Exception:
            v = 50
        self.tick_entry.setText(str(v))
        self.state.set_setting("tick_interval", v)

    def _on_rollover(self):
        try:
            h = int(self.ro_entry.text().strip()) % 24
        except Exception:
            h = 0
        self.ro_entry.setText(str(h))
        self.state.set_setting("rollover_hour", h)

    def _on_rollover_enabled(self, v):
        """换日刷新数据的总开关"""
        self.state.set_setting("rollover_enabled", bool(v))

    def _on_api_port(self):
        try:
            v = max(1024, min(65535, int(self.api_entry.text().strip())))
        except Exception:
            v = 8765
        self.api_entry.setText(str(v))
        self.state.set_setting("api_port", v)
        # 地址显示跟着改，并且**立刻**把接口换到新端口（以前要重启）
        try:
            self.obs_addr.setText(self._bar_url(v))
        except Exception:
            pass
        try:
            self.win.apply_api()
        except Exception:
            pass

    def _on_close_behavior(self, text):
        self.state.set_setting("close_behavior", {
            "每次询问": "ask", "最小化到托盘": "tray", "直接退出": "exit"}.get(text, "ask"))

    def _on_obs(self, v):
        """直播数据接口总开关：立刻开 / 关接口"""
        self.state.set_setting("obs_api_enabled", bool(v))
        try:
            self.win.apply_api()
        except Exception:
            pass

    def _copy_obs(self):
        from PySide6.QtWidgets import QApplication as _A
        _A.clipboard().setText(self.obs_addr.text())
        QMessageBox.information(self, "已复制",
                                f"OBS 浏览器源地址已复制：\n{self.obs_addr.text()}")

    def _on_sidebar_glass(self, v):
        self.state.set_setting("sidebar_glass", bool(v))
        self.win.set_sidebar_glass(bool(v))

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

        cur = str(self.state.settings.get(key, "") or "")
        init = QColor(cur) if QColor.isValidColorName(cur) else QColor(T.ACCENT)
        col = QColorDialog.getColor(init, self.win, "选择颜色")
        if not col.isValid():
            # 取消了 → 下拉框回到当前实际值，别停在「自定义颜色…」上
            self._set_combo_silently(combo, self.state.settings.get(key, ""))
            return
        hexv = col.name()
        self._set_combo_silently(combo, hexv)
        self._apply_colors(key, hexv, display=f"自定义 {hexv}")

    def _apply_colors(self, key, value, display=None):
        self.state.set_setting(key, value)
        T.reload_colors(self.state.settings)
        # ⚠ 先把主窗口记下来：rebuild_ui() 会把旧页面从窗口上摘掉，
        #   之后就找不到主窗口了，弹窗会跑到屏幕角落去。
        win = self.win
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

    # ---------- 热键捕获 ----------
    def _start_hotkey_capture(self, which="hotkey"):
        """开始录制热键

        which 指明这次是给哪个动作录：设置里的键名（hotkey / hotkey_bar …）。
        """
        self._capturing = which
        if which not in self._hotkey_btns:
            return
        self._hotkey_btns[which].setText("请按下按键…（Esc 取消）")
        self.setFocus()

    def _on_key_press(self, e):
        which = getattr(self, "_capturing", None)
        if not which:
            return
        btn = self._hotkey_btns.get(which)
        cur = str(self.state.settings.get(which, "关闭"))
        self._capturing = None
        if btn is None:
            return
        k = e.key()
        if k == Qt.Key_Escape:
            btn.setText(cur)
            return
        name = _qt_key_name(e)
        if name is None:
            btn.setText(cur)
            return
        # 同一个键不能同时给两个动作用 —— 不然按一下触发两个
        for other, obtn in self._hotkey_btns.items():
            if other != which and str(self.state.settings.get(other, "关闭")) == name:
                QMessageBox.information(
                    self, "这个键已经用过了",
                    f"「{name}」已分配给其他动作，请更换按键。")
                btn.setText(cur)
                return
        self.state.set_setting(which, name)
        btn.setText(name)

    def on_show(self):
        pass


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


# ============================================================
#  公告（左侧栏那个入口点进来的是这一页，不是弹窗）
# ============================================================
class PageNotice(BasePage):
    """公告页：列出全部公告（最新在最上面），点标题就地展开看全文

    往期公告也在这一页 —— 列表里往下翻就是了。
    未读的标题前面带个红点，点开就算读过。
    """

    title = "公告"

    def __init__(self, win):
        super().__init__(win)
        self.state = win.state
        self.notices = []
        self._cards = []

        # 顶部：条数 + 全部已读 + 刷新
        bar = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(label_qss(T.DIM, 12))
        bar.addWidget(self.count_label)
        bar.addStretch(1)
        self.read_all_btn = QPushButton("全部标为已读")
        self.read_all_btn.setFixedHeight(30)
        self.read_all_btn.setCursor(Qt.PointingHandCursor)
        self.read_all_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.read_all_btn.clicked.connect(self._mark_all)
        bar.addWidget(self.read_all_btn)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setStyleSheet(btn_qss("normal", self.alpha))
        set_btn_icon(self.refresh_btn, "refresh-cw", 15)
        self.refresh_btn.clicked.connect(self._refresh_online)
        bar.addWidget(self.refresh_btn)
        self.v.addLayout(bar)

        # 滚动区放公告列表
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setStyleSheet(scroll_qss())
        sc.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.list_lay = QVBoxLayout(inner)
        self.list_lay.setContentsMargins(0, 0, 10, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        sc.setWidget(inner)
        self.scroll = sc
        self.add(sc, 1)

        self.empty = QLabel("（还没有公告）")
        self.empty.setStyleSheet(label_qss(T.DIM, 14))
        self.empty.setAlignment(Qt.AlignCenter)
        self.list_lay.insertWidget(0, self.empty)

        self.set_notices(qt_notice.load_all())

    # ---------- 数据 ----------
    def set_notices(self, notices):
        """重建列表。公告本来就不多（几十条以内），整表重建够用，
        而且只在「切到本页/拉到新公告/标记已读」时才发生 —— 不是每次数据变化都重建。"""
        self.notices = list(notices or [])
        for w in self._cards:
            self.list_lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._cards = []

        unread = qt_notice.unread_count(self.notices, self.state.settings)
        self.empty.setVisible(not self.notices)
        self.count_label.setText(
            f"共 {len(self.notices)} 条" + (f"，{unread} 条未读" if unread else ""))

        for i, n in enumerate(self.notices):
            card = self._make_card(n)
            self.list_lay.insertWidget(i, card)
            self._cards.append(card)

    def _make_card(self, n):
        """一条公告 = 一个折叠区，点标题展开看全文"""
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 2, 0, 0)
        bv.setSpacing(6)
        txt = QLabel(str(n.get("body", "")))
        txt.setWordWrap(True)
        txt.setStyleSheet(label_qss(T.TEXT, 13))
        bv.addWidget(txt)
        url = str(n.get("url", "") or "").strip()
        if url:
            b = QPushButton("打开链接")
            b.setFixedHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss("accent", self.alpha))
            b.clicked.connect(lambda _=False, u=url: __import__("webbrowser").open(u))
            bv.addWidget(b, alignment=Qt.AlignLeft)

        tm = str(n.get("time", "") or "").strip()
        desc = (f"{tm}　" if tm else "") + (
            "● 未读" if qt_notice.is_unread(n, self.state.settings) else "已读")
        # ⚠ 必须用关键字传 body_widget：Accordion 第 5 个位置参数现在是 items
        #   （一项一张子卡片那个），位置传会把 QWidget 当成 items → 崩
        acc = Accordion(self, "megaphone", str(n.get("title", "")), desc,
                        body_widget=body, alpha=self.alpha)

        # 展开就算读过了
        def _toggle(opened, notice=n):
            if opened:
                qt_notice.mark_read(
                    notice, self.state.settings,
                    lambda s: self.state.set_setting("read_notices", s.get("read_notices", [])))
                self._sync_unread()
        acc._on_toggle = _toggle
        return acc

    def _sync_unread(self):
        """只更新未读标记和计数，不重建列表"""
        unread = qt_notice.unread_count(self.notices, self.state.settings)
        self.count_label.setText(
            f"共 {len(self.notices)} 条" + (f"，{unread} 条未读" if unread else ""))
        for card, n in zip(self._cards, self.notices):
            tm = str(n.get("time", "") or "").strip()
            card.desc_label.setText(
                (f"{tm}　" if tm else "") +
                ("● 未读" if qt_notice.is_unread(n, self.state.settings) else "已读"))
        try:
            self.win.sidebar.set_notice_unread(unread > 0)
        except Exception:
            pass

    def _mark_all(self):
        qt_notice.mark_all_read(
            self.notices, self.state.settings,
            lambda s: self.state.set_setting("read_notices", s.get("read_notices", [])))
        self._sync_unread()

    def _refresh_online(self):
        """手动重新拉一次（带 ?t= 绕开 CDN 缓存）"""
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("拉取中…")
        self._fetcher = qt_notice.NoticeFetcher()
        self._fetcher.done.connect(self._on_refreshed)
        self._fetcher.start(bust_cache=True)

    def _on_refreshed(self, notices):
        """手动刷新回来了

        notices 为 None = 一个源都没拉到（保持现状）；
        为空列表 = 拉到了，远端确实一条公告都没有（要把本地的也清掉）。
        """
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("刷新")
        if notices is None:
            QMessageBox.information(self, "刷新失败", "没拉到公告（可能是网络问题）。\n"
                                                      "显示的还是上次缓存的内容。")
            return
        self.set_notices(notices)
        if notices:
            QMessageBox.information(self, "已刷新", f"拉到 {len(notices)} 条公告。")
        else:
            QMessageBox.information(self, "已刷新", "远端现在一条公告都没有。\n"
                                                    "（可能刚被清空）")

    def on_show(self):
        # 切到本页时重新读一次（可能后台刚拉到新的）
        self.set_notices(qt_notice.load_all())


# ============================================================
def right_wrap(*widgets):
    """把几个控件包成一个整体，好塞进 SettingRow 的右边"""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for x in widgets:
        lay.addWidget(x)
    return w


def build_pages(win):
    """页面顺序要和侧栏对应：
       0 启动  1 收益统计条  2 收益记录  3 设置  4 公告
       前 4 个是侧栏导航项，「公告」是单独那个入口（在导航下面）
       （「今日统计」原来是单独一页，现在收在启动页「开始监测」的折叠卡片里）"""
    return [PageLaunch(win), PageBar(win),
            PageRecords(win), PageSettings(win), PageNotice(win)]


# 公告页在栈里的下标（侧栏那个「公告」按钮要用）
NOTICE_PAGE_INDEX = 4
