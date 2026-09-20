# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 主窗口

三件事，在 Tk 里每一件都是大工程，在这里都是现成的：
  1. 无边框 + 真圆角（WA_TranslucentBackground + 画圆角路径，带抗锯齿）
  2. 背景图铺底 + 卡片半透明（卡片是 rgba，Qt 自己混合）
  3. 侧边栏磨砂（把背景图那块缩小再放大 = 便宜模糊）

背景图 / 背景色 / 强调色 / 面板透明度 全部来自
config/settings.json —— 跟 Tk 版共用同一份设置。
"""
import os

from PySide6.QtCore import Qt, QRectF, QRect, QPoint, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QColor, QIcon
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QStackedWidget, QMessageBox)

import config_manager
import paths
from qt_pages import NOTICE_PAGE_INDEX
from qt_theme import (HEADER, RADIUS_WINDOW, panel_alpha, label_qss, rgba,
                      btn_qss)
import qt_theme as T


# ---------- 背景图工具 ----------
def _cover(pm, w, h):
    """把图裁成铺满 w×h（居中裁剪）= CSS 的 cover"""
    if w <= 0 or h <= 0 or pm.isNull():
        return pm
    s = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return s.copy((s.width() - w) // 2, (s.height() - h) // 2, w, h)


def _blur(pm, factor=10):
    """便宜模糊：缩小再放大。够用，而且不慢。"""
    if pm.isNull():
        return pm
    w, h = max(1, pm.width()), max(1, pm.height())
    small = pm.scaled(max(1, w // factor), max(1, h // factor),
                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def load_background(settings):
    """背景图：设置了 bg_image 就用图；**没设置就返回空 = 走纯色背景**

    （以前没设图时会自己画一张渐变图，现在不要了 —— 直接用主题的背景色。）
    """
    p = settings.get("bg_image")
    if p and os.path.exists(p):
        pm = QPixmap(p)
        if not pm.isNull():
            return pm
    return QPixmap()          # 空 = 纯色背景


# ============================================================
#  标题条
# ============================================================
class TitleBar(QFrame):
    def __init__(self, win, title="StatGI", subtitle=""):
        super().__init__(win)
        self.win = win
        self._drag = None
        self.setFixedHeight(46)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(HEADER, 190)};"
            f" border-top-left-radius: {RADIUS_WINDOW}px;"
            f" border-top-right-radius: {RADIUS_WINDOW}px; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.setSpacing(0)

        ico = QLabel("🍃")
        ico.setStyleSheet("font-size:16px;")
        lay.addWidget(ico)
        lay.addSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(label_qss(T.TEXT, 14, True))
        lay.addWidget(self.title_label)
        lay.addSpacing(14)
        self.sub_label = QLabel(subtitle)
        self.sub_label.setStyleSheet(label_qss(T.DIM, 12))
        lay.addWidget(self.sub_label)
        lay.addStretch(1)

        for text, cb, danger in (("—", self.win.showMinimized, False),
                                 ("✕", self.win.close, True)):
            b = QPushButton(text)
            b.setFixedSize(42, 30)
            b.setCursor(Qt.PointingHandCursor)
            hover = "#C0392B" if danger else "#3A3A3A"
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{T.TEXT}; border:none;"
                f" border-radius:6px; font-size:13px; }}"
                f"QPushButton:hover {{ background:{hover}; }}")
            b.clicked.connect(cb)
            lay.addWidget(b)

    # 按住标题条拖动窗口（子控件不会把鼠标事件冒泡给主窗口，所以写在这里）
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.win.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None


# ============================================================
#  左侧栏（磨砂玻璃）
# ============================================================
class Sidebar(QFrame):
    def __init__(self, win, items, on_select):
        super().__init__(win)
        self.win = win
        self.setFixedWidth(190)
        self._blur = None
        self._glass = bool((win.state.settings or {}).get("sidebar_glass", True))
        self._items = items
        self._on_select = on_select

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 14)
        lay.setSpacing(4)

        self.buttons = []
        for i, (icon, name) in enumerate(items):
            b = QPushButton(f"  {icon}   {name}")
            b.setFixedHeight(40)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self._on_select(idx))
            lay.addWidget(b)
            self.buttons.append(b)

        lay.addStretch(1)

        # ---- 公告（放在导航和版本号之间，做一个独立入口）----
        # 它不是"页面"，点一下是弹窗 —— 所以不参与 set_active 的高亮
        self.notice_btn = QPushButton("  📢   公告")
        self.notice_btn.setFixedHeight(40)
        self.notice_btn.setCursor(Qt.PointingHandCursor)
        self.notice_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{T.TEXT}; border:none;"
            f" border-radius:8px; text-align:left; padding-left:14px;"
            f" font-family:'Microsoft YaHei UI'; font-size:14px; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,28); }}")
        self.notice_btn.clicked.connect(self._on_notice_click)
        lay.addWidget(self.notice_btn)

        # 未读小红点：浮在按钮右上角（做成按钮的子控件，跟着按钮走）
        self.notice_dot = QLabel("●", self.notice_btn)
        self.notice_dot.setStyleSheet(
            "color:#E06C5A; font-size:13px; background:transparent;")
        self.notice_dot.setFixedSize(16, 16)
        self.notice_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.notice_dot.hide()

        v = QLabel("V0.9 · Qt 版")
        v.setStyleSheet(label_qss(T.DIM, 12))
        v.setAlignment(Qt.AlignCenter)
        lay.addWidget(v)

        self.set_active(0)

    def _on_notice_click(self):
        fn = getattr(self.win, "show_notice_page", None)
        if callable(fn):
            fn()

    def set_notice_unread(self, unread):
        """有没有未读公告 —— 有就在公告那一项右上角挂个红点"""
        self.notice_dot.setVisible(bool(unread))
        if unread:
            self._place_dot()
            self.notice_dot.raise_()

    def _place_dot(self):
        """把红点摆在按钮右上角（按钮大小定了之后才准）"""
        b = self.notice_btn
        self.notice_dot.move(max(0, b.width() - 20), 4)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_dot()

    def showEvent(self, e):
        super().showEvent(e)
        self._place_dot()

    def set_active(self, idx):
        for i, b in enumerate(self.buttons):
            active = (i == idx)
            bg = rgba(T.ACCENT, 45) if active else "transparent"
            fg = T.ACCENT if active else T.TEXT
            b.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:{fg}; border:none;"
                f" border-radius:8px; text-align:left; padding-left:14px;"
                f" font-family:'Microsoft YaHei UI'; font-size:14px; }}"
                f"QPushButton:hover {{ background: rgba(255,255,255,28); }}")

    def set_glass(self, on):
        """毛玻璃开关：关掉就不模糊背景图，只压暗"""
        self._glass = bool(on)
        self.refresh_bg()

    def refresh_bg(self):
        self._blur = None
        self.update()

    def paintEvent(self, e):
        # 侧栏 = 背景图上**对应位置**那一块 +（可选）模糊 + 压暗
        #
        # 关键：要从窗口坐标里取自己那一块，不能拿 self.rect()（那是自己的
        # 局部坐标，永远从 0,0 开始）—— 否则背景图会整体上移一个标题条的高度，
        # 看起来就是「侧栏的图错位了」。
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 左下角跟着窗口一起圆角，否则整个窗口的左下角会被切成直角
        r = self.rect()
        path = QPainterPath()
        path.moveTo(r.left(), r.top())
        path.lineTo(r.right() + 1, r.top())
        path.lineTo(r.right() + 1, r.bottom() - RADIUS_WINDOW + 1)
        path.quadTo(r.right() + 1, r.bottom() + 1,
                    r.right() - RADIUS_WINDOW + 1, r.bottom() + 1)
        path.lineTo(r.left() + RADIUS_WINDOW, r.bottom() + 1)
        path.quadTo(r.left(), r.bottom() + 1, r.left(), r.bottom() - RADIUS_WINDOW + 1)
        path.closeSubpath()
        p.setClipPath(path)

        bg = self.win.background()
        if bg.isNull():
            p.fillRect(r, QColor(T.SIDEBAR))
        else:
            if self._blur is None:
                # 自己在窗口里的位置（含标题条高度）
                top_left = self.mapTo(self.win, QPoint(0, 0))
                crop = bg.copy(QRect(top_left.x(), top_left.y(),
                                     self.width(), self.height()))
                self._blur = _blur(crop, 12) if getattr(self, "_glass", True) else crop
            if self._blur is not None:
                p.drawPixmap(0, 0, self._blur)
            p.fillRect(r, QColor(12, 12, 14, 150))
        p.end()


# ============================================================
#  主窗口
# ============================================================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = config_manager.load_settings()
        self.alpha = panel_alpha(self.settings)

        # 托盘 / 统计条窗口 / 图标管理窗口 / 检测接口 的句柄
        self.tray = None
        self.hotkey = None
        self.bar_window = None
        self.icon_dialog = None
        self.notices = []
        self.api_server = None
        self._quitting = False

        self.setWindowTitle("StatGI")
        self.resize(960, 700)
        self.setMinimumSize(760, 540)

        # 无边框 + 窗口背景透明 —— 圆角才是真的圆角（带抗锯齿，不会被画成直角）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._bg_src = load_background(self.settings)
        self._bg_cache = None
        self._bg_key = None
        self._dim = float(self.settings.get("bg_dim", 0.0) or 0.0)

        self._build()
        self._setup_extras()

    # ---------- 托盘 / 热键 / 接口 ----------
    def _setup_extras(self):
        """主界面建好之后，把周边的东西装上。

        每一块单独 try，并且把出错原因记进 data/error.log ——
        不用「except Exception: pass」把问题吞掉（那样只会得到
        "没装上"三个字，根本不知道为什么）。
        """
        from errlog import log_exc

        # 托盘 + 全局热键
        try:
            from qt_tray import Tray, HotkeyManager
            # 用 resource_file()，不能用 app_dir()：
            # app_icon.ico 打包后在 _internal\ 里（= _MEIPASS），**不在 EXE 旁边**。
            # 用 app_dir() 会找不到 → 托盘退回兜底图标、任务栏变成 Qt 默认图标。
            ico = paths.resource_file("app_icon.ico")
            icon = QIcon(str(ico)) if ico.exists() else QIcon()
            if not icon.isNull():
                self.setWindowIcon(icon)     # 任务栏 / Alt+Tab 用这个
            self.tray = Tray(self, ico, icon)
            # 全局热键可以有多个动作，每个动作一条设置（都默认「关闭」）
            self.hotkey = HotkeyManager(self, [
                ("hotkey", self.state.toggle),           # 开始 / 停止监测
                ("hotkey_bar", self.toggle_stat_bar),    # 显示 / 隐藏统计条
                ("hotkey_home", self.hotkey_show_home),  # 把主窗口叫回来
            ])
        except Exception:
            log_exc("qt_window 托盘/热键")

        # 直播数据接口（跟 Tk 版共用 api_server.py）
        try:
            from api_server import ApiServer
            self.api_server = ApiServer(
                port=int(self.settings.get("api_port", 8765) or 8765))
            self.api_server.set_provider(self._api_data)
            self.api_server.start()
        except Exception:
            self.api_server = None
            log_exc("qt_window 直播接口")

        # 公告：先用本地已有的（缓存 / 内置）初始化一次。
        # 这样「还没拉回来」和「拉不到」的时候侧栏红点也是对的 ——
        # 公告页显示了几条，侧栏就该反映几条，两边不能不一致。
        try:
            import qt_notice
            self.set_notice(qt_notice.load_all())
        except Exception:
            log_exc("qt_window 公告初始化")

        # 公告：再后台静默拉一次
        # 拉到了就更新侧栏红点和公告页；拉不到什么都不做 ——
        # 公告是锦上添花，不能因为没网就弹错误打扰人。
        try:
            import qt_notice
            self.notice_fetcher = qt_notice.NoticeFetcher()
            self.notice_fetcher.done.connect(self._on_notice)
            self.notice_fetcher.start()
        except Exception:
            self.notice_fetcher = None
            log_exc("qt_window 公告")

    def _on_notice(self, notices):
        """公告拉回来了（这里已经在主线程 —— 信号跨线程是安全的）

        notices 有两种：
            []      拉到了，远端一条公告都没有（公告被清空）→ 要跟着清空
            None    一个源都没拉到 → 保持现状（用缓存），别乱动
        """
        if notices is None:
            return
        try:
            self.set_notice(notices)
            # 公告页如果已经建好，顺手把列表也更新一下
            pg = self.pages[NOTICE_PAGE_INDEX] if len(self.pages) > NOTICE_PAGE_INDEX else None
            fn = getattr(pg, "set_notices", None)
            if callable(fn):
                fn(notices)
        except Exception:
            pass

    # ---------- 公告 ----------
    def set_notice(self, notices):
        """记下公告列表，并更新侧栏那个未读小红点"""
        self.notices = list(notices or [])
        unread = 0
        try:
            import qt_notice
            unread = qt_notice.unread_count(self.notices, self.state.settings)
        except Exception:
            pass
        try:
            self.sidebar.set_notice_unread(unread > 0)
        except Exception:
            pass

    def show_notice_page(self):
        """点侧栏「公告」→ 切到公告页（不是弹窗）"""
        done = self.stack.currentIndex() == NOTICE_PAGE_INDEX
        if done:
            # 已经在这一页了，再点一次就当作「刷新一下」
            pg = self.pages[NOTICE_PAGE_INDEX]
            fn = getattr(pg, "on_show", None)
            if callable(fn):
                fn()
            return
        self.show_page(NOTICE_PAGE_INDEX)

    def _api_data(self):
        """直播接口给出去的数据

        ⚠ 字段名要**同时**给新旧两套：
        · 新名字（materials / seconds）是 Qt 版内部一直在用的
        · 老名字（material_total / running_seconds）是 OBS 那套网页要的
          —— 内置在 api_server.py 里的那个页面、还有用户自建的
          「直播间美化.html」，读的都是老名字。v0.8 换 Qt 的时候
          只给了新名字，网页上「材料」和「挂机时间」就一直显示 0 了。
        两套都给最省事，也不会再踩一次。
        """
        snap = self.state.snapshot()
        mats = snap.get("materials") or {}
        try:
            mat_total = sum(int(v) for v in mats.values())
        except Exception:
            mat_total = 0
        secs = snap["seconds"]
        return {
            "date": getattr(self.state.stats, "date", ""),
            "mora": snap["mora"],
            "artifact": snap["artifact"],
            "seconds": secs,
            "running_seconds": secs,        # ← OBS 网页用的老名字
            "materials": mats,
            "material_total": mat_total,    # ← OBS 网页用的老名字
            "monitoring": self.state.monitoring,
        }

    def set_obs(self, on):
        """OBS 开关：只是记录状态，接口一直在跑"""
        pass

    # ---------- 背景 ----------
    def background(self):
        """按当前窗口尺寸铺满的背景图（带缓存，尺寸没变就不重算）"""
        w, h = self.width(), self.height()
        if self._bg_key != (w, h):
            self._bg_cache = _cover(self._bg_src, w, h)
            self._bg_key = (w, h)
        return self._bg_cache

    def set_background_image(self, path_or_none):
        """换背景图（改设置后调它，不会重建任何控件）

        传 None / 空 = 去掉背景图，回到纯色背景。
        """
        if path_or_none and os.path.exists(path_or_none):
            pm = QPixmap(path_or_none)
            self._bg_src = pm if not pm.isNull() else QPixmap()
        else:
            self._bg_src = QPixmap()          # 空 = 纯色
        self._bg_key = None
        if hasattr(self, "sidebar"):
            self.sidebar.refresh_bg()
        self.update()

    # ---------- 换颜色（背景色 / 强调色）----------
    def rebuild_ui(self):
        """按最新的颜色把界面重建一遍。

        换背景色/强调色时调它 —— 不用重启，改完立刻能看到。
        重建的是页面和侧边栏按钮，不动 state（统计和监测不受影响）。
        """
        import importlib
        import qt_pages
        importlib.reload(qt_pages)        # 让它重新读一遍新颜色

        # 1) 侧边栏按钮重新上色
        self.sidebar._glass = bool(self.state.get_setting("sidebar_glass", True))
        self.sidebar.set_active(self.stack.currentIndex())
        self.sidebar._blur = None
        self.sidebar.update()

        # 2) 标题条
        self.titlebar.setStyleSheet(
            f"QFrame {{ background: {rgba(T.HEADER, 190)};"
            f" border-top-left-radius: {RADIUS_WINDOW}px;"
            f" border-top-right-radius: {RADIUS_WINDOW}px; }}")

        # 3) 页面重建（旧的丢掉，新的按新颜色搭）
        idx = self.stack.currentIndex()
        old = self.pages
        for p in old:
            self.stack.removeWidget(p)
            p.setParent(None)
            p.deleteLater()
        self.pages = qt_pages.build_pages(self)
        for p in self.pages:
            self.stack.addWidget(p)
        self.show_page(idx)
        self._bg_key = None
        self.update()

    def resizeEvent(self, e):
        self._bg_key = None
        super().resizeEvent(e)
        if hasattr(self, "sidebar"):
            self.sidebar.refresh_bg()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                            RADIUS_WINDOW, RADIUS_WINDOW)
        p.setClipPath(path)
        bg = self.background()
        if bg.isNull():
            # 没有背景图 -> 纯色（跟着设置里的「背景颜色」走）
            p.fillRect(self.rect(), QColor(T.BG))
        else:
            p.drawPixmap(0, 0, bg)
        a = int(40 + 180 * max(0.0, min(1.0, getattr(self, "_dim", 0.0))))
        if not bg.isNull():
            p.fillRect(self.rect(), QColor(0, 0, 0, a))
        p.setClipping(False)

    def apply_bg_dim(self):
        """背景压暗：只重画窗口背景，不碰任何控件"""
        try:
            self._dim = float(self.state.settings.get("bg_dim", 0.0) or 0.0)
        except Exception:
            self._dim = 0.0
        self.update()

    # ---------- 自己实现改窗口大小 ----------
    # 为什么不用 QSizeGrip？因为它是放在右下角的一个小控件，
    # 会把那个角**画成直角**盖住窗口的圆角（左下角则是被侧栏盖住）。
    # 自己做边缘检测就没有这个问题，而且四个边和四个角都能拉。
    def _edge_at(self, pos):
        m = 6                                  # 边缘判定宽度
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        left, right = x <= m, x >= w - m
        top, bottom = y <= m, y >= h - m
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"
        return None

    def _cursor_for(self, edge):
        return {
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
        }.get(edge)

    def mouseMoveEvent(self, e):
        if self._resize_edge and (e.buttons() & Qt.LeftButton):
            self._do_resize(e.globalPosition().toPoint())
            e.accept()
            return
        edge = self._edge_at(e.position().toPoint())
        cur = self._cursor_for(edge)
        self.setCursor(cur if cur else Qt.ArrowCursor)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            edge = self._edge_at(e.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_start = (e.globalPosition().toPoint(), self.geometry())
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._resize_edge = None
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        if not self._resize_edge:
            self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(e)

    def _do_resize(self, gpos):
        start_pos, start_geo = self._resize_start
        dx = gpos.x() - start_pos.x()
        dy = gpos.y() - start_pos.y()
        g = QRect(start_geo)
        e = self._resize_edge
        minw, minh = self.minimumWidth(), self.minimumHeight()
        if "l" in e:
            g.setLeft(min(g.left() + dx, g.right() - minw))
        if "r" in e:
            g.setRight(max(g.right() + dx, g.left() + minw))
        if "t" in e:
            g.setTop(min(g.top() + dy, g.bottom() - minh))
        if "b" in e:
            g.setBottom(max(g.bottom() + dy, g.top() + minh))
        self.setGeometry(g)

    # ---------- 各种打开 / 关闭 ----------
    def open_stat_bar(self):
        if self.bar_window is None:
            from qt_bar import StatBarWindow
            self.bar_window = StatBarWindow(self.state, on_closed=self._bar_closed)
        self.bar_window.apply_appearance()
        return self.bar_window

    def _bar_closed(self):
        self.bar_window = None

    def toggle_stat_bar(self):
        """热键用：统计条开着就收起，没开就打开

        （打开的动作在 open_stat_bar → apply_appearance 里，最后会 show()）
        """
        try:
            if self.bar_window is not None:
                self.bar_window.close()     # close 会走 _bar_closed 清掉引用
            else:
                self.open_stat_bar()
        except Exception:
            log_exc("qt_window 切换统计条")

    def hotkey_show_home(self):
        """热键用：把主窗口叫回来（从托盘/最小化状态恢复并置顶）"""
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            log_exc("qt_window 显示主窗口")

    def open_icon_manager(self):
        """图标管理：只能开一个，已经开着就拎到前面来"""
        if self.icon_dialog is not None:
            try:
                if self.icon_dialog.isVisible():
                    self.icon_dialog.raise_()
                    self.icon_dialog.activateWindow()
                    return
            except Exception:
                pass
        from qt_dialogs import IconManagerDialog
        self.icon_dialog = IconManagerDialog(
            self, on_change=self._on_icons_changed)
        self.icon_dialog.finished.connect(lambda _=0: setattr(self, "icon_dialog", None))
        self.icon_dialog.show()

    def _on_icons_changed(self):
        if self.bar_window is not None:
            self.bar_window.apply_appearance()

    def open_data_dir(self):
        import os
        import subprocess
        d = paths.app_dir() / "data"
        try:
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))          # noqa  Windows 专用
        except Exception:
            try:
                subprocess.Popen(["explorer", str(d)])
            except Exception:
                pass

    def set_sidebar_glass(self, on):
        """左侧栏毛玻璃开关（关掉就是纯色+压暗）"""
        self._sidebar_glass = bool(on)
        if hasattr(self, "sidebar"):
            self.sidebar.set_glass(self._sidebar_glass)

    def set_obs(self, on):
        """OBS 开关：接口一直在跑，这里不用做什么"""
        pass

    def restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def really_quit(self):
        self._quitting = True
        self.close()

    def closeEvent(self, e):
        """点 ✕：按设置里的「关闭行为」来"""
        if self._quitting:
            self._shutdown()
            return super().closeEvent(e)
        behavior = str(self.state.settings.get("close_behavior", "ask"))
        if behavior == "tray":
            e.ignore()
            self.hide()
            return
        if behavior == "exit":
            self._shutdown()
            return super().closeEvent(e)
        box = QMessageBox(self)
        box.setWindowTitle("退出")
        box.setText("要关闭程序，还是最小化到托盘？")
        box.setInformativeText("最小化后监测会继续运行，想彻底退出就选「关闭程序」。")
        b_exit = box.addButton("🗑 关闭程序", QMessageBox.DestructiveRole)
        b_tray = box.addButton("📌 最小化到托盘", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_exit:
            self._shutdown()
            return super().closeEvent(e)
        if clicked is b_tray:
            e.ignore()
            self.hide()
            return
        e.ignore()

    def _shutdown(self):
        """真正退出前：停监测、关子窗口、停接口"""
        try:
            if self.state.monitoring:
                self.state.stop()
        except Exception:
            pass
        for w in (self.bar_window, self.icon_dialog):
            try:
                if w is not None:
                    w.close()
            except Exception:
                pass
        try:
            if self.tray is not None:
                self.tray.icon.hide()
        except Exception:
            pass
        try:
            if self.api_server is not None:
                # ApiServer 没有 stop()，直接关它内部那个 werkzeug 服务器
                srv = (getattr(self.api_server, "_server", None)
                       or getattr(self.api_server, "server", None))
                if srv is not None:
                    srv.shutdown()
        except Exception:
            pass

    # ---------- 界面 ----------
    def _build(self):
        from qt_pages import build_pages
        from qt_core import AppState

        # 全程序唯一的状态对象（统计 + 监测 + 唯一的那个刷新定时器）
        self.state = AppState(self.settings)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self, "StatGI", "● 未框选（自动检测游戏窗口）")
        root.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.stack = QStackedWidget()
        self.pages = build_pages(self)
        for p in self.pages:
            self.stack.addWidget(p)

        self.sidebar = Sidebar(
            self,
            # 「今日统计」不单独一页了 —— 挪到「启动」页那张卡片下面的
            # 折叠区里（点开就看到时间/摩拉/材料/狗粮四个数）。
            [("🚀", "启动"), ("📶", "收益统计条"),
             ("📋", "收益记录"), ("⚙", "设置")],
            self.show_page)
        body.addWidget(self.sidebar)
        body.addWidget(self.stack, 1)

        holder = QWidget()
        holder.setLayout(body)
        root.addWidget(holder, 1)

        # 改窗口大小是自己在 mouseMove/Press 里做的（不用 QSizeGrip，
        # 那玩意儿会把右下角盖成直角）
        self._resize_edge = None
        self._resize_start = (None, None)
        self.setMouseTracking(True)

        # 状态变了只改标题条那行小字，不重建任何东西
        self.state.status_changed.connect(
            lambda text, color: self.titlebar.sub_label.setText(f"● {text}"))

    def show_page(self, idx):
        self.stack.setCurrentIndex(idx)
        # 公告页不在导航里（是侧栏下面那个单独入口），
        # 所以在公告页时把导航的高亮全部清掉
        self.sidebar.set_active(-1 if idx == NOTICE_PAGE_INDEX else idx)
        page = self.pages[idx]
        # 页面第一次显示时让它自己刷新一次（各页自己实现）
        fn = getattr(page, "on_show", None)
        if callable(fn):
            fn()
