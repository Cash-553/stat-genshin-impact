# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 五个页面

启动 / 收益统计条 / 收益细则 / 设置 / 公告 / 收益记录。
（今日统计不单独一页了，收在启动页「开始监测」那张折叠卡片里。）

刷新原则（很重要）：
  · 页面只订阅 state 的信号，数据真变了才动
  · 只改变化的那一个标签，绝不重建控件
  · 不可见的页面一律不刷（记脏标记，显示出来时再补）
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QComboBox, QSlider, QLineEdit,
                               QScrollArea, QFrame, QMessageBox,
                               QStackedWidget, QDialog, QSizePolicy)

from qt_theme import (label_qss, btn_qss, combo_qss, entry_qss,
                      slider_qss, scroll_qss, rgba)
import qt_theme as T
import qt_notice
import qt_settings_tabs
import svc_capture
import svc_settings
import svc_records
import svc_daily
from qt_daily_chart import DailyBarChart
from qt_widgets import (Card, SettingRow, SubRow, Accordion,
                        heading, right_wrap, make_combo,
                        set_btn_icon, small_button, bind_cb,
                        IconButton, RedDot, msg_info)
from qt_icon import IconWidget, attach_hover

# 版本号住在 app_info（叶子模块）里 —— 这样 qt_update 读版本时不必反向
# import 本文件，两边就不会形成循环依赖了。
#
# ⚠ 这里**必须**继续把 VERSION 转发出来：`qt_window` / `qt_sidebar` /
#   `qt_titlebar` / `qt_navbtn` / `qt_bg` 都是从 `qt_pages` 拿它的。
#   （第 9 批拆设置标签页时，本文件自己已经不用它了。）
from app_info import VERSION

# 颜色下拉框里那一项「自定义颜色…」（选了会开取色器）
#
# ⚠ 第 9 批把「外观」标签页拆出去之后，真正的定义在 `qt_settings_tabs` 里
#   （那边要用，而 qt_pages 反向 import 它会成环）。这里**转发**一下，
#   `qt_pages.CUSTOM_COLOR` 对外仍然拿得到，值一个字没变。
from qt_settings_tabs import CUSTOM_COLOR          # noqa: E402,F401


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

    def _dd(self, items, width=150):
        """通用下拉框（放在基类上，别的页面也能用）"""
        return make_combo(items, width)


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

        # ---- 暂停 / 继续（只在「监测中 / 暂停中」出现）----
        # 跟「停止」的区别：**暂停不结束本次会话** ——
        # 收益记录不写、小结不弹，继续时接着这一段跑，数据不清零。
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setFixedSize(88, 38)
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.pause_btn.clicked.connect(self._on_pause)
        self.pause_btn.setVisible(False)

        _btn_box = QWidget()
        _bl = QHBoxLayout(_btn_box)
        _bl.setContentsMargins(0, 0, 0, 0)
        _bl.setSpacing(8)
        _bl.addWidget(self.pause_btn)
        _bl.addWidget(self.start_btn)

        self.add(SettingRow(self, "play", "开始监测",
                            "自动定位游戏窗口并识别掉落收益",
                            right_wrap(_btn_box), alpha=self.alpha))

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
                            "选择清空范围后点右侧按钮执行；不影响收益细则与收藏夹",
                            row, alpha=self.alpha))

        # 重新框选（折叠区）
        self.reselect = Accordion(
            self, "crosshair", "重新框选", "手动指定识别区域；通常无需设置",
            items=[
                ("crosshair", "重新框选区域", "在屏幕上手动框出掉落提示所在的区域",
                 small_button("框选", self._on_reselect, self.alpha,
                              icon="crosshair", width=90), None,
                 "点「框选」后屏幕会变暗：用鼠标在掉落提示所在的地方拖一个矩形，"
                 "松开鼠标即完成，按 Esc 取消。\n"
                 "框得越贴近提示文字，识别越准。\n"
                 "⚠ 一般**不需要**手动框 —— 程序默认会自动找游戏窗口；"
                 "只有自动找不到（或你想只盯屏幕上一小块）时才用。"),
                ("camera", "诊断截图", "存一张识别区域的截图，用来确认框得对不对",
                 small_button("截图", self._on_debug_screenshot, self.alpha,
                              icon="camera", width=90), None,
                 "把当前识别区域截图存到 data/debug/，并顺手识别一次给你看结果，"
                 "用来确认「框的位置对不对、能不能认出字」。\n"
                 "没手动框过区域时，这里会提示你先框选。"),
                # ★ 用户要求加的：框完不满意要能退回去
                ("rotate-ccw", "恢复默认", "取消手动框选，改回自动检测游戏窗口",
                 small_button("恢复默认", self._on_reset_region, self.alpha,
                              kind="danger", icon="rotate-ccw", width=110), None,
                 "把「手动框选的区域」**清掉**，回到程序默认的做法：自动检测游戏窗口。\n"
                 "框完不满意、换分辨率 / 换窗口模式之后框歪了、或者只是想把这块设置"
                 "还原，都用这个退回去。\n"
                 "恢复后**不用重开监测**，下一次识别就按新的方式走。"),
            ],
            alpha=self.alpha,
            tip="这里管的是「识别哪一块屏幕」。\n"
                "默认是自动检测游戏窗口，正常游玩不用动；"
                "手动框选是给特殊场景准备的（多屏、窗口化、只想盯一小块等）。\n"
                "框歪了或者不想要了，点「恢复默认」就能回到自动检测。")
        self.add(self.reselect)
        # 把「重新框选区域」那张子卡片记下来 —— 它的说明里要显示**当前是哪种方式**
        self.region_card = None
        for _c in self.reselect.item_cards:
            if _c.title_label.text() == "重新框选区域":
                self.region_card = _c
        self._sync_region_desc()
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

    def _on_pause(self):
        if getattr(self.state, "paused", False):
            self.state.resume(
                on_error=lambda msg: QMessageBox.information(self, "提示", msg))
        else:
            self.state.pause()
        self._sync_button()

    def _sync_button(self):
        mon = bool(self.state.monitoring)
        paused = bool(getattr(self.state, "paused", False))
        txt = "停止" if mon else "开始"
        if self.start_btn.text() != txt:       # 只有真的不一样才 setText
            self.start_btn.setText(txt)
        # 统计卡片跟着监测状态显示/隐藏：开始 -> 出现；停止 -> 消失。
        # 只在**状态真的变了**的时候动它，不用每次刷新都算一遍。
        # 暂停按钮：监测中显示「暂停」，暂停中显示「继续」，其余隐藏
        show_pause = mon or paused
        if self.pause_btn.isVisible() != show_pause:
            self.pause_btn.setVisible(show_pause)
        ptxt = "继续" if paused else "暂停"
        if self.pause_btn.text() != ptxt:
            self.pause_btn.setText(ptxt)

        # 统计卡片：监测中或暂停中都显示（暂停时这一段的数据还留着）
        now = mon or paused
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
        self._sync_region_desc()          # 那一行的说明要改成"当前：手动区域 W×H"
        QMessageBox.information(
            self, "已保存",
            f"识别区域已保存：\n{rect.width()} × {rect.height()}\n\n"
            "建议点击「诊断截图」确认识别区域是否正确。\n"
            "如果框完不满意，可以点下面的「恢复默认」退回自动检测。")

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
            from PIL import Image as PILImage
            frame = svc_capture.grab(region)
            img = PILImage.fromarray(frame[:, :, :3][:, :, ::-1])
            d = paths.app_dir() / "data" / "debug"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"manual_{time.strftime('%Y%m%d_%H%M%S')}.png"
            img.save(f)

            texts = ""
            try:
                lines = svc_capture.recognize(frame)
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
        """切回启动页：按钮状态 + 「当前是自动还是手动」那行字都要跟上。

        ⚠ 这里原来**定义了两个 on_show**（后一个是 `pass`），把前一个覆盖掉了 ——
          所以切页时 `_sync_button()` 其实一直没被调用（2026-09-29 顺手修掉）。
        """
        self._sync_button()
        self._sync_region_desc()

    def _sync_region_desc(self):
        """把「当前是手动框选还是自动检测」写到那一行的说明里。

        用户不用展开、也不用去别处看，抬头就知道现在是哪种方式。
        """
        card = getattr(self, "region_card", None)
        if card is None:
            return
        try:
            r = self.state.settings.get("region")
            if isinstance(r, dict) and int(r.get("w", 0) or 0) > 0:
                card.desc_label.setText(
                    f"当前：手动区域 {int(r['w'])} × {int(r['h'])}"
                    "　（可重新框选，或用下面的「恢复默认」退回）")
            else:
                card.desc_label.setText("当前：自动检测游戏窗口（默认）")
        except Exception:
            pass

    def _on_reset_region(self):
        """恢复默认：取消手动框选的区域，回到「自动检测游戏窗口」。

        为什么需要它：手动框完如果不满意（框歪了、换分辨率后对不上），
        以前没法退回默认 —— 只能重开软件，或者自己去配置文件里删 region。
        """
        cur = self.state.settings.get("region")
        if not (isinstance(cur, dict) and int(cur.get("w", 0) or 0) > 0):
            msg_info(self, "已经是默认",
                     "现在用的就是默认方式：自动检测游戏窗口，没有手动框选。\n\n"
                     "（如果识别不到，可以先点「诊断截图」看看区域对不对。）")
            return
        if QMessageBox.question(
                self, "恢复默认",
                "取消手动框选的区域，改回「自动检测游戏窗口」？\n\n"
                "· 不用重开监测，下一次识别就按新的方式走；\n"
                "· 以后想再手动框，随时点「框选」就行。") != QMessageBox.Yes:
            return
        self.state.set_setting("region", None)
        self._sync_region_desc()
        msg_info(self, "已恢复默认",
                 "已改回自动检测游戏窗口。\n\n"
                 "如果识别还是不对，可以点「重新框选区域」手动框一个。")


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
                            "常驻桌面的悬浮窗：摩拉 / 材料 / 狗粮三格，图标在上、数值在下",
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
                            "向左调高透明度，减少对游戏画面的遮挡",
                            right_wrap(self.opacity, self.opacity_label), alpha=self.alpha))

        # ---- 悬浮窗样式 ----
        self._build_bar_style(bar)

        self.stretch()

    # ---------- 悬浮窗内容与样式 ----------
    def _build_bar_style(self, bar):
        """入口收在「项目设置」对话框里：动态项目 + 每项独立属性 + 整体窗口设置。

        不要在设置页里堆一堆滑块 —— 那样既不直观也不好扩展。
        """
        edit = small_button("编辑悬浮窗…", self._open_bar_editor, self.alpha,
                            icon="palette", width=128, height=30)
        self.bar_edit_btn = edit
        items = [
            ("settings", "项目与样式",
             "加项目 / 改名字 / 字体 / 卡片 / 排列，改完立刻生效", edit),
        ]
        self.bar_style_acc = Accordion(self, "palette", "悬浮窗内容与样式",
                                       "", items=items, alpha=self.alpha)
        self.add(self.bar_style_acc)
        self._sync_bar_style_desc()

    def _open_bar_editor(self):
        from qt_bar_editor import BarEditorDialog
        if self.win.bar_window is None:
            self.win.open_stat_bar()
            # ⚠ 这里要同步一下按钮文字 —— 不然悬浮窗都开出来了，
            #   按钮还写着「打开统计条」，点一下反而把它关了。
            self._sync_btn()
        # ⚠ 用 show() 而不是 exec()：**模态会把悬浮窗锁住**，
        #   开着编辑器就没法拖悬浮窗了。非模态才能边改边拖。
        dlg = getattr(self, "_bar_editor_dlg", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = BarEditorDialog(self.win, self.alpha, on_apply=self._apply_bar)
        self._bar_editor_dlg = dlg          # 存起来，不然会被垃圾回收
        dlg.finished.connect(lambda _r: self._sync_bar_style_desc())
        dlg.show()

    def _apply_bar(self):
        """让悬浮窗立刻按新配置重建"""
        if self.win.bar_window is not None:
            self.win.bar_window.reload()

    def _sync_bar_style_desc(self):
        import svc_bar
        cfg = svc_bar.load()
        items = cfg.get("items") or []
        vis = sum(1 for x in items if x.get("visible", True))
        self.bar_style_acc.desc_label.setText(
            f"当前 {len(items)} 个项目，显示 {vis} 个")

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
        import svc_bar
        cfg = svc_bar.load()
        cfg["window"]["opacity"] = v / 100.0
        svc_bar.save(cfg)
        if self.win.bar_window is not None:
            self.win.bar_window.reload()

    def on_show(self):
        self._sync_btn()
        self._sync_bar_style_desc()


# ============================================================
#  收益记录
# ============================================================
class PageRecords(BasePage):
    title = "收益细则"

    def __init__(self, win):
        super().__init__(win)
        self.state = win.state
        self._open = set()          # 展开了总数那一级的记录 key（第一级）
        self._mats = set()          # 列出了材料明细的记录 key（第二级）
        self._cards = {}
        self._view = "normal"       # normal = 收益记录 / fav = 收藏夹
        self._edit = False          # 编辑模式（勾选多条批量操作）
        self._checked = set()       # 编辑模式下勾选的记录 key
        self._sig = None            # 上次建列表时的"内容指纹"（切页时判断要不要重建）

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
        """切到本页时刷新 —— **数据没变就不重建**。

        ⚠ 以前是无条件 `refresh()`：每切一次页就把全部卡片重建一遍，
          哪怕只是点进来又点出去（用户反馈的"点开有轻微延迟和卡顿"）。
        """
        if self._sig is not None and self._sig == self._signature():
            return
        self.refresh()

    def _signature(self):
        """当前视图的"内容指纹"：只有它变了才值得重建控件"""
        try:
            items = self._current_items()
        except Exception:
            return None
        return (self._view, self._edit,
                tuple(svc_records.record_key(i) for i in items))

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
            return list(reversed(svc_records.load_favorites()))
        return list(reversed(svc_records.load_sessions()))

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
            self._cards[svc_records.record_key(item)] = c
            self.rec_list.insertWidget(idx, c)
        # 记下这次建的内容指纹（切页时用它判断"要不要重建"）
        self._sig = (self._view, self._edit,
                     tuple(svc_records.record_key(i) for i in items))
        self._sync_head()

    # ================= 视图 / 编辑模式 =================

    def _toggle_view(self):
        self._view = "fav" if self._view == "normal" else "normal"
        self._open.clear()
        self._mats.clear()
        self._checked.clear()
        self.refresh()

    def _toggle_edit(self):
        self._edit = not self._edit
        if not self._edit:
            self._checked.clear()
        self.refresh()

    def _toggle_check(self, key):
        """勾选 / 取消一条 —— **原地改那一个按钮**，不重建列表。

        ⚠ 以前这里是 `refresh()`（整页重建）：勾一条就重建全部卡片，
          记录一多就明显卡顿（用户 2026-09-29 反馈"点开有轻微延迟和卡顿"）。
        """
        if key in self._checked:
            self._checked.discard(key)
        else:
            self._checked.add(key)
        self._sync_check(key)
        self._sync_head()

    def _sync_check(self, key):
        """只把那一条的勾选框刷新一下（图标 + 高亮）"""
        c = self._cards.get(key)
        btn = getattr(c, "sel_btn", None)
        if btn is None:
            return
        on = key in self._checked
        btn.set_icon("square-check" if on else "square")
        btn.set_active(on)

    def _toggle_all(self):
        keys = {svc_records.record_key(i) for i in self._current_items()}
        if keys and keys <= self._checked:
            self._checked.clear()
        else:
            self._checked |= keys
        for k in keys:                      # 同样只刷勾选框，不整页重建
            self._sync_check(k)
        self._sync_head()

    # ================= 单条操作 =================

    def _favorite_one(self, item):
        svc_records.add_favorite(item)
        self.refresh()

    def _unfavorite_one(self, item):
        svc_records.remove_favorite(item)
        self.refresh()

    def _delete_one(self, item):
        key = svc_records.record_key(item)
        left = [r for r in svc_records.load_sessions()
                if svc_records.record_key(r) != key]
        svc_records.save_sessions(left)
        self._checked.discard(key)
        self.refresh()

    # ================= 批量操作 =================

    def _batch_favorite(self):
        if not self._checked:
            QMessageBox.information(self, "提示", "先勾选要收藏的记录")
            return
        n = 0
        for item in self._current_items():
            if svc_records.record_key(item) in self._checked:
                svc_records.add_favorite(item)
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
                svc_records.remove_favorite(key)
        else:
            if QMessageBox.question(
                    self, "确认",
                    f"删除选中的 {len(self._checked)} 条收益记录？\n"
                    "（已收藏的副本会留在收藏夹里，不受影响）"
            ) != QMessageBox.Yes:
                return
            left = [r for r in svc_records.load_sessions()
                    if svc_records.record_key(r) not in self._checked]
            svc_records.save_sessions(left)
        self._checked.clear()
        self.refresh()

    # ================= 卡片 =================

    @staticmethod
    def _when_parts(item):
        """把记录里的时间拆成 (日期, 开始时刻, 结束时刻)

        ⚠ 记录是 svc_records.make_record() 写的，字段叫 **start / end**
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
        """一条收益记录 = **两级展开的折叠卡片**（用户指定的层级）。

            收起      🗓 日期　开始 → 结束　时长              [✎][★][▸][🗑]
            展开一级  摩拉 xx　狗粮 xx　材料 xx               ← 总数
                      [查看明细]                             ← 在这张卡片上
            展开二级  破损的面具 ×12  牢固的箭簇 ×6 …          ← 材料明细

        名称和备注的编辑入口是右边那个铅笔图标（用户要求「只要图标」）。
        """
        key = svc_records.record_key(item)
        c = Card(self, alpha=self.alpha)
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        # ---------- 头部：名称/默认名 + 备注 …… 图标 ----------
        top = QHBoxLayout()
        top.setSpacing(8)

        if self._edit:                      # 编辑模式：最左边一个勾选框
            sel = IconButton(c, height=28, icon_size=17,
                             icon="square-check" if key in self._checked else "square",
                             alpha=self.alpha,
                             active=key in self._checked)
            sel.clicked.connect(lambda _=None, k=key: self._toggle_check(k))
            top.addWidget(sel)
            # 勾选时**原地改这一个按钮**，不重建整页（见 _toggle_check）
            c.sel_btn = sel

        name = svc_records.display_name(item)
        notes = svc_records.display_notes(item)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        name_lb = QLabel(name)
        name_lb.setStyleSheet(label_qss(T.TEXT, 15, True))
        mid.addWidget(name_lb)
        note_lb = QLabel(notes or "（没有备注）")
        note_lb.setStyleSheet(label_qss(T.DIM, 12))
        note_lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        note_lb.setMinimumWidth(0)
        mid.addWidget(note_lb)
        top.addLayout(mid, 1)

        # ---------- 第一级展开：只看得到**总数** ----------
        mats = item.get("materials") or {}
        mat_total = sum(int(v) for v in mats.values())
        head_body = QWidget()
        hb = QVBoxLayout(head_body)
        hb.setContentsMargins(0, 4, 0, 0)
        hb.setSpacing(6)
        nums = QHBoxLayout()
        for label, val in (("摩拉", f"{item.get('mora', 0):,}"),
                           ("狗粮", f"×{item.get('artifact', 0)}"),
                           ("材料", f"{mat_total}")):
            lb = QLabel(f"{label} {val}")
            lb.setStyleSheet(label_qss(T.ACCENT, 15, True))
            nums.addWidget(lb)
            nums.addSpacing(20)
        nums.addStretch(1)
        hb.addLayout(nums)

        # ---------- 第二级：全部材料明细 ----------
        # ⚠「查看明细」按钮**不在这里** —— 它挪到卡片头部去了（见下）。
        #   放在这一块里的话，收起状态就看不到它，用户以为没这个功能（踩过）。
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 2, 0, 0)
        dl.setSpacing(6)

        mats_box = QWidget(detail)
        mb = QVBoxLayout(mats_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(4)
        # ⚠ 材料明细**先不建**（懒加载）—— 这一条很重要：
        #   以前是建卡片时就把**所有**材料行都建出来（哪怕卡片是收起的），
        #   一条记录几十上百种材料 = 几百个控件；切到「收益细则」页要重建
        #   全部卡片，于是"只有 4 条记录点开也卡一下"（用户 2026-09-29 反馈）。
        #   现在改成**第一次展开时才建**（只建一次，之后复用）。
        mats_box._filled = False

        def _fill_mats():
            if mats_box._filled:
                return
            mats_box._filled = True
            if mats:
                for mname, cnt in sorted(mats.items(), key=lambda kv: -kv[1]):
                    r = QHBoxLayout()
                    a = QLabel(mname)
                    a.setStyleSheet(label_qss(T.TEXT, 13))
                    b = QLabel(f"×{cnt}")
                    b.setStyleSheet(label_qss(T.DIM, 13))
                    r.addWidget(a)
                    r.addStretch(1)
                    r.addWidget(b)
                    mb.addLayout(r)
            else:
                lb = QLabel("（这条记录没有材料）")
                lb.setStyleSheet(label_qss(T.DIM, 13))
                mb.addWidget(lb)
            mb.addStretch(1)

        dl.addWidget(mats_box)

        # 三个状态：卡片有没有展开 / 明细有没有列出
        opened = key in self._open
        mats_shown = key in self._mats
        if opened and mats_shown:          # 本来就是展开的，建的时候直接填上
            _fill_mats()
        head_body.setVisible(opened)
        detail.setVisible(opened and mats_shown)
        mats_box.setVisible(mats_shown)
        v.addLayout(top)
        v.addWidget(head_body)
        v.addWidget(detail)
        # 存一下，方便外部（验证脚本 / 以后要联动的地方）查状态
        c.detail = detail
        c.head_body = head_body
        c.mats_box = mats_box

        # ---------- 右边的图标：编辑 / 收藏 / 删除 ----------
        # ⚠ 编辑图标是用户明确要求的（「在主卡片右边加一个编辑的图标，只要图标」）
        edit_btn = IconButton(c, icon="pencil", alpha=self.alpha, height=28,
                              icon_size=16)
        edit_btn.setToolTip("改这条记录的名称和备注")
        edit_btn.clicked.connect(lambda _=None, it=item: self._edit_record(it))
        top.addWidget(edit_btn)

        is_fav = svc_records.is_favorite(item)
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

        # 「查看明细 / 收起明细」—— **放在卡片头部**，收起状态也看得到。
        # ⚠ 用户报过"折叠卡片里没有查看明细这个选项" —— 之前它被放进
        #   展开后的内容区里，收起时根本看不见。放头部就没这个问题。
        det_btn = IconButton(c, icon="file-text", text="查看明细",
                             alpha=self.alpha, height=28, icon_size=15)
        det_btn.setToolTip("展开这条记录，列出全部材料明细")
        top.addWidget(det_btn)

        # 折叠箭头
        arrow = QLabel("▾" if opened else "▸")
        arrow.setStyleSheet(label_qss(T.DIM, 14))
        top.addWidget(arrow)
        c.arrow = arrow

        if not fav:
            del_btn = IconButton(c, icon="trash", kind="danger",
                                 alpha=self.alpha, height=28, icon_size=16)
            del_btn.setToolTip("删除这条收益记录（收藏夹里的副本不受影响）")
            del_btn.clicked.connect(
                lambda _=None, it=item: self._delete_one(it))
            top.addWidget(del_btn)

        # ---------- 展开 / 收起 ----------
        # 两级状态：
        #   _open  第一级（看得到总数那一行）
        #   _mats  第二级（材料明细全列出来）
        # 头部那个「查看明细」按钮**两级一起管**（它就是"看明细"的入口）；
        # 点名字 / 备注 / 箭头只切第一级，但按钮文字要跟着对上。
        def _sync_btn(b=det_btn, k=key):
            b.set_text("收起明细" if k in self._mats else "查看明细")

        def _toggle_card(_=None, k=key, hb=head_body, d=detail,
                         ar=arrow, mm=mats_box):
            if k in self._open:
                self._open.discard(k)
                hb.setVisible(False)
                d.setVisible(False)
                ar.setText("▸")
            else:
                self._open.add(k)
                hb.setVisible(True)
                # 明细按上次的状态恢复
                if k in self._mats:
                    _fill_mats()
                    d.setVisible(True)
                    mm.setVisible(True)
                ar.setText("▾")
            _sync_btn()

        # 「查看明细 / 收起明细」—— 两级一起开 / 一起关
        def _toggle_mats(_=None, k=key, d=detail, mm=mats_box, b=det_btn,
                         hb=head_body, ar=arrow):
            if k in self._mats:
                self._mats.discard(k)
                self._open.discard(k)
                mm.setVisible(False)
                d.setVisible(False)
                hb.setVisible(False)
                ar.setText("▸")
            else:
                self._mats.add(k)
                self._open.add(k)
                _fill_mats()               # ★ 这时候才真正建材料行
                hb.setVisible(True)
                d.setVisible(True)
                mm.setVisible(True)
                ar.setText("▾")
            _sync_btn()

        for w in (name_lb, note_lb, arrow):
            w.setCursor(Qt.PointingHandCursor)
            w.mousePressEvent = _toggle_card
        det_btn.clicked.connect(_toggle_mats)
        _sync_btn()

        return c


    def _edit_record(self, item):
        """弹出小窗改名称 / 备注"""
        import qt_dialogs
        dlg = qt_dialogs.RecordEditDialog(self, item, alpha=self.alpha)
        dlg.setStyleSheet(dlg.styleSheet())
        # 弹在应用窗口正中间
        try:
            dlg.adjustSize()
            g = self.window().frameGeometry()
            dlg.move(g.center().x() - dlg.width() // 2,
                     g.center().y() - dlg.height() // 2)
        except Exception:
            pass
        if dlg.exec() != QDialog.Accepted:
            return
        name, notes = dlg.values()
        svc_records.update_record(item, name=name, notes=notes)
        self.refresh()

    def _on_clear(self):
        if self._view == "fav":
            if QMessageBox.question(self, "确认",
                                    "确定清空整个收藏夹吗？") != QMessageBox.Yes:
                return
            svc_records.clear_favorites()
            self._checked.clear()
            self.refresh()
            QMessageBox.information(self, "已清空", "收藏夹已清空")
            return
        if QMessageBox.question(self, "确认",
                                "确定清空所有收益记录吗？\n"
                                "（今日的统计数据不受影响；收藏夹也不受影响）"
                                ) != QMessageBox.Yes:
            return
        svc_records.clear_sessions()
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
#  收益记录（柱状图）
# ============================================================
class PageDaily(BasePage):
    """收益记录：一根柱子 = 一天，看摩拉 / 狗粮。

    用户 2026-10-04 定的口径：
        · 两个「界面」：摩拉 和 狗粮（上面切换）
        · **默认近 30 天**
        · 保持深色（不照搬 DeepSeek 的浅色）
        · **不要跳转**（点柱子不做任何事，只看悬停数字）
        · **没有收益的那天直接跳过**（不画零高柱）

    数据来自 `svc_daily.daily_totals()`（读收益记录按天加起来）。
    """

    title = "收益记录"

    # (字段, 按钮文字)
    METRICS = (("mora", "摩拉", ""),
               ("artifact", "狗粮", ""))

    def __init__(self, win):
        super().__init__(win)
        self._metric = "mora"
        self._month = None            # None = 还没定，refresh 时选最新的有数据的月
        self._data = None
        self._sig = None
        self._months = []

        card = Card(alpha=self.alpha)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 14)
        cl.setSpacing(10)

        # ---- 第一行：左边切指标，右边选月份 ----
        # 用户 2026-10-04 定的：按**自然月**看（默认显示有数据的那个月），
        # 不要"从今天倒数 N 天"，也不要"全部" —— 挂久了全部的数据太多。
        top = QHBoxLayout()
        top.setSpacing(8)
        self._metric_btns = {}
        for key, text, _unit in self.METRICS:
            # ⚠ 必须用 bind_cb 包一层：clicked 会塞一个 checked(False) 进来，
            #   直接写 `lambda k=key:` 会让 k 变成 False —— 症状是
            #   "点了狗粮就再也切不回摩拉"（2026-10-04 用户报的）。
            b = small_button(text, bind_cb(self._pick_metric, key),
                             self.alpha, width=74)
            self._metric_btns[key] = b
            top.addWidget(b)
        top.addStretch(1)
        self.month_combo = make_combo([], width=150)
        self.month_combo.currentIndexChanged.connect(self._on_month_changed)
        top.addWidget(self.month_combo)
        cl.addLayout(top)

        # ---- 第二行：合计（大字）+ 单位；下面一行小字写天数/平均/最高 ----
        line = QHBoxLayout()
        line.setSpacing(6)
        self.total_label = QLabel("—")
        self.total_label.setStyleSheet(T.title_qss(26))
        line.addWidget(self.total_label)
        self.unit_label = QLabel("")
        self.unit_label.setStyleSheet(label_qss(T.DIM, 12))
        line.addWidget(self.unit_label, 0, Qt.AlignBottom)
        line.addStretch(1)
        cl.addLayout(line)
        # ⚠ 小字单独一行、左对齐 —— 塞进上面那行的右边会跟大字对不齐
        #   （两个标签的垂直对齐方式不同，渲染出来会错开一截，真截图看出来的）
        self.sub_label = QLabel("")
        self.sub_label.setStyleSheet(label_qss(T.DIM, 12))
        self.sub_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cl.addWidget(self.sub_label)

        # ---- 图 ----
        # 高度**封顶**：不然卡片会把图拉成一根很长的竖条，比例就不像那张参考图了
        self.chart = DailyBarChart(unit="")
        self.chart.setMinimumHeight(210)
        self.chart.setMaximumHeight(340)
        cl.addWidget(self.chart, 1)

        self.add(card, 1)

        hint = QLabel("按天汇总收益细则；只画有收益的那些天，"
                      "跨零点的挂机算在开始那天")
        hint.setStyleSheet(label_qss(T.DIM, 11))
        self.add(hint)
        # 挂机时数据会变，但只有本页可见时才刷（别的页一律不刷）
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._auto_refresh)
        self._sync_buttons()

    # ---------- 交互 ----------
    def _pick_metric(self, key):
        if key != self._metric:
            self._metric = key
            self._sync_buttons()
            self._apply()

    def _on_month_changed(self, idx):
        try:
            key = self.month_combo.itemData(idx)
        except Exception:
            key = None
        if key and key != self._month:
            self._month = key
            self.refresh(reload_months=False)

    def _sync_buttons(self):
        for key, b in self._metric_btns.items():
            b.setStyleSheet(btn_qss("accent" if key == self._metric
                                    else "normal", self.alpha))

    def _fill_months(self, months):
        """把月份填进下拉框（**别触发回调**，否则切月会递归）"""
        self._months = months
        keys = [m["key"] for m in months]
        if self._month not in keys:
            # 默认：有数据的**最新那个月**（用户 2026-10-04 定的）
            self._month = keys[0] if keys else None
        self.month_combo.blockSignals(True)
        try:
            self.month_combo.clear()
            for m in months:
                tag = "（本月）" if m["key"] == time.strftime("%Y-%m") else ""
                self.month_combo.addItem(f"{m['label']}{tag}", m["key"])
            if self._month in keys:
                self.month_combo.setCurrentIndex(keys.index(self._month))
        finally:
            self.month_combo.blockSignals(False)

    # ---------- 数据 ----------
    def _signature(self):
        """数据没变就不重建（跟收益细则页一个套路）"""
        try:
            rows = svc_records.load_sessions() or []
            return (len(rows),
                    sum(int(r.get("mora", 0) or 0) for r in rows),
                    sum(int(r.get("artifact", 0) or 0) for r in rows))
        except Exception:
            return None

    def refresh(self, reload_months=True):
        try:
            if reload_months or not self._months:
                self._fill_months(svc_daily.month_options())
            rows, summary = svc_daily.daily_totals(month=self._month)
        except Exception as e:
            rows, summary = [], {}
            try:
                import errlog
                errlog.log_exc("收益记录页刷新")
            except Exception:
                pass
            self.sub_label.setText(f"读取失败：{type(e).__name__}")
        self._data = (rows, summary)
        self._sig = self._signature()
        self._apply()
        self._loaded_month = self._month

    def _apply(self):
        """按当前选中的指标，把图和大字重画一遍（不重新读数据）"""
        rows, summary = (self._data or ([], {}))
        self.chart.set_rows(rows, self._metric)
        val = int(summary.get(self._metric, 0) or 0)
        self.total_label.setText(f"{val:,}" if rows else "—")
        self.unit_label.setText(
            {"mora": "摩拉", "artifact": "狗粮"}.get(self._metric, "")
            if rows else "")
        if not rows:
            self.sub_label.setText("还没有收益")
            return
        avg = int(summary.get(f"avg_{self._metric}", 0) or 0)
        peak = summary.get("peak") or {}
        peak_v = int((peak or {}).get(self._metric, 0) or 0)
        bits = [f"{summary.get('days', 0)} 天有收益",
                f"平均每天 {avg:,}"]
        if peak_v > 0 and peak.get("date"):
            bits.append(f"最高 {peak['date']}（{peak_v:,}）")
        self.sub_label.setText("　·　".join(bits))

    # ---------- 生命周期 ----------
    def _auto_refresh(self):
        if not self.isVisible():
            return
        if self._signature() != self._sig:
            self.refresh()

    def on_show(self):
        changed_month = self._month != getattr(self, "_loaded_month", None)
        if not changed_month and self._data is not None \
                and self._signature() == self._sig:
            return
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)


# ============================================================
#  设置
# ============================================================
# ============================================================
#  已经拆成独立类的设置标签页（第 9 批，一次拆一个）
#
#  工厂签名统一是 (scroll_area, cfg, alpha, win)，但**每个标签页自己决定要哪些** ——
#  比如 LiveTab 只要一个 apply_api 回调，不拿整个主窗口。
#  没登记在这里的标签页，仍然由 PageSettings._build_* 建。
#
#  ⚠ 拆的时候必须逐像素比对：拆完冒烟截图要跟拆之前一字不差
#    （见 _morph\smoke_baseline.py）。
# ============================================================
TAB_FACTORIES = {
    "外观": lambda sc, cfg, alpha, win: qt_settings_tabs.AppearanceTab(
        sc, cfg, alpha, win),
    "识别": lambda sc, cfg, alpha, win: qt_settings_tabs.RecognizeTab(
        sc, cfg, alpha),
    "行为": lambda sc, cfg, alpha, win: qt_settings_tabs.BehaviorTab(
        sc, cfg, alpha),
    "统计": lambda sc, cfg, alpha, win: qt_settings_tabs.StatsTab(
        sc, cfg, alpha, win),
    "直播": lambda sc, cfg, alpha, win: qt_settings_tabs.LiveTab(
        sc, cfg, alpha, win.apply_api),
    "升级": lambda sc, cfg, alpha, win: qt_settings_tabs.UpgradeTab(
        sc, cfg, alpha, win),
    "开发": lambda sc, cfg, alpha, win: qt_settings_tabs.DevTab(
        sc, cfg, alpha, win),
}


class PageSettings(BasePage):
    """设置页：分成 7 个标签，不用在一长条里翻来翻去

    标签是自己画的一排按钮 + QStackedWidget，每个标签里一个滚动区。
    所有设置改完**立即生效 + 立即存盘**，没有保存按钮。

    ⚠ 第 9 批之后，**7 个标签页各自是一个独立类**（见 `qt_settings_tabs` 和
      `TAB_FACTORIES`）。本页只剩：标签栏 + 滚动区 + 那 5 处转发
      （键盘事件 / `on_hide` / 两个红点 / 模拟更新开关）。
    """

    title = "设置"

    TABS = ["外观", "识别", "行为", "统计", "直播", "升级", "开发"]

    def __init__(self, win):
        super().__init__(win)
        # 只拿设置相关的窄入口 —— 设置页没有理由碰 AppState 上
        # 的 toggle() / stop() / snapshot()（那些是识别器的启停和统计）
        self.cfg = svc_settings.Settings(win.state)
        self._last_tab = 0           # 用户最后待的那个标签（清空搜索时回到它）

        # ---------- 搜索框（2026-09-29 加）----------
        # 7 个标签、20 多行设置，找一项得挨个翻；输入关键词直接列出来，
        # 点一条就跳过去（顺带把折叠的卡片展开、闪一下让人找到）。
        #
        # ⚠ 必须套在 Card 里：QLineEdit 写的是**浅色**字（entry_qss），
        #   直接摆在页面背景上时，遇到浅色背景整条就"看不见"了
        #   （踩过：截图里搜索框凭空消失）。卡片是深色半透明底，两种背景都能读。
        srow = Card(self, alpha=self.alpha)
        sl = QHBoxLayout(srow)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(8)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText(
            "搜索设置项…（比如：摩拉 / 热键 / 缩放 / 日志）")
        self.search_entry.setFixedHeight(32)
        self.search_entry.setClearButtonEnabled(True)
        self.search_entry.setStyleSheet(entry_qss())
        self.search_entry.textChanged.connect(self._on_search)
        sl.addWidget(self.search_entry, 1)
        self.add(srow)

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
        # 七个标签页全都是独立类（第 9 批拆完）—— 这里只负责造滚动区、
        # 把它塞进去、按名字记下来。
        self.tabs = QStackedWidget()
        self._scroll = {}
        # 标签名 -> 那个标签页对象。
        # 有些东西还留在本页上（标签栏的红点、键盘事件），要靠它找到
        # 那个标签页里的控件/处理器（见 `_tab_attr`）。
        self._tabs = {}
        for name in self.TABS:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setStyleSheet(scroll_qss())
            sc.viewport().setAutoFillBackground(False)
            make = TAB_FACTORIES.get(name)
            if make is None:
                # 不该发生：TABS 里有一个标签没登记工厂
                raise KeyError(f"设置页标签「{name}」没有登记在 TAB_FACTORIES 里")
            inner = make(sc, self.cfg, self.alpha, win)
            sc.setWidget(inner)
            self.tabs.addWidget(sc)
            self._tabs[name] = inner
            self._scroll[name] = sc
        self.add(self.tabs, 1)

        # ---------- 搜索结果页（第 8 个页面，不在标签栏里）----------
        self._search_page_index = self.tabs.count()      # 加在 7 个标签后面
        ssc = QScrollArea()
        ssc.setWidgetResizable(True)
        ssc.setFrameShape(QFrame.NoFrame)
        ssc.setStyleSheet(scroll_qss())
        ssc.viewport().setAutoFillBackground(False)
        sinner = QWidget()
        sinner.setStyleSheet("background: transparent;")
        self.search_list = QVBoxLayout(sinner)
        self.search_list.setContentsMargins(0, 0, 10, 0)
        self.search_list.setSpacing(8)
        ssc.setWidget(sinner)
        self.tabs.addWidget(ssc)
        self._search_hit_label = QLabel("")
        self._search_hit_label.setStyleSheet(label_qss(T.DIM, 13))
        self.search_list.addWidget(self._search_hit_label)
        self.search_list.addStretch(1)
        self._search_results = []          # [(标签下标, 控件)]，点结果时用

        self._on_tab(0)

        # 热键捕获（要能收键盘，必须 StrongFocus）
        # ⚠ 焦点和 keyPressEvent 留在**设置页**身上：热键录制时页面抢焦点，
        #   收到键盘之后再转给「行为」标签页（那个类自己搬走了，见 `_on_key_press`）。
        self.setFocusPolicy(Qt.StrongFocus)
        self.keyPressEvent = self._on_key_press
        beh = self._tabs.get("行为")
        if beh is not None:
            beh.focus_host = self

    # ================= 小工具 =================
    def _tab_attr(self, tab, name):
        """取某个标签页上的控件/属性（拆出去之后它们不住在本页了）。

        ⚠ 第 9 批是一次拆一个的，所以中间态那会儿这里还得「两边都找一下」
          （`self._tabs` 里没有就退回 `self.<name>`）。七个标签页全拆完之后
          本页一个都不剩，退路也随之删掉了 —— 现在只认 `self._tabs`。
        """
        return getattr(self._tabs.get(tab), name, None)

    def _on_tab(self, idx):
        # 离开「开发」页时，把「模拟检测到新版本」自动关掉。
        # 那是个纯预览用的开关，忘了关的话侧栏会一直闪红光，很烦。
        # ⚠ 当前页可能是**搜索结果页**（下标 = 标签数），所以不能直接
        #   拿 currentIndex() 去索引 TABS —— 会 IndexError（测试抓到过）。
        cur = self.tabs.currentIndex()
        prev_name = self.TABS[cur] if 0 <= cur < len(self.TABS) else ""
        new_name = self.TABS[idx] if 0 <= idx < len(self.TABS) else ""
        if prev_name == "开发" and new_name != "开发":
            sw = self._tab_attr("开发", "sim_update")
            if sw is not None and sw.isChecked():
                sw.setChecked(False)          # 会触发 toggled → 关掉提示

        # 点标签栏 = 退出搜索（不然点了标签还停在搜索结果页，很怪）
        try:
            if self.search_entry.text():
                self.search_entry.blockSignals(True)
                self.search_entry.clear()
                self.search_entry.blockSignals(False)
        except Exception:
            pass

        self.tabs.setCurrentIndex(idx)
        if 0 <= idx < len(self.TABS):     # 记住"用户最后待的标签页"（清空搜索时回到这儿）
            self._last_tab = idx
        for i, b in enumerate(self._tab_btns):
            on = (i == idx)
            b.setStyleSheet(
                f"QPushButton {{ background:{rgba(T.ACCENT, 60) if on else 'transparent'};"
                f" color:{T.ACCENT if on else T.TEXT}; border:none; border-radius:8px;"
                f" font-family:'Microsoft YaHei UI'; font-size:14px;"
                f"{' font-weight:600;' if on else ''} }}"
                f"QPushButton:hover {{ background: rgba(255,255,255,28); }}")

    # ================= 搜索设置项 =================

    def _searchable(self):
        """把所有标签页里"能搜的东西"收集起来。

        收三类（都是界面上真实存在的行）：
            SettingRow   普通设置行
            SubRow       折叠区里的子行（也是 SwitchAccordion 的头部）
            Accordion    折叠卡片本身（它的标题/说明/悬停说明也值得搜）
        返回 [(标签下标, 标题, 说明, 悬停说明, 控件)]。
        """
        out = []
        for ti, name in enumerate(self.TABS):
            tab = self._tabs.get(name)
            if tab is None:
                continue
            seen = set()
            for cls in (SettingRow, SubRow):
                for w in tab.findChildren(cls):
                    if id(w) in seen:
                        continue
                    seen.add(id(w))
                    out.append((ti,
                                getattr(w, "title_label", None).text()
                                if getattr(w, "title_label", None) else "",
                                getattr(w, "desc_label", None).text()
                                if getattr(w, "desc_label", None) else "",
                                w.toolTip() or "", w))
            for a in tab.findChildren(Accordion):
                if id(a) in seen:
                    continue
                seen.add(id(a))
                out.append((ti, a.title_label.text(), a.desc_label.text(),
                            a.header.toolTip() or "", a))
        return out

    def _clear_search_rows(self):
        """把上一次的搜索结果控件都丢掉"""
        for w in self._search_results:
            self.search_list.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._search_results = []

    def _on_search(self, text):
        """输入框一变：要么回到标签页，要么显示搜索结果"""
        q = (text or "").strip().lower()
        self._clear_search_rows()
        if not q:
            self.tabs.setCurrentIndex(max(0, self._last_tab))
            return

        hits = []
        for ti, title, desc, tip, w in self._searchable():
            hay = f"{title}\n{desc}\n{tip}".lower()
            if q in hay:
                hits.append((ti, title, desc, w))

        if not hits:
            self._search_hit_label.setText(f"没有找到跟「{text}」有关的设置项")
        else:
            self._search_hit_label.setText(
                f"找到 {len(hits)} 项　（点一条直接跳过去）")

        for n, (ti, title, desc, w) in enumerate(hits):
            row = SettingRow(self, "search", title,
                             f"{self.TABS[ti]}　·　{desc}",
                             None, alpha=self.alpha, height=64)
            row.setToolTip("点击跳到这一项")
            row.setCursor(Qt.PointingHandCursor)
            cb = (lambda _e=None, t=ti, target=w: self._goto_setting(t, target))
            row.mousePressEvent = cb
            for child in (row.title_label, row.desc_label, row.icon_box,
                          row.icon_widget):
                try:
                    child.setCursor(Qt.PointingHandCursor)
                    child.mousePressEvent = cb
                except Exception:
                    pass
            self.search_list.insertWidget(n, row)
            self._search_results.append(row)

        self.tabs.setCurrentIndex(self._search_page_index)

    def _goto_setting(self, tab_idx, target):
        """跳到某一项：清空搜索 → 切标签 → 展开所在折叠卡片 → 滚到它 → 闪一下"""
        self.search_entry.blockSignals(True)
        self.search_entry.clear()
        self.search_entry.blockSignals(False)
        self._on_tab(tab_idx)

        # 折叠的祖先卡片要展开，否则跳过去只看到一张合着的卡片
        try:
            p = target.parent()
            while p is not None and p is not self:
                if hasattr(p, "_open") and not p._open and hasattr(p, "_toggle"):
                    p._toggle()
                p = p.parent()
        except Exception:
            pass

        sc = self._scroll.get(self.TABS[tab_idx])
        try:
            if sc is not None:
                sc.ensureWidgetVisible(target, 20, 20)
        except Exception:
            pass

        # 闪一下：把那一行的说明文字临时改成强调色，1.2 秒后还原
        lb = getattr(target, "desc_label", None)
        if lb is not None:
            try:
                old = lb.styleSheet()
                lb.setStyleSheet(label_qss(T.ACCENT, 12, True))
                QTimer.singleShot(1200, lambda: lb.setStyleSheet(old))
            except Exception:
                pass

    # ================= 外观 =================
    # ✅ 已拆到 `qt_settings_tabs.AppearanceTab`（第 9 批）。
    #    原来是 `_build_appearance` + `_on_alpha` / `_on_dim` / `_set_bg_name` /
    #    `_choose_bg` / `_clear_bg` / `_on_sidebar_glass` / `_combo_show_color` /
    #    `_set_combo_silently` / `_pick_custom_color` / `_apply_colors` /
    #    `_on_bg_color` / `_on_accent_color`
    #    （构建在这儿、处理器混在文件尾部那一堆里）。

    # ================= 识别 =================
    # ✅ 已拆到 `qt_settings_tabs.RecognizeTab`（第 9 批）。
    #    原来是 `_build_recognize` + `_sync_kind_desc` / `_on_kinds_changed` /
    #    `_on_change_level` / `_on_event_window` / `_on_ocr_interval` / `_on_tick`
    #    （构建在这儿、处理器混在文件尾部那一堆里）。

    # ================= 行为 =================
    # ✅ 已拆到 `qt_settings_tabs.BehaviorTab`（第 9 批）。
    #    原来是 `_build_behavior` + `_on_close_behavior` / `_start_hotkey_capture` /
    #    `_on_key_press`（+ 模块级的 `_qt_key_name`）。
    #    ⚠ 只有键盘事件例外：`keyPressEvent` 还留在本页（它是抢焦点的控件），
    #      收到之后转发给 `BehaviorTab.on_key`。

    # ================= 统计 =================
    # ✅ 已拆到 `qt_settings_tabs.StatsTab`（第 9 批）。
    #    原来是 `_build_stats` + `_build_filter_group` / `_filter_cfg_desc` /
    #    `_on_filter_toggled` / `_open_filter` / `_make_mat_items` / `_reset_names` /
    #    `_refresh_mat_count` / `_open_material_editor` / `_reset_materials` /
    #    `_on_rollover` / `_on_rollover_enabled` / `_warn_empty_filters` /
    #    `_center_on_app`（构建在这儿、处理器混在文件尾部那一堆里）。
    #    ⚠ 只有「离开设置页的空名单提醒」例外：主窗口调的是**页面**的
    #      `on_hide`，所以本页留一个转发（见下面 `on_hide`）。

    # ---------- 离开设置页时的空名单提醒 ----------

    def on_hide(self):
        """离开设置页：转给「统计」标签页做空名单提醒。

        ⚠ 主窗口切页时调的是**页面**的 `on_hide`（见 `qt_window` 第 618 行），
          所以这里必须转发一道 —— 本体已经搬进 `StatsTab.warn_empty_filters`，
          连"弹完才切页"的顺序都跟原来一样。
        """
        tab = self._tabs.get("统计")
        if tab is None:
            return
        try:
            tab.warn_empty_filters()
        except Exception:
            pass

    # ================= 直播 =================
    # ✅ 已拆到 `qt_settings_tabs.LiveTab`（第 9 批）。
    #    原来是 `_build_live` + `_bar_url` + `_on_api_port` / `_on_obs` / `_copy_obs`
    #    （构建在这儿、处理器混在文件尾部那一堆里）。

    # ================= 升级 =================
    # ✅ 已拆到 `qt_settings_tabs.UpgradeTab`（第 9 批）。
    #    原来是 `_build_upgrade` + `_on_check_update` / `_update_result` /
    #    `_ask_update` / `_do_auto_update` / `_on_update_channel`
    #    （构建在这儿、处理器混在文件尾部那一堆里）。
    #    ⚠ `update_checked` 这个信号也跟着搬走了（它挂在那个标签页上）——
    #      本页的 `set_update_badge` / `goto_update` 通过 `_tab_attr` 找
    #      那个标签页上的 `update_dot` / `update_row`。

    # ================= 开发 =================
    # ✅ 已拆到 `qt_settings_tabs.DevTab`（第 9 批）。
    #    原来是 `_build_dev` + `_make_dev_items` / `_set_dev_path` /
    #    `_on_sim_update` / `_on_developer_mode` / `_refresh_dev_stats` /
    #    `_on_choose_dataset_path` / `_on_open_dataset` / `_on_clear_dataset`。

    # ---------- 检测到新版本的提示 ----------

    def set_update_badge(self, on):
        """检测到新版本：「升级」标签 + 「版本更新」那一行都挂红点"""
        dot = self._tab_dots.get("升级")
        if dot is not None:
            dot.set_on(on)
        dot2 = self._tab_attr("升级", "update_dot")
        if dot2 is not None:
            dot2.set_on(on)

    def goto_update(self):
        """跳到「升级」标签，并滚到「版本更新」那一行"""
        try:
            self._on_tab(self.TABS.index("升级"))
        except Exception:
            return
        sc = self._scroll.get("升级")
        row = self._tab_attr("升级", "update_row")
        if sc is not None and row is not None:
            sc.ensureWidgetVisible(row, 0, 90)

    # ---------- 热键捕获 ----------
    def _on_key_press(self, e):
        """设置页收到键盘 → 转给「行为」标签页（热键录制要用）。

        ⚠ 为什么焦点/键盘还留在本页：`keyPressEvent` 必须装在**有焦点**的那个
          控件上，而抢焦点的是设置页（`_start_hotkey_capture` 里
          `focus_host.setFocus()` 指的就是本页）。所以「行为」把录制逻辑带走了、
          键盘事件从这儿转一道 —— 处理器本身在 `qt_settings_tabs.BehaviorTab.on_key`。
        """
        tab = self._tabs.get("行为")
        if tab is not None:
            tab.on_key(e)

    def on_show(self):
        pass

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
def build_pages(win):
    """页面栈的顺序（**代码里的顺序**）：
       0 启动  1 收益统计条  2 收益细则  3 设置  4 公告  5 收益记录

    ⚠ **新页一律追加在末尾**，别插进中间 —— 0~4 这几个下标被一堆测试和
      渲染脚本写死引用了（`_morph` 里 15 个文件），插一页它们全指错页。
      侧栏想把它显示在第几个，写在 `qt_window` 的 `_nav_to_page` 那张表里。
    """
    return [PageLaunch(win), PageBar(win),
            PageRecords(win), PageSettings(win), PageNotice(win),
            PageDaily(win)]


# 页面在栈里的下标（**追加新页时只动这里**，别写死数字）
LAUNCH_PAGE_INDEX = 0      # 启动
BAR_PAGE_INDEX = 1         # 收益统计条
RECORDS_PAGE_INDEX = 2     # 收益记录
SETTINGS_PAGE_INDEX = 3    # 设置（标题栏那个「设置」齿轮要用）
NOTICE_PAGE_INDEX = 4      # 公告（侧栏下面那个单独入口）
DAILY_PAGE_INDEX = 5       # 每日收益（侧栏映射表要用）

