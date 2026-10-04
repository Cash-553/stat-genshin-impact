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
from PySide6.QtCore import Qt, QRectF, QRect, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QColor, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
                               QMessageBox, QDialog)
import config_manager
import paths
from qt_pages import (NOTICE_PAGE_INDEX, SETTINGS_PAGE_INDEX, DAILY_PAGE_INDEX,
                      RECORDS_PAGE_INDEX, LAUNCH_PAGE_INDEX, BAR_PAGE_INDEX)
from qt_theme import RADIUS_WINDOW, panel_alpha, label_qss, rgba
import qt_theme as T
from qt_bg import _cover, load_background
from qt_titlebar import TitleBar
from qt_navbtn import NavButton
from qt_sidebar import Sidebar
# 三个闪烁常量也一起转发 —— 它们内部只有 Sidebar 在用，
# 但留在这儿可以保证 `qt_window` 对外露出的名字跟拆之前**一个不差**
# （`_morph\api_snapshot.py` 会盯着这个）。

# ============================================================
#  注意：TitleBar / NavButton / Sidebar / 背景图工具 都已经搬走了
#
#     qt_bg.py         _cover / _blur / load_background
#     qt_titlebar.py   TitleBar
#     qt_navbtn.py     NavButton
#     qt_sidebar.py    Sidebar（+ 闪烁那几个常量）
#
#  上面 import 进来的那些名字**必须留着转发** ——
#  `qt_bar_editor.py` 顶层就 `from qt_window import NavButton`，
#  删了它编辑器直接起不来，而且 py_compile 查不出来。
# ============================================================


# ============================================================
#  主窗口
# ============================================================
class MainWindow(QWidget):
    # 后台线程检测到新版本时发这个（参数是 qt_update.check 返回的 dict）
    update_found = Signal(object)

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

        每一块单独 try，并且把出错原因记进 data/日志/报错/ ——
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
            # 全局热键：两个动作，各一条设置（都默认「关闭」）
            self.hotkey = HotkeyManager(self, [
                ("hotkey", self.state.toggle),           # 开始 / 停止监测
                ("hotkey_bar", self.toggle_stat_bar),    # 显示 / 隐藏统计条
            ])
        except Exception:
            log_exc("qt_window 托盘/热键")

        # 直播数据接口（跟 api_server.py 共用）
        # 真正的启动在 apply_api() 里 —— 那里会看设置决定开不开、用哪个端口。
        self._api_port = None
        self._api_on = None
        self.apply_api()

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

    def apply_api(self):
        """按设置把直播接口开起来 / 关掉 / 换端口

        设置里改了「连接 OBS」开关或者端口，就调这个方法 —— 立刻生效，
        不用重启程序（以前端口改完必须重启，开关更是个摆设）。
        """
        try:
            st = (self.state.settings if getattr(self, "state", None) else
                  self.settings) or {}
            want = bool(st.get("obs_api_enabled", True))
            port = int(st.get("api_port", 8765) or 8765)
            if self.api_server is not None:
                if (getattr(self, "_api_on", None) == want
                        and getattr(self, "_api_port", None) == port):
                    return                       # 没变，什么都不做
                try:
                    self.api_server.stop()
                except Exception:
                    pass
                self.api_server = None
                self._api_on = None
            if want:
                from api_server import ApiServer
                self.api_server = ApiServer(port=port)
                self.api_server.set_provider(self._api_data)
                self.api_server.start()
            self._api_on = want
            self._api_port = port
        except Exception:
            self.api_server = None
            log_exc("qt_window 直播接口")

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

    def _open_dir(self, d):
        """在文件管理器里打开一个目录（打不开就退回 explorer）"""
        import os
        import subprocess
        try:
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))          # noqa  Windows 专用
        except Exception:
            try:
                subprocess.Popen(["explorer", str(d)])
            except Exception:
                pass

    def open_data_dir(self):
        self._open_dir(paths.app_dir() / "data")

    def open_log_dir(self):
        """打开识别日志文件夹（一次运行一个文件，放在 data/识别日志/）"""
        import detect_log
        self._open_dir(detect_log.LOG_DIR)

    def set_sidebar_glass(self, on):
        """左侧栏毛玻璃开关（关掉就是纯色+压暗）"""
        self._sidebar_glass = bool(on)
        if hasattr(self, "sidebar"):
            self.sidebar.set_glass(self._sidebar_glass)

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
        # 「每次询问」→ 卡片式确认窗（2026-10-04 用户要求换掉原来的 QMessageBox）
        from qt_dlg_card import ExitDialog
        dlg = ExitDialog(self, alpha=self.alpha)
        if dlg.exec() != QDialog.Accepted:
            e.ignore()
            return
        choice = dlg.chosen() or "tray"
        # 勾了「不再提醒我」→ 把这次的选择存成 close_behavior，以后直接照办
        if dlg.check_checked():
            try:
                self.state.settings["close_behavior"] = choice
                config_manager.save_settings(self.state.settings)
            except Exception:
                log_exc("记住关闭行为")
        if choice == "exit":
            self._shutdown()
            return super().closeEvent(e)
        e.ignore()
        self.hide()

    def _shutdown(self):
        """真正退出前：停监测、关子窗口、停接口"""
        # ⚠ 先标记"正在退出"：这样 _shutdown 里那次 stop() 不会弹「本次小结」
        #   （自动更新前也会走 _shutdown，同样不该弹窗）
        self._quitting = True
        try:
            # 暂停中也要 stop() —— 否则这次挂机的收益记录不会写
            if self.state.monitoring or getattr(self.state, "paused", False):
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
                # `ApiServer.stop()` 早就有（api_server.py）——
                # 这里原来写着"没有 stop()"、伸手去掏它的私有属性 `_server`，
                # 是过期代码（而且那个 `getattr(..., "server")` 兜底的名字根本不存在）。
                self.api_server.stop()
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

        # 侧栏顺序 ↔ 页面栈顺序**不是**一回事：页面栈里新页一律追加在末尾
        # （见 `qt_pages.build_pages` 的说明），侧栏想显示在第几个就写在这张表里。
        # 下标是 `build_pages` 的返回顺序。
        self._nav_to_page = [LAUNCH_PAGE_INDEX, BAR_PAGE_INDEX,
                             RECORDS_PAGE_INDEX, DAILY_PAGE_INDEX,
                             SETTINGS_PAGE_INDEX]
        self._page_to_nav = {p: n for n, p in enumerate(self._nav_to_page)}

        self.sidebar = Sidebar(
            self,
            # 「今日统计」不单独一页了 —— 挪到「启动」页那张卡片下面的
            # 折叠区里（点开就看到时间/摩拉/材料/狗粮四个数）。
            [("rocket", "启动"), ("chart-column", "收益统计条"),
             ("clipboard-list", "收益细则"), ("chart-bar", "收益记录"),
             ("settings", "设置")],
            self._on_nav)
        body.addWidget(self.sidebar)

        # 后台线程查到的更新结果 → 主线程刷新提示
        self.update_found.connect(
            lambda info: self.set_update_available(True, info.get("version", "")))
        body.addWidget(self.stack, 1)

        holder = QWidget()
        holder.setLayout(body)
        root.addWidget(holder, 1)

        # 改窗口大小是自己在 mouseMove/Press 里做的（不用 QSizeGrip，
        # 那玩意儿会把右下角盖成直角）
        self._resize_edge = None
        self._resize_start = (None, None)
        self.setMouseTracking(True)

        # 状态变了只改标题条那行小字，不重建任何东西。
        # 文字**和颜色**都要跟着走（正在监测=绿、已暂停=红），
        # 以前这里把 color 丢掉了，所以标题条永远是灰的。
        self.state.status_changed.connect(self._on_title_status)
        # 手动停止监测 → 弹「本次小结」（退出程序时不弹，见 _shutdown）
        self.state.session_ended.connect(self._on_session_ended)

    def _on_session_ended(self, rec):
        """本次监测结束：弹一个小结（可以在设置里关掉）

        2026-10-04：小结弹窗换成了卡片式（圆角 ✕ + 整宽确定）。
        中途曾按用户要求加过「查看收益记录 / 查看每日收益 / 继续监测」几个
        单选项，**看过效果之后用户又让删掉了**，所以这里不再有分支。
        """
        try:
            if getattr(self, "_quitting", False):
                return                      # 正在退出，别弹
            if not bool(self.state.settings.get("stop_summary", True)):
                return
            import qt_dialogs
            qt_dialogs.StopSummaryDialog(self, rec, alpha=self.alpha).exec()
        except Exception:
            log_exc("qt_window 停止小结")

    def _on_title_status(self, text, color):
        """标题条左上角那行状态：跟启动页那张卡片用的是同一套文字和颜色"""
        try:
            self.titlebar.sub_label.setText(f"● {text}")
            self.titlebar.sub_label.setStyleSheet(label_qss(color, 12))
        except Exception:
            log_exc("qt_window 标题状态")

    def show_page(self, idx):
        # ⚠ 先给**上一页**一个 on_hide 的机会，再切页。
        #   设置页用它做「名单开着但为空」的提醒 —— 弹窗必须弹在切页之前，
        #   不然用户已经走了才跳提示，会莫名其妙。
        try:
            old = self.stack.currentWidget()
            fn = getattr(old, "on_hide", None)
            if callable(fn):
                fn()
        except Exception:
            from errlog import log_exc
            log_exc("on_hide")
        self.stack.setCurrentIndex(idx)
        # 高亮侧栏里对应的那一项。查表是因为**侧栏顺序 ≠ 页面栈顺序**
        # （新页追加在栈末尾）；公告页不在导航里 → -1 = 全部取消高亮。
        self.sidebar.set_active(self._page_to_nav.get(idx, -1))
        page = self.pages[idx]
        # 页面第一次显示时让它自己刷新一次（各页自己实现）
        fn = getattr(page, "on_show", None)
        if callable(fn):
            fn()

    def _on_nav(self, nav_idx):
        """侧栏点了第 nav_idx 项 → 切到它映射的那一页"""
        try:
            self.show_page(self._nav_to_page[nav_idx])
        except Exception:
            from errlog import log_exc
            log_exc("qt_window 侧栏导航")

    # ============================================================
    #  检测到新版本
    # ============================================================
    def set_update_available(self, on, version=""):
        """检测到新版本 → 侧栏左下角闪红光 + 设置里挂红点"""
        try:
            self.sidebar.set_update_available(on, version)
        except Exception:
            pass
        for p in self.pages:
            fn = getattr(p, "set_update_badge", None)
            if callable(fn):
                try:
                    fn(on)
                except Exception:
                    pass

    def show_update_settings(self):
        """点侧栏那个闪烁的「检测到新版本」→ 跳到 设置→其它→版本更新"""
        # ⚠ 用常量，别写死 3：新页一律**追加在页面栈末尾**，
        #   但"哪一页是设置"由 `qt_pages.SETTINGS_PAGE_INDEX` 说了算。
        self.show_page(SETTINGS_PAGE_INDEX)
        p = (self.pages[SETTINGS_PAGE_INDEX]
             if len(self.pages) > SETTINGS_PAGE_INDEX else None)
        fn = getattr(p, "goto_update", None)
        if callable(fn):
            fn()

    def start_update_check(self):
        """启动后自动查一次更新。

        两个渠道都试（Gitee + GitHub）—— 只试一个的话，那个渠道被墙/被限流
        就永远检测不到更新了。整个过程在后台线程跑，不卡界面。
        """
        import threading

        def work():
            try:
                import qt_update
                info, ch, reason = qt_update.check("auto", bust_cache=True)
                if info and info.get("is_newer"):
                    # 信号会自动排到主线程执行（Qt 跨线程发信号是安全的）
                    self.update_found.emit(info)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True, name="update-check").start()
