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
                               QStackedWidget, QDialog, QTextEdit)

from qt_theme import (panel_alpha, label_qss, btn_qss, entry_qss, combo_qss,
                      slider_qss, scroll_qss, rgba)
import qt_theme as T
import config_manager
from qt_widgets import (Card, SettingRow, Switch, Accordion, ButtonRow, heading,
                        level_name, level_value)

VERSION = "0.9"

# 检测更新用的仓库。注意这个仓库改过两次名：
#   genshin-income-tracker（最早的旧名，**已经不存在了**，Tk 版就错在这儿）
#   StatGI（别名，会 301 重定向到下面这个）
#   stat-genshin-impact（现在的真名）
# 用真名可以少一次重定向，更稳。
UPDATE_REPO = "Cash-553/stat-genshin-impact"


def version_tuple(s):
    """'0.10-beta' -> (0, 10)   只取版本号前面的数字段"""
    import re
    head = str(s or "").split("-")[0].split("+")[0]
    nums = re.findall(r"\d+", head)
    return tuple(int(x) for x in nums) if nums else ()


def is_newer_version(latest, current):
    """latest 是不是真的比 current 新

    为什么不能直接用 != 比较：GitHub 上最新发布可能是 v0.7，而本地已经
    跑到 v0.8 了 —— 用 != 的话会把**老版本**当新版本弹出来。
    另外字符串比较下 "0.10" < "0.9"，按数字比才是对的。
    """
    a, b = version_tuple(latest), version_tuple(current)
    if not a or not b:
        return str(latest) != str(current)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


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

        # ---- 公告卡片 ----
        # 只有真的有公告时才显示；没读过的话右边带个红点。
        # 拉不到公告就整张卡片藏起来，什么都不说（公告是锦上添花，不能打扰人）。
        # 标题放在卡片说明栏里（那是它该在的地方），右边只留红点 + 按钮。
        self.notice = None
        spot = QWidget()
        sl = QHBoxLayout(spot)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        self.notice_dot = QLabel("●")
        self.notice_dot.setStyleSheet(label_qss("#E06C5A", 12))
        self.notice_btn = QPushButton("查看 ▸")
        self.notice_btn.setFixedSize(96, 32)
        self.notice_btn.setCursor(Qt.PointingHandCursor)
        self.notice_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.notice_btn.clicked.connect(self._show_notice)
        sl.addWidget(self.notice_dot)
        sl.addWidget(self.notice_btn)
        self.notice_row = SettingRow(
            self, "📢", "公告", "", spot, alpha=self.alpha, height=70)
        self.notice_row.setVisible(False)
        self.add(self.notice_row)

        self._refresh_notice()

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
        self.stretch()

        # 订阅状态：文字变了才改，**不重建控件**
        self.state.status_changed.connect(self._on_status)
        self.state.event_happened.connect(self._on_event)
        self.state.stats_changed.connect(self._sync_button)

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

    def _refresh_notice(self):
        """显示公告卡片。

        优先级：远程拉到的（缓存在 data/notice_cache.json）> 程序内置的那份。
        两个都没有就藏起来 —— 什么都不做，不弹错。
        """
        import qt_notice
        n = qt_notice.load_cached() or qt_notice.load_builtin()
        self.set_notice(n)

    def set_notice(self, n):
        self.notice = n
        if not n:
            self.notice_row.setVisible(False)
            return
        self.notice_row.setVisible(True)
        import qt_notice
        unread = qt_notice.is_unread(n, self.state.settings)
        self.notice_dot.setVisible(unread)
        # 标题放说明栏里，太长就截断（完整内容点「查看」能看到）
        # 未读小红点只留右边那一个 —— 放两处反而乱
        title = str(n.get("title", "公告"))
        if len(title) > 34:
            title = title[:33] + "…"
        self.notice_row.set_text(desc=title)
        self.notice_btn.setText("查看 ▸")

    def _show_notice(self):
        if not self.notice:
            return
        import qt_notice
        n = self.notice
        dlg = QDialog(self.win)
        dlg.setWindowTitle("公告")
        dlg.setMinimumWidth(520)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        t = QLabel(str(n.get("title", "公告")))
        t.setStyleSheet(label_qss(T.ACCENT, 18, True))
        t.setWordWrap(True)
        v.addWidget(t)

        body = QTextEdit()
        body.setPlainText(str(n.get("body", "")))
        body.setReadOnly(True)
        body.setMinimumHeight(200)
        body.setStyleSheet(
            f"QTextEdit {{ background: {rgba('#FFFFFF', 18)}; color: {T.TEXT};"
            f" border: none; border-radius: 8px; padding: 10px;"
            f" font-family: 'Microsoft YaHei UI'; font-size: 13px; }}")
        v.addWidget(body, 1)

        row = QHBoxLayout()
        url = str(n.get("url", "") or "").strip()
        if url:
            b_open = QPushButton("打开链接")
            b_open.setFixedHeight(32)
            b_open.setCursor(Qt.PointingHandCursor)
            b_open.setStyleSheet(btn_qss("accent", self.alpha))
            b_open.clicked.connect(lambda: __import__("webbrowser").open(url))
            row.addWidget(b_open)
        row.addStretch(1)
        b_ok = QPushButton("知道了")
        b_ok.setFixedSize(100, 32)
        b_ok.setCursor(Qt.PointingHandCursor)
        b_ok.setStyleSheet(btn_qss("normal", self.alpha))
        b_ok.clicked.connect(dlg.accept)
        row.addWidget(b_ok)
        v.addLayout(row)

        # 打开就算读过了（记下 id，下次不再显示红点）
        qt_notice.mark_read(n, self.state.settings,
                            lambda s: self.state.set_setting("last_read_notice", n.get("id", "")))
        self.notice_dot.setVisible(False)
        dlg.exec()

    def on_show(self):
        self._sync_button()
        self._refresh_notice()

    def on_show(self):
        pass


# ============================================================
#  今日统计
# ============================================================
class PageHome(BasePage):
    title = "今日统计"

    def __init__(self, win):
        super().__init__(win)

        # 三个数字卡片
        row = QHBoxLayout()
        row.setSpacing(10)
        self.num_labels = {}
        for key, title, unit in (("mora", "💰 今日摩拉", ""),
                                 ("artifact", "💠 狗粮（圣遗物）", "×"),
                                 ("time", "⏱ 监测时间", "")):
            c = Card(self, alpha=self.alpha)
            v = QVBoxLayout(c)
            v.setContentsMargins(16, 14, 16, 14)
            v.setSpacing(6)
            lb = QLabel(title)
            lb.setStyleSheet(label_qss(T.DIM, 13))
            val = QLabel("0")
            val.setStyleSheet(label_qss(T.ACCENT, 26, True))
            v.addWidget(lb)
            v.addWidget(val)
            self.num_labels[key] = val
            row.addWidget(c)
        self.v.addLayout(row)

        # 材料列表（滚动）
        c = Card(self, alpha=self.alpha)
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        t = QLabel("📦 材料")
        t.setStyleSheet(label_qss(T.TEXT, 15, True))
        self.detail_btn = QPushButton("查看明细")
        self.detail_btn.setFixedHeight(28)
        self.detail_btn.setCursor(Qt.PointingHandCursor)
        self.detail_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.detail_btn.clicked.connect(self._toggle_detail)
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(self.detail_btn)
        v.addLayout(head)

        self.mat_scroll = QScrollArea()
        self.mat_scroll.setWidgetResizable(True)
        self.mat_scroll.setFrameShape(QFrame.NoFrame)
        self.mat_scroll.setStyleSheet(scroll_qss())
        self.mat_scroll.viewport().setAutoFillBackground(False)
        self.mat_inner = QWidget()
        self.mat_inner.setStyleSheet("background: transparent;")
        self.mat_list = QVBoxLayout(self.mat_inner)
        self.mat_list.setContentsMargins(0, 0, 0, 0)
        self.mat_list.setSpacing(2)
        self.mat_scroll.setWidget(self.mat_inner)

        # 明细视图（默认藏起来，点「查看明细」才显示）
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_scroll.setStyleSheet(scroll_qss())
        self.detail_scroll.viewport().setAutoFillBackground(False)
        d_inner = QWidget()
        d_inner.setStyleSheet("background: transparent;")
        self.detail_list = QVBoxLayout(d_inner)
        self.detail_list.setContentsMargins(0, 0, 0, 0)
        self.detail_list.setSpacing(2)
        self.detail_scroll.setWidget(d_inner)
        self.detail_scroll.hide()
        self.detail_rows = []
        self._detail_shown = False

        v.addWidget(self.mat_scroll, 1)
        v.addWidget(self.detail_scroll, 1)
        self.add(c, 1)

        # 空状态提示（只有真的没材料时才显示）
        self.empty_label = QLabel("（暂无，开始监测后自动统计）")
        self.empty_label.setStyleSheet(label_qss(T.DIM, 14))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.mat_list.addWidget(self.empty_label)
        self.mat_list.addStretch(1)

        # 增量更新用的缓存：材料名 -> (整行控件, 数量标签)
        self._rows = {}
        self._last_txt = {}          # 上一次写进标签的文字，一样就不写
        self._stale = False          # 不可见期间漏掉的刷新

        self.state = win.state
        self.state.stats_changed.connect(self.refresh)

    # ---------- 刷新：只改变化的部分 ----------
    def refresh(self):
        # **看不见的页面一律不刷** —— 数据在别的页变了也不该动这里的控件。
        # 记个脏标记，等它重新显示时（showEvent）再补一次。
        if not self.isVisible():
            self._stale = True
            return
        self._stale = False
        snap = self.state.snapshot()
        self._set_num("mora", f"{snap['mora']:,}")
        self._set_num("artifact", f"×{snap['artifact']}")
        self._set_num("time", fmt_seconds(snap["seconds"]))
        self._update_materials(snap["materials"])

    def showEvent(self, e):
        """重新显示出来时，如果之前有漏刷就补一次"""
        super().showEvent(e)
        if getattr(self, "_stale", False):
            self.refresh()

    def _set_num(self, key, text):
        lb = self.num_labels.get(key)
        if lb is None:
            return
        if self._last_txt.get(key) == text:      # 文字没变 -> 一个字都不动
            return
        self._last_txt[key] = text
        lb.setText(text)

    def _update_materials(self, merged):
        """材料列表：只增删改变化的那几行，**绝不整表重建**"""
        names = set(merged)
        # 1) 删掉已经没有的
        for name in list(self._rows):
            if name not in names:
                row, _lb = self._rows.pop(name)
                self.mat_list.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
        # 2) 新增 / 更新数量
        items = sorted(merged.items(), key=lambda kv: -kv[1])
        for i, (name, count) in enumerate(items):
            txt = f"×{count}"
            item = self._rows.get(name)
            if item is None:
                row, lb = self._make_mat_row(name, txt)
                self._rows[name] = (row, lb)
            else:
                row, lb = item
                if lb.text() != txt:             # 只有数量变了才写
                    lb.setText(txt)
            # 顺序变了才挪位置（挪控件很便宜，不重建）
            if self.mat_list.indexOf(row) != i:
                self.mat_list.insertWidget(i, row)
        # 3) 空状态
        self.empty_label.setVisible(len(items) == 0)

    def _make_mat_row(self, name, txt):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(6, 2, 6, 2)
        n = QLabel(name)
        n.setStyleSheet(label_qss(T.TEXT, 14))
        c = QLabel(txt)
        c.setStyleSheet(label_qss(T.ACCENT, 14, True))
        lay.addWidget(n)
        lay.addStretch(1)
        lay.addWidget(c)
        return row, c

    # ---------- 查看明细：简要列表 / 完整明细 就地切换 ----------
    def _toggle_detail(self):
        self._detail_shown = not getattr(self, "_detail_shown", False)
        if self._detail_shown:
            self.mat_scroll.hide()
            self.detail_scroll.show()
            self.detail_btn.setText("收起明细")
            self._rebuild_detail()
        else:
            self.detail_scroll.hide()
            self.mat_scroll.show()
            self.detail_btn.setText("查看明细")

    def _rebuild_detail(self):
        """明细 = 特殊材料 + 普通材料分开列（只在切到明细时重建一次）"""
        for w in self.detail_rows:
            self.detail_list.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self.detail_rows = []
        snap = self.state.snapshot()
        mats = snap["materials"]
        normal = getattr(self.state.stats, "normal_materials", {}) or {}
        groups = [("✦ 特殊材料 / 圣遗物", {k: v for k, v in mats.items() if k not in normal}),
                  ("◆ 普通材料", dict(normal))]
        for title, data in groups:
            head = QLabel(f"{title}   共 {sum(data.values())} 个")
            head.setStyleSheet(label_qss(T.ACCENT, 14, True))
            self.detail_list.addWidget(head)
            self.detail_rows.append(head)
            if not data:
                lb = QLabel("（无）")
                lb.setStyleSheet(label_qss(T.DIM, 13))
                self.detail_list.addWidget(lb)
                self.detail_rows.append(lb)
            for name, cnt in sorted(data.items(), key=lambda kv: -kv[1]):
                r, _c = self._make_mat_row(name, f"×{cnt}")
                self.detail_list.addWidget(r)
                self.detail_rows.append(r)
        self.detail_list.addStretch(1)

    def on_show(self):
        self.state.force_refresh()



# ============================================================
#  收益统计条
# ============================================================
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

    def _make_card(self, idx, item):
        c = Card(self, alpha=self.alpha)
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        top = QHBoxLayout()
        dur = fmt_duration(item.get("seconds", 0))
        t = QLabel(f"⏱ {item.get('date', '')}  {item.get('time', '')}   时长 {dur}")
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

        self.hotkey_btn = QPushButton(str(s.get("hotkey", "关闭")))
        self.hotkey_btn.setFixedSize(140, 32)
        self.hotkey_btn.setCursor(Qt.PointingHandCursor)
        self.hotkey_btn.setStyleSheet(btn_qss("normal", self.alpha))
        self.hotkey_btn.clicked.connect(self._start_hotkey_capture)
        self._row(tb, "⌨", "全局热键（开始/停止监测）",
                  "点按钮后按下想用的键（Esc 取消）", self.hotkey_btn)

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

        def _do():
            latest = url = None
            try:
                import urllib.request
                import json as _json
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                    headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                tag = str(data.get("tag_name", "")).strip()
                # 只去掉开头的那个 v（lstrip("v") 会把开头的所有 v 都吃掉）
                latest = tag[1:] if tag[:1].lower() == "v" else tag
                url = data.get("html_url", f"https://github.com/{UPDATE_REPO}/releases")
            except Exception:
                latest = None
            # 发信号回主线程 —— 后台线程绝对不能直接碰控件
            self.update_checked.emit(latest, url)

        threading.Thread(target=_do, daemon=True).start()

    def _update_result(self, latest, url):
        if latest is None:
            self.update_status.setText("检测失败（需联网）")
            self.update_status.setStyleSheet(label_qss("#E06C5A", 12))
            return
        if not latest:
            self.update_status.setText("未获取到版本信息")
            self.update_status.setStyleSheet(label_qss(T.DIM, 12))
            return
        if not is_newer_version(latest, VERSION):
            # 远端不比本地新（包括远端更旧的情况）—— 都算「已是最新」
            self.update_status.setText(f"已是最新版本（{VERSION}）")
            self.update_status.setStyleSheet(label_qss("#6CCB5F", 12))
            return
        self.update_status.setText(f"发现新版本 {latest}")
        self.update_status.setStyleSheet(label_qss(T.ACCENT, 12))
        if QMessageBox.question(
                self, "发现新版本",
                f"当前版本 {VERSION}\n最新版本 {latest}\n\n是否打开下载页面？"
        ) == QMessageBox.Yes:
            import webbrowser
            webbrowser.open(url)

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
    def _start_hotkey_capture(self):
        self._capturing = True
        self.hotkey_btn.setText("请按下按键…（Esc 取消）")
        self.setFocus()

    def _on_key_press(self, e):
        if not self._capturing:
            return
        self._capturing = False
        k = e.key()
        if k == Qt.Key_Escape:
            self.hotkey_btn.setText(str(self.state.settings.get("hotkey", "关闭")))
            return
        name = _qt_key_name(e)
        if name is None:
            self.hotkey_btn.setText(str(self.state.settings.get("hotkey", "关闭")))
            return
        self.state.set_setting("hotkey", name)
        self.hotkey_btn.setText(name)

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
    return [PageLaunch(win), PageHome(win), PageBar(win),
            PageRecords(win), PageSettings(win)]
