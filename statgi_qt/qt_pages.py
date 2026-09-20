# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 五个页面

启动 / 今日统计 / 收益统计条 / 收益记录 / 设置。

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
from qt_widgets import (Card, SettingRow, Switch, Accordion, ButtonRow, heading,
                        level_name, level_value)

VERSION = "0.9"


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
        t = QLabel("🍃  StatGI")
        t.setStyleSheet(label_qss(T.TEXT, 20, True))
        self.status_label = QLabel("● 未框选（自动检测游戏窗口）")
        self.status_label.setStyleSheet(label_qss(T.DIM, 13))
        self.last_label = QLabel("🕐 最后识别：—")
        self.last_label.setStyleSheet(label_qss(T.DIM, 12))
        v.addWidget(t)
        v.addWidget(self.status_label)
        v.addWidget(self.last_label)
        self.add(c)

        # 公告不在这儿了 —— 挪到左侧栏做一个独立入口（未读时挂红点），
        # 点一下由 MainWindow.show_notice() 弹窗显示。

        # 开始监测
        # 尺寸跟下面的「清空」按钮**完全一致**（都是 110×38），
        # 而且都贴着卡片的右边距，所以两个按钮上下对齐。
        self.start_btn = QPushButton("开始")
        self.start_btn.setFixedSize(110, 38)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet(btn_qss("accent", self.alpha))
        self.start_btn.clicked.connect(self._on_start)
        self.add(SettingRow(self, "▶", "开始监测",
                            "自动找到游戏窗口并识别掉落收益",
                            right_wrap(self.start_btn), alpha=self.alpha))

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
        self.add(SettingRow(self, "🧹", "清空",
                            "选好要清空的内容，再点右边按钮（收益记录不受影响）",
                            row, alpha=self.alpha))

        # 重新框选（折叠区）
        self.reselect = Accordion(
            self, "🎯", "重新框选", "手动指定要识别的屏幕区域（一般都不用）",
            ButtonRow(self, [("重新框选区域", self._on_reselect),
                             ("📷 诊断截图", self._on_debug_screenshot)], self.alpha),
            alpha=self.alpha)
        self.add(self.reselect)

        # ---- 今日统计（折叠区）----
        # 原来是一个单独的页面，现在并到启动页里，收成折叠区。
        # 只放四个数字：挂机时间 / 摩拉 / 材料 / 狗粮。
        # 材料明细不在这儿（那个去「收益记录」看），免得启动页太乱。
        self.stat_body = QWidget()
        sb = QHBoxLayout(self.stat_body)
        sb.setContentsMargins(2, 8, 2, 4)
        sb.setSpacing(8)
        self.stat_labels = {}
        self._stat_txt = {}          # 上次写进去的文字，一样就不重复写
        self._stat_stale = True      # 折叠期间漏掉的刷新
        for key, title in (("time", "⏱ 挂机时间"), ("mora", "💰 摩拉"),
                           ("materials", "📦 材料"), ("artifact", "💠 狗粮")):
            col = QVBoxLayout()
            col.setSpacing(2)
            lb = QLabel(title)
            lb.setStyleSheet(label_qss(T.DIM, 12))
            val = QLabel("—")
            val.setStyleSheet(label_qss(T.ACCENT, 19, True))
            col.addWidget(lb)
            col.addWidget(val)
            self.stat_labels[key] = val
            sb.addLayout(col)
        sb.addStretch(1)
        self.stat_acc = Accordion(self, "📊", "今日统计",
                                  "挂机时间 · 摩拉 · 材料 · 狗粮",
                                  self.stat_body, alpha=self.alpha,
                                  on_toggle=self._on_stat_toggle)
        self.add(self.stat_acc)
        self.stretch()

        # 订阅状态：文字变了才改，**不重建控件**
        self.state.status_changed.connect(self._on_status)
        self.state.event_happened.connect(self._on_event)
        self.state.stats_changed.connect(self._sync_button)
        # 今日统计那四个数字：折叠着就不刷，展开时一次性补上
        self.state.stats_changed.connect(self._on_stats_changed)

    # ---------- 今日统计（折叠区） ----------
    def _on_stat_toggle(self, opened):
        if opened:
            self.refresh_stats()

    def _on_stats_changed(self):
        if self.stat_acc._open:
            self.refresh_stats()
        else:
            self._stat_stale = True

    def refresh_stats(self):
        """只改变化的那几个数字，别的控件一个字都不动"""
        self._stat_stale = False
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

    def _on_status(self, text, color):
        self.status_label.setText(f"● {text}")
        self.status_label.setStyleSheet(label_qss(color, 13))

    def _on_event(self, desc, ts):
        self.last_label.setText(
            f"🕐 最后识别：{desc}  ({time.strftime('%H:%M:%S', time.localtime(ts))})")

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

    def _on_clear(self):
        kind = self.clear_dd.currentText()
        st = self.state.stats
        if kind.startswith("清空今日"):
            if QMessageBox.question(self, "确认", "确定清空今天的所有收益吗？\n（历史记录不受影响）"
                                    ) != QMessageBox.Yes:
                return
            st.clear_today()
            msg = "今天的收益已清空"
        elif kind.startswith("清空监测时间"):
            if QMessageBox.question(self, "确认", "确定清空监测时间吗？\n（摩拉、材料等收益不受影响）"
                                    ) != QMessageBox.Yes:
                return
            st.clear_running_seconds()
            if self.state.monitoring:
                self.state.reset_monitor_start()
            msg = "监测时间已清空"
        else:
            if QMessageBox.question(self, "确认", "确定清空今天的收益数据和监测时间吗？\n（收益记录不受影响）"
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
            "接下来会全屏变暗。\n\n"
            "· 用鼠标在游戏画面的「掉落提示」区域拖一个框\n"
            "· 松手即完成；按 Esc 取消\n"
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
            "建议点「📷 诊断截图」确认框对了没有。")

    def _on_debug_screenshot(self):
        """截一张识别区域的画面并存下来，顺便 OCR 看看识别到什么"""
        region = self.state.settings.get("region")
        if not region:
            QMessageBox.information(
                self, "提示",
                "还没有手动框选区域。\n\n程序默认会自动检测游戏窗口；\n"
                "如果想手动指定，请先点「重新框选区域」。")
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
                    "💡 如果显示的是掉落提示（如「破损的面具 ×1」），说明框对了。")
            else:
                QMessageBox.information(
                    self, "截图已保存",
                    f"截图已保存：\n{f}\n\n画面里没有识别到文字。\n"
                    "💡 如果掉落提示出现时这里仍是空白，说明区域没框对。")
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

        self.open_btn = QPushButton("📶 打开统计条")
        self.open_btn.setFixedSize(150, 38)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setStyleSheet(btn_qss("accent", self.alpha))
        self.open_btn.clicked.connect(self._toggle_bar)
        self.add(SettingRow(self, "📶", "直播间小窗口",
                            "摩拉 / 材料 / 狗粮 三个格子，图标在上、数量在下",
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
        self.add(SettingRow(self, "🌓", "统计条透明度",
                            "往左拉更透明，直播画面上不容易挡到游戏画面",
                            right_wrap(self.opacity, self.opacity_label), alpha=self.alpha))

        # 显示项目：做成折叠区（跟「重新框选」一个样子），点开就地勾选
        self.slot_switches = {}
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 2, 0, 0)
        bv.setSpacing(4)
        for key, name in (("slot1", "💰 摩拉"), ("slot2", "⚔ 材料"), ("slot3", "💠 狗粮")):
            r = QHBoxLayout()
            lb = QLabel(name)
            lb.setStyleSheet(label_qss(T.TEXT, 14))
            sw = Switch(body, bool(bar.get("show_" + key, True)))
            sw.toggled.connect(lambda v, k=key: self._on_slots_changed())
            r.addWidget(lb)
            r.addStretch(1)
            r.addWidget(sw)
            bv.addLayout(r)
            self.slot_switches[key] = sw
        self.slot_acc = Accordion(self, "📶", "显示项目",
                                  "点开勾选要显示的格子（改完立即生效）",
                                  body, alpha=self.alpha)
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
        txt = "关闭统计条" if self.win.bar_window is not None else "📶 打开统计条"
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
        self._open = set()
        self._cards = {}

        head = QHBoxLayout()
        head.addStretch(1)
        self.clear_btn = QPushButton("🗑 清空记录")
        self.clear_btn.setFixedHeight(32)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.clear_btn.clicked.connect(self._on_clear)
        head.addWidget(self.clear_btn)
        self.v.addLayout(head)

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

        self.empty_label = QLabel("（还没有记录）\n点「开始监测」跑一段时间，再点「停止监测」，就会生成一条。")
        self.empty_label.setStyleSheet(label_qss(T.DIM, 14))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.rec_list.addWidget(self.empty_label)
        self.rec_list.addStretch(1)

    def on_show(self):
        self.refresh()

    def refresh(self):
        """重建记录列表 —— 这个只在**切到本页**或**停止监测**时发生，
        不是每次数据变化都重建（记录条数本来就很少变）。"""
        import sessions
        items = sessions.load_sessions()
        # 先清空旧卡片（只清卡片，不动布局里的空状态和弹簧）
        for w in list(self._cards.values()):
            self.rec_list.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._cards = {}
        self._open = set()
        self.empty_label.setVisible(not items)
        for idx, item in enumerate(reversed(items)):
            c = self._make_card(idx, item)
            self._cards[idx] = c
            self.rec_list.insertWidget(idx, c)

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

    def _make_card(self, idx, item):
        c = Card(self, alpha=self.alpha)
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        top = QHBoxLayout()
        dur = fmt_duration(item.get("seconds", 0))
        date, t1, t2 = self._when_parts(item)
        # 日期 + 时间段，一眼能看出这段是几点到几点挂的
        when = f"📅 {date}" if date else "📅 ——"
        if t1:
            when += f"　⏱ {t1}"
            if t2:
                when += f" → {t2}"
        t = QLabel(f"{when}　　时长 {dur}")
        t.setStyleSheet(label_qss(T.TEXT, 14, True))
        top.addWidget(t)
        top.addStretch(1)
        btn = QPushButton("查看明细 ▾")
        btn.setFixedHeight(26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(btn_qss("normal", self.alpha))
        top.addWidget(btn)
        v.addLayout(top)

        nums = QHBoxLayout()
        for label, val, color in (("摩拉", f"{item.get('mora', 0):,}", T.ACCENT),
                                  ("狗粮", f"×{item.get('artifact', 0)}", T.ACCENT)):
            lb = QLabel(f"{label} {val}")
            lb.setStyleSheet(label_qss(color, 15, True))
            nums.addWidget(lb)
            nums.addSpacing(20)
        nums.addStretch(1)
        v.addLayout(nums)

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
        detail.setVisible(False)
        v.addWidget(detail)

        def _toggle(_=False, i=idx, d=detail, b=btn):
            if i in self._open:
                self._open.discard(i)
                d.setVisible(False)
                b.setText("查看明细 ▾")
            else:
                self._open.add(i)
                d.setVisible(True)
                b.setText("收起明细 ▴")
        btn.clicked.connect(_toggle)
        return c

    def _on_clear(self):
        import sessions
        if QMessageBox.question(self, "确认",
                                "确定清空所有收益记录吗？\n（今日统计的数据不受影响）") != QMessageBox.Yes:
            return
        sessions.clear_sessions()
        self.refresh()
        QMessageBox.information(self, "已清空", "收益记录已清空")


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

    TABS = ["外观", "识别", "行为", "统计", "直播", "其它"]

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
        for i, name in enumerate(self.TABS):
            b = QPushButton(name)
            b.setFixedHeight(34)
            b.setMinimumWidth(76)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, x=i: self._on_tab(x))
            bl.addWidget(b)
            self._tab_btns.append(b)
        bl.addStretch(1)
        self.add(bar)

        # ---------- 每个标签一个滚动区 ----------
        self.tabs = QStackedWidget()
        self._inner = {}
        self._lay = {}
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
        self.add(self.tabs, 1)

        # ---------- 各标签的内容 ----------
        self._build_appearance(s)
        self._build_recognize(s)
        self._build_behavior(s)
        self._build_stats(s)
        self._build_live(s)
        self._build_other(s)

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
        self._row(tb, "🌓", "卡片透明度",
                  "卡片 / 侧边栏 / 按钮统一用这个（0% = 全透明）",
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
        self._row(tb, "🌑", "背景压暗",
                  "背景图太花、字看不清时往右拉（0% = 不压暗）",
                  right_wrap(self.dim_slider, self.dim_label))

        pic = QPushButton("🖼 选择图片")
        clr = QPushButton("✖ 清除")
        for b, kind, cb in ((pic, "normal", self._choose_bg), (clr, "danger", self._clear_bg)):
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
        import os as _os
        cur = s.get("bg_image") or ""
        self.bg_name = QLabel(_os.path.basename(cur) if cur else "未设置（纯色背景）")
        self.bg_name.setStyleSheet(label_qss(T.DIM, 12))
        self._row(tb, "🖼", "自定义背景图片",
                  "选一张图当窗口背景，卡片会变成半透明玻璃",
                  right_wrap(pic, clr, self.bg_name))

        import theme as _theme_mod      # 只为了取预设名字列表
        bg_items = list(getattr(_theme_mod, "BG_PRESETS", {"经典深黑": "#1C1C1C"}).keys())
        ac_items = list(getattr(_theme_mod, "ACCENT_PRESETS", {"经典蓝": "#4CC2FF"}).keys())
        self.bg_dd = self._dd(bg_items)
        self.accent_dd = self._dd(ac_items)
        self.bg_dd.setCurrentText(str(s.get("bg_color", "经典深黑")))
        self.accent_dd.setCurrentText(str(s.get("accent_color", "经典蓝")))
        self.bg_dd.currentTextChanged.connect(self._on_bg_color)
        self.accent_dd.currentTextChanged.connect(self._on_accent_color)
        self._row(tb, "🎨", "背景颜色", "窗口背景色（改完立即生效）", self.bg_dd)
        self._row(tb, "🌈", "强调色",
                  "按钮、选中项、数字高亮的颜色（改完立即生效）", self.accent_dd)

        self.sidebar_glass = Switch(self._inner[tb], bool(s.get("sidebar_glass", True)))
        self.sidebar_glass.toggled.connect(self._on_sidebar_glass)
        self._row(tb, "🌫", "左侧栏毛玻璃效果",
                  "需要先设置背景图片（模糊+压暗，模拟磨砂质感）", self.sidebar_glass)

        # 「统计条图标」放在这里（从「直播」挪过来的）
        icon_btn = QPushButton("打开图标管理")
        icon_btn.setFixedHeight(34)
        icon_btn.setCursor(Qt.PointingHandCursor)
        icon_btn.setStyleSheet(btn_qss("normal", self.alpha))
        icon_btn.clicked.connect(self.win.open_icon_manager)
        self._row(tb, "🖼", "统计条图标",
                  "换收益统计条三个格子的图标（摩拉/材料/狗粮）", icon_btn)

    # ================= 识别 =================
    def _build_recognize(self, s):
        tb = "识别"
        self.tick_entry = QLineEdit(str(s.get("tick_interval", 50)))
        self.tick_entry.setFixedWidth(90)
        self.tick_entry.setAlignment(Qt.AlignCenter)
        self.tick_entry.setStyleSheet(entry_qss())
        self.tick_entry.editingFinished.connect(self._on_tick)
        self._row(tb, "⏱", "检测间隔",
                  "每多少毫秒检查一次画面（10~5000，默认 50）", self.tick_entry)

        # 文字识别频率：性能 / 标准 / 省电 / 极致省电（越小越频繁）
        self.ocr_dd = self._dd([name for name, _v in config_manager.OCR_LEVELS])
        self.ocr_dd.setCurrentText(
            level_name(config_manager.OCR_LEVELS,
                       int(s.get("ocr_interval", 150) or 150), config_manager.DEFAULT_OCR_LEVEL))
        self.ocr_dd.currentTextChanged.connect(self._on_ocr_interval)
        self._row(tb, "🔍", "文字识别频率",
                  "越快响应越及时，越慢越省电（默认「标准」）", self.ocr_dd)

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
        self._row(tb, "🎚", "画面变化灵敏度",
                  "越灵敏识别越快，越灵敏也越耗电（默认「标准」）", self.change_dd)

        ev = str(s.get("event_end_window", 1.5)).replace("秒", "").strip()
        self.event_dd = self._dd(["1.0 秒", "1.5 秒", "2.5 秒"])
        self.event_dd.setCurrentText((f"{ev} 秒" if f"{ev} 秒" in ("1.0 秒", "1.5 秒", "2.5 秒")
                                      else "1.5 秒"))
        self.event_dd.currentTextChanged.connect(self._on_event_window)
        self._row(tb, "🔁", "防重复窗口",
                  "同一提示消失多久后再出现才算新掉落（默认 1.5 秒）", self.event_dd)

        # 识别哪几样：折叠区（跟「重新框选」一个样子）
        box = QWidget()
        bl2 = QVBoxLayout(box)
        bl2.setContentsMargins(0, 2, 0, 0)
        bl2.setSpacing(4)
        self.kind_switches = {}
        for key, name in (("enable_mora", "💰 摩拉"),
                          ("enable_material", "⚔ 材料"),
                          ("enable_artifact", "💠 狗粮")):
            r = QHBoxLayout()
            lb = QLabel(name)
            lb.setStyleSheet(label_qss(T.TEXT, 14))
            sw = Switch(box, bool(s.get(key, True)))
            sw.toggled.connect(lambda v, k=key: self._on_kinds_changed(k, v))
            r.addWidget(lb)
            r.addStretch(1)
            r.addWidget(sw)
            bl2.addLayout(r)
            self.kind_switches[key] = sw
        self.kind_acc = Accordion(self._inner[tb], "🎯", "识别哪几样",
                                  "", box, alpha=self.alpha)
        self._lay[tb].insertWidget(self._lay[tb].count() - 1, self.kind_acc)
        self._sync_kind_desc()

    def _sync_kind_desc(self):
        names = [n for k, n in (("enable_mora", "摩拉"), ("enable_material", "材料"),
                                ("enable_artifact", "狗粮"))
                 if self.kind_switches[k].isChecked()]
        self.kind_acc.desc_label.setText(
            f"当前识别：{'、'.join(names) if names else '（都不识别）'}"
            "　·　点开勾选，不想统计的直接关掉")

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
        self._row(tb, "🎯", "只在原神前台时识别",
                  "切到别的应用就暂停，回到原神自动继续", self.only_fg)

        self.close_dd = self._dd(["每次询问", "最小化到托盘", "直接退出"])
        self.close_dd.setCurrentText({
            "ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"
        }.get(str(s.get("close_behavior", "ask")), "每次询问"))
        self.close_dd.currentTextChanged.connect(self._on_close_behavior)
        self._row(tb, "✖", "点右上角 ✕ 时", "关闭窗口时的行为", self.close_dd)

        # 热键可以有多个动作 —— 每个动作一个按钮。
        # _hotkey_btns 记着「设置里的键名 -> 按钮」，录制的时候按名字找按钮。
        self._hotkey_btns = {}
        self._capturing = None
        for key, icon, title, desc in (
                ("hotkey", "⌨", "热键：开始 / 停止监测",
                 "点按钮后按下想用的键（Esc 取消）"),
                ("hotkey_bar", "⌨", "热键：显示 / 隐藏统计条",
                 "再按一次就收起。不想用就留「关闭」"),
                ("hotkey_home", "⌨", "热键：显示主窗口",
                 "窗口最小化到托盘后，按一下叫回来")):
            btn = QPushButton(str(s.get(key, "关闭")))
            btn.setFixedSize(140, 32)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(btn_qss("normal", self.alpha))
            btn.clicked.connect(lambda _=False, k=key: self._start_hotkey_capture(k))
            self._hotkey_btns[key] = btn
            self._row(tb, icon, title, desc, btn)

    # ================= 统计 =================
    def _build_stats(self, s):
        tb = "统计"
        self.ro_entry = QLineEdit(str(int(s.get("rollover_hour", 0) or 0)))
        self.ro_entry.setFixedWidth(70)
        self.ro_entry.setAlignment(Qt.AlignCenter)
        self.ro_entry.setStyleSheet(entry_qss())
        self.ro_entry.editingFinished.connect(self._on_rollover)
        ro = right_wrap(self.ro_entry)
        lb = QLabel("点")
        lb.setStyleSheet(label_qss(T.DIM, 13))
        ro.layout().addWidget(lb)
        self._row(tb, "🌅", "换日时间",
                  "填 0~23。挂机挂过零点的话，往后填几小时就不会中途归零", ro)

        # 「自动登记新材料」放在这里（从「识别」挪过来的）
        self.auto_reg = Switch(self._inner[tb], bool(s.get("auto_register_material", True)))
        self.auto_reg.toggled.connect(
            lambda v: self.state.set_setting("auto_register_material", bool(v)))
        self._row(tb, "➕", "自动登记新材料",
                  "遇到材料库里没有的名字时自动加进材料库", self.auto_reg)

    # ================= 直播 =================
    def _build_live(self, s):
        tb = "直播"
        self.obs_sw = Switch(self._inner[tb], bool(s.get("obs_browser_source", False)))
        self.obs_sw.toggled.connect(self._on_obs)
        api_port = int(s.get("api_port", 8765) or 8765)
        self.obs_addr = QLabel(f"http://127.0.0.1:{api_port}/overlay")
        self.obs_addr.setStyleSheet(label_qss(T.TEXT, 13))
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(60, 28)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(btn_qss("normal", self.alpha))
        copy_btn.clicked.connect(self._copy_obs)
        self._row(tb, "📺", "连接 OBS 直播覆盖",
                  "在 OBS 里添加「浏览器源」，粘贴右边地址",
                  right_wrap(self.obs_sw, self.obs_addr, copy_btn))

        # 「直播接口端口」放在这里（从「统计」挪过来的）
        self.api_entry = QLineEdit(str(api_port))
        self.api_entry.setFixedWidth(90)
        self.api_entry.setAlignment(Qt.AlignCenter)
        self.api_entry.setStyleSheet(entry_qss())
        self.api_entry.editingFinished.connect(self._on_api_port)
        self._row(tb, "🔌", "直播接口端口",
                  "OBS 用这个端口取数据（改完要重启程序才生效）", self.api_entry)

    # ================= 其它 =================
    def _build_other(self, s):
        tb = "其它"

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
        self._row(tb, "🌐", "更新渠道",
                  "从哪个渠道查更新和打开下载页（国内选 Gitee 更快）",
                  self.channel_dd)

        # ---- 检测更新 ----
        upd_row = QWidget()
        ul = QHBoxLayout(upd_row)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(8)
        self.update_btn = QPushButton("🔍 检测更新")
        self.update_btn.setFixedSize(130, 32)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.update_btn.clicked.connect(self._on_check_update)
        self.update_status = QLabel("")
        self.update_status.setStyleSheet(label_qss(T.DIM, 12))
        ul.addWidget(self.update_btn)
        ul.addWidget(self.update_status)
        self._row(tb, "🔄", "版本更新",
                  f"当前版本 v{VERSION}（检测需要联网）", upd_row)

        self.dev_enabled = Switch(self._inner[tb], bool(s.get("developer_mode", False)))
        self.dev_enabled.toggled.connect(self._on_developer_mode)
        self._row(tb, "🛠", "开发者模式",
                  "打开后才显示下面的样本采集工具", self.dev_enabled)

        self.dev_body = self._make_dev_body(self._inner[tb])
        self.dev_row = self._row(tb, "🧪", "开发者选项",
                                 "本地 AI 样本采集（截图只存本地，不上传、不进 Git）",
                                 self.dev_body, height=200)
        self.dev_row.setVisible(bool(s.get("developer_mode", False)))

    # ---------- 开发者选项 ----------
    def _make_dev_body(self, parent):
        from dataset_collector import DEFAULT_PATH
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(6)

        # 注意：DatasetCollector 读的键是 dataset_enabled，
        # 不是 dataset_collect —— 键名写错了这个开关就是空的。
        self.dev_switch = Switch(box, bool(self.state.get_setting("dataset_enabled", False)))
        self.dev_switch.toggled.connect(
            lambda v: self.state.set_setting("dataset_enabled", bool(v)))
        r = QHBoxLayout()
        lb = QLabel("启用样本采集")
        lb.setStyleSheet(label_qss(T.TEXT, 14))
        r.addWidget(lb)
        r.addStretch(1)
        r.addWidget(self.dev_switch)
        v.addLayout(r)

        p = self.state.get_setting("dataset_path", "") or str(DEFAULT_PATH)
        self.dev_path_label = QLabel(p)
        self.dev_path_label.setStyleSheet(label_qss(T.DIM, 12))
        self.dev_path_label.setWordWrap(True)
        browse = QPushButton("浏览…")
        browse.setFixedHeight(28)
        browse.setCursor(Qt.PointingHandCursor)
        browse.setStyleSheet(btn_qss("normal", self.alpha))
        browse.clicked.connect(self._on_choose_dataset_path)
        r2 = QHBoxLayout()
        r2.addWidget(self.dev_path_label, 1)
        r2.addWidget(browse)
        v.addLayout(r2)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        for text, cb in (("打开文件夹", self._on_open_dataset),
                         ("清空样本", self._on_clear_dataset)):
            b = QPushButton(text)
            b.setFixedHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss("normal", self.alpha))
            b.clicked.connect(cb)
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)

        self.dev_stats_label = QLabel("")
        self.dev_stats_label.setStyleSheet(label_qss(T.DIM, 12))
        v.addWidget(self.dev_stats_label)
        self._refresh_dev_stats()
        return box

    def _on_developer_mode(self, v):
        self.state.set_setting("developer_mode", bool(v))
        self.dev_row.setVisible(bool(v))
        if v:
            self._refresh_dev_stats()

    def _refresh_dev_stats(self):
        try:
            from dataset_collector import DatasetCollector
            st = DatasetCollector(self.state.settings).stats()
            self.dev_stats_label.setText(
                f"GAMEPLAY：{st.get('gameplay', 0)}    "
                f"NON_GAMEPLAY：{st.get('non_gameplay', 0)}    "
                f"总样本：{st.get('total', 0)}\n"
                f"占用：{st.get('size_mb', 0)} MB / {st.get('max_mb', 100)} MB")
        except Exception:
            self.dev_stats_label.setText("（无法读取样本统计）")

    def _on_choose_dataset_path(self):
        d = QFileDialog.getExistingDirectory(self, "选择样本保存位置")
        if not d:
            return
        self.state.set_setting("dataset_path", d)
        self.dev_path_label.setText(d)

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
            tip = QLabel("点「立即更新」会自动下载并替换好，全程不用管：\n"
                         "软件先自己关掉 → 自动替换 → 自动重新打开。\n"
                         "你的设置和收益数据不会被覆盖。")
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
                                    f"{err}\n\n不影响现在这个版本，可以稍后再试，"
                                    "或者点「打开下载页」手动下载。")
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
                    "  · 自动完成替换（会弹一个黑窗口，**别关它**）\n"
                    "  · 更新完自动重新打开\n\n"
                    "你的设置和收益数据不会被覆盖。\n\n现在就开始更新吗？"
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

    def _choose_bg(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not p:
            return
        try:
            from PIL import Image
            Image.open(p).verify()
        except Exception:
            QMessageBox.warning(self, "失败", "这个文件不是有效的图片，请重新选择。")
            return
        self.state.set_setting("bg_image", p)
        import os as _os
        self.bg_name.setText(_os.path.basename(p))
        self.win.set_background_image(p)
        QMessageBox.information(self, "成功", "背景图片已应用。")

    def _clear_bg(self):
        self.state.set_setting("bg_image", "")
        self.bg_name.setText("未设置（纯色背景）")
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

    def _on_api_port(self):
        try:
            v = max(1024, min(65535, int(self.api_entry.text().strip())))
        except Exception:
            v = 8765
        self.api_entry.setText(str(v))
        self.state.set_setting("api_port", v)

    def _on_close_behavior(self, text):
        self.state.set_setting("close_behavior", {
            "每次询问": "ask", "最小化到托盘": "tray", "直接退出": "exit"}.get(text, "ask"))

    def _on_obs(self, v):
        self.state.set_setting("obs_browser_source", bool(v))
        self.win.set_obs(bool(v))

    def _copy_obs(self):
        from PySide6.QtWidgets import QApplication as _A
        _A.clipboard().setText(self.obs_addr.text())
        QMessageBox.information(self, "已复制",
                                f"OBS 浏览器源地址已复制：\n{self.obs_addr.text()}")

    def _on_sidebar_glass(self, v):
        self.state.set_setting("sidebar_glass", bool(v))
        self.win.set_sidebar_glass(bool(v))

    # ---------- 背景色 / 强调色：改完立即生效 ----------
    def _apply_colors(self, key, value):
        self.state.set_setting(key, value)
        T.reload_colors(self.state.settings)
        self.win.rebuild_ui()
        QMessageBox.information(self, "已应用", f"颜色已切换为「{value}」。")

    def _on_bg_color(self, v):
        if getattr(self, "_colors_ready", False):
            self._apply_colors("bg_color", v)

    def _on_accent_color(self, v):
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
                    f"「{name}」已经分配给另一个动作了，换一个键吧。")
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
        self.refresh_btn = QPushButton("↻ 刷新")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setStyleSheet(btn_qss("normal", self.alpha))
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
        acc = Accordion(self, "📢", str(n.get("title", "")), desc, body,
                        alpha=self.alpha)

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
        self.refresh_btn.setText("↻ 刷新")
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
       （「今日统计」原来是单独一页，现在并进启动页的折叠区了）"""
    return [PageLaunch(win), PageBar(win),
            PageRecords(win), PageSettings(win), PageNotice(win)]


# 公告页在栈里的下标（侧栏那个「公告」按钮要用）
NOTICE_PAGE_INDEX = 4
