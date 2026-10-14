# -*- coding: utf-8 -*-
"""模块仓库 —— 浏览 / 下载 / 更新模块与配置（2026-10-15 推倒重做）。

远端（Gitee 优先，逐条兜底）：Gitee / jsDelivr / GitHub —— 任一可用即可。
安全：仓库里只有"声明式内容"（启动程序 / 打开网址），不执行第三方代码；
      下载后按清单里的 sha256 校验（对换行差异容错）。

界面要点：
    · 顶部三个固定选项：全部 / 模块 / 配置
    · 列表每行**固定高度**（64）→ 卡片不可能被内容撑大 ✗
    · 行右侧：下载 / 更新 / 灰色「已安装」
    · 点下载 → 原地变成「加载圆圈 + 进度条」（圆圈是 QPainter 画的弧线 ✓）
"""
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

import qt_theme as T
import svc_modules
from qt_theme import label_qss

GITEE_BASE = "https://gitee.com/Cash553/statgi-modules/raw/HEAD/"
GITEE_BASE_ALT = "https://gitee.com/Cash553/statgi-modules/raw/master/"
JSDELIVR_BASE = "https://cdn.jsdelivr.net/gh/Cash-553/statgi-modules@master/"
GITHUB_BASE = "https://raw.githubusercontent.com/Cash-553/statgi-modules/master/"
GITHUB_BASE_ALT = "https://raw.githubusercontent.com/Cash-553/statgi-modules/main/"
INDEX = "index.json"
UA = "StatGI/0.9.7 (module repo)"

ALL_CATS = "全部"
KIND_MOD = "模块"
KIND_CFG = "配置"
KIND_HAS = "已安装"
CHIPS = (ALL_CATS, KIND_MOD, KIND_CFG, KIND_HAS)

ROW_H = 64          # 每行固定高度 → 卡片不可能被撑大 ✓


# ============================================================
def _bases():
    """按优先级列出所有下载前缀（先 master，再 HEAD；Gitee 的 HEAD 别名会滞后）"""
    return ((GITEE_BASE_ALT, "Gitee"), (GITEE_BASE, "Gitee"),
            (JSDELIVR_BASE, "jsDelivr"),
            (GITHUB_BASE, "GitHub"), (GITHUB_BASE_ALT, "GitHub(main)"))


def _get(url, timeout=10):
    # 中文文件名要转义；再带时间戳尽量避开 CDN 旧内容
    import time as _t
    try:
        url = urllib.parse.quote(str(url), safe=":/?&=#%+")
        url = f"{url}{'&' if '?' in url else '?'}t={int(_t.time())}"
    except Exception:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ver_tuple(s):
    import re
    nums = re.findall(r"\d+", str(s or ""))
    return tuple(int(x) for x in nums) if nums else ()


def is_newer(remote, local):
    a, b = ver_tuple(remote), ver_tuple(local)
    if not a:
        return False
    if not b:
        return True
    return a > b


def fetch_index():
    """拉清单：((模块列表, 配置列表), 来源或错误)。

    拿到后**验一下**第一个文件真能下载吗 —— CDN 常给出过期清单（文件已改名 → 全 404）✓
    """
    errs = []
    for base, tag in _bases():
        try:
            d = json.loads(_get(base + INDEX).decode("utf-8-sig"))
            mods, cfgs = d.get("modules") or [], d.get("configs") or []
            first = (mods + cfgs)[0] if (mods or cfgs) else None
            if first is not None and str(first.get("file") or ""):
                try:
                    _get(base + str(first["file"]), timeout=10)
                except Exception:
                    errs.append(f"{tag}: index-stale")
                    continue
            return (mods, cfgs), tag
        except Exception as e:
            errs.append(f"{tag}: {type(e).__name__}")
    return ([], []), "拉不到清单（" + "，".join(errs) + "）"


def _sha_ok(blob, want):
    """校验 sha256（Gitee 可能改换行，三种形式都认）"""
    if not want:
        return True, blob
    for v in (blob, blob.replace(b"\r\n", b"\n"), blob.replace(b"\n", b"\r\n")):
        if hashlib.sha256(v).hexdigest() == want:
            return True, v
    return False, blob


def download(item):
    """下载并校验；返回 (字节, 来源或错误说明)"""
    rel = str((item or {}).get("file") or "")
    if not rel:
        return None, "清单里没写 file"
    want = str((item or {}).get("sha256") or "").lower()
    errs = []
    for base, tag in _bases():
        try:
            blob = _get(base + rel, timeout=20)
            ok, fixed = _sha_ok(blob, want)
            if not ok:
                errs.append(f"{tag}: 校验不符")
                continue
            return fixed, tag
        except Exception as e:
            errs.append(f"{tag}: {type(e).__name__}")
    return None, "下载失败（" + "，".join(errs) + "）"


def installed_versions():
    """{key: 本地版本号} —— 两个来源都读：

        · data/modules/*.json      （配置）
        · modules/<名字>/module.py （模块文件夹 —— 里面有 VERSION ✓）

    ⚠ 2026-10-15：以前只读 data/modules ✗ —— 模块是"文件夹"形式装的，
      版本读不到就当成空 → 永远被判成"比远端旧" → 一直显示「更新」✗
    """
    import re
    out = {}
    # 配置
    try:
        d = Path(svc_modules.modules_dir())
        for f in list(d.glob("*.sgmod.json")) + list(d.glob("*.json")):
            try:
                j = json.loads(f.read_text(encoding="utf-8-sig"))
                k = str(j.get("key") or "")
                if k:
                    out[k] = str(j.get("version") or "")
            except Exception:
                continue
    except Exception:
        pass
    # 模块文件夹
    roots = []
    try:
        import modules as _M
        for attr in ("ROOT_MODULES", "MODULE_FILES", "HERE"):
            v = getattr(_M, attr, None)
            if v is not None:
                roots.append(Path(v))
    except Exception:
        pass
    try:
        import paths
        roots.append(Path(paths.app_dir()) / "modules")
    except Exception:
        pass
    for r in roots:
        try:
            for sub in Path(r).iterdir():
                if not sub.is_dir():
                    continue
                mf = sub / "module.py"
                if not mf.is_file():
                    continue
                try:
                    txt = mf.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                k = sub.name
                m = re.search(r'^\s*KEY\s*=\s*["\']([^"\']+)["\']', txt, re.M)
                if m:
                    k = m.group(1).strip() or k
                v = re.search(r'^\s*VERSION\s*=\s*["\']([^"\']+)["\']', txt, re.M)
                out[k] = v.group(1).strip() if v else out.get(k, "")
        except Exception:
            continue
    return out


def save_module(item, blob):
    """把配置存进 data/modules/。返回 (成功?, 说明)"""
    try:
        d = Path(svc_modules.modules_dir())
        d.mkdir(parents=True, exist_ok=True)
        name = str((item or {}).get("key") or "module") + ".sgmod.json"
        (d / name).write_bytes(blob)
        return True, name
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ============================================================
class Spinner(QWidget):
    """正常的加载圆圈：一段弧线绕着转（QPainter 画的 ✓）"""

    def __init__(self, parent=None, size=18, color=None, width=2):
        super().__init__(parent)
        self._angle = 0
        self._size = size
        self._color = QColor(color or T.ACCENT)
        self._w = width
        self.setFixedSize(size, size)
        self.setStyleSheet("background: transparent;")
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        self._angle = (self._angle + 22) % 360
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = self._w + 1
        rect = QRectF(m, m, self._size - 2 * m, self._size - 2 * m)
        pen = QPen(QColor(255, 255, 255, 38), self._w)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(rect)
        pen = QPen(self._color, self._w)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(-self._angle * 16), int(100 * 16))
        p.end()


# ============================================================
class Row(QFrame):
    """一个条目：左边名称/说明，右边动作区。**定高**，绝不撑大 ✓"""

    def __init__(self, parent, item, dialog):
        super().__init__(parent)
        self.item = item or {}
        self.dlg = dialog
        self.setObjectName("repRow")
        self.setFixedHeight(ROW_H)                     # ★
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "#repRow { background: rgba(255,255,255,0.035);"
            " border: 1px solid rgba(255,255,255,0.07); border-radius: 10px; }")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        mid = QVBoxLayout()
        mid.setSpacing(1)
        name = str(self.item.get("name") or self.item.get("key") or "")
        ver = str(self.item.get("version") or "")
        author = str(self.item.get("author") or "匿名")
        cat = str(self.item.get("category") or "")
        star = "★ " if self.item.get("featured") else ""
        t = QLabel(f"{star}{name}")
        t.setStyleSheet(label_qss(T.TEXT, 13, True))
        mid.addWidget(t)
        line2 = " · ".join(x for x in (str(self.item.get("desc") or ""),
                                       f"v{ver}" if ver else "",
                                       author, cat) if x)
        d = QLabel(line2)
        d.setStyleSheet(label_qss(T.DIM, 11))
        mid.addWidget(d)
        lay.addLayout(mid, 1)

        chg = str(self.item.get("changelog") or "").strip()
        if chg:
            c = QLabel("更新：" + chg)
            c.setStyleSheet(label_qss(T.DIM, 10))
            c.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lay.addWidget(c)

        self.act = QWidget()
        self.act.setFixedSize(104, 30)                 # ★ 定尺寸 ✓
        self.act.setStyleSheet("background: transparent;")
        self.act_lay = QHBoxLayout(self.act)
        self.act_lay.setContentsMargins(0, 0, 0, 0)
        self.act_lay.setSpacing(6)
        lay.addWidget(self.act, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.show_button()

    # ---------- 动作区 ----------
    def _set_act_w(self, w):
        """改动作区宽度：平时 104；装上以后要放 [卸载][已安装] → 190 ✓"""
        self._act_w = int(w)
        try:
            self.act.setFixedWidth(self._act_w)
        except Exception:
            pass

    def _clear(self):
        while self.act_lay.count():
            it = self.act_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                try:
                    w.deleteLater()
                except Exception:
                    pass

    def _btn(self, text, slot=None, width=None):
        """一个固定尺寸的小按钮；宽度可指定 ✓"""
        b = QPushButton(text)
        b.setFixedSize(int(width or 104), 30)
        if text == "已安装":
            b.setEnabled(False)
            b.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.06); color: #8b9096;"
                " border: 1px solid rgba(255,255,255,0.10); border-radius: 8px; }")
        elif text == "卸载":
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton { background: rgba(224,108,90,0.16); color: #E06C5A;"
                " border: 1px solid rgba(224,108,90,0.45); border-radius: 8px; }")
            if slot is not None:                       # ★ 以前漏了这句 → 点了没反应 ✗
                b.clicked.connect(lambda *_a, _s=slot: _s())
        else:
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {T.ACCENT}; color: #ffffff;"
                f" border: none; border-radius: 8px; font-weight: 600; }}")
            if slot is not None:
                b.clicked.connect(lambda *_a, _s=slot: _s())
        return b

    def show_button(self):
        """按本地情况显示：下载 / 更新 / [卸载][已安装]"""
        key = str(self.item.get("key") or "")
        local = (self.dlg.installed or {}).get(key, "")
        have = self.dlg.is_installed(key)
        if have and not is_newer(self.item.get("version"), local or ""):
            self.show_installed()
            return
        self._clear()
        self._set_act_w(104)
        if have or (local and is_newer(self.item.get("version"), local)):
            self.act_lay.addWidget(self._btn("更新", lambda: self.dlg.install(self.item)))
        else:
            self.act_lay.addWidget(self._btn("下载", lambda: self.dlg.install(self.item)))

    def show_busy(self):
        """点下去 → 加载圆圈 + 进度条 ✓"""
        self._clear()
        self._set_act_w(104)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.08); border: none;"
            " border-radius: 3px; }"
            f"QProgressBar::chunk {{ background: {T.ACCENT}; border-radius: 3px; }}")
        sp = Spinner(self, size=18)
        sp.start()
        self.act_lay.addWidget(bar, 1)
        self.act_lay.addWidget(sp)
        self._spinner = sp

    def show_installed(self):
        """已安装：[卸载]（左） + 灰色「已安装」（右）✓"""
        self._clear()
        self._set_act_w(190)
        self.act_lay.addWidget(
            self._btn("卸载", lambda: self.dlg.uninstall(self.item), width=80))
        self.act_lay.addWidget(self._btn("已安装", width=104))


# ============================================================
class ModuleRepoDialog(QDialog):
    """模块仓库窗口"""

    def __init__(self, parent=None, alpha=255):
        super().__init__(parent)
        self.alpha = alpha
        self.mods = []
        self.cfgs = []
        self.installed = {}
        self.cat = ALL_CATS
        self.rows = []
        self.src = ""
        self.setWindowTitle("模块仓库")
        self.resize(700, 560)
        self.setStyleSheet(f"background: {T.BG};")

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        t = QLabel("模块仓库　界面版 2026-10-15d")   # ← 一眼看出是新界面 ✓
        t.setStyleSheet(label_qss(T.ACCENT, 17, True))
        v.addWidget(t)

        self.hint = QLabel("正在读取清单…")
        self.hint.setStyleSheet(label_qss(T.DIM, 11))
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名字 / 说明 / 作者…")
        self.search.setFixedHeight(32)
        self.search.textChanged.connect(lambda _t: self.render())
        v.addWidget(self.search)

        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        v.addLayout(self.chip_row)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.viewport().setAutoFillBackground(False)
        self.holder = QWidget()
        self.holder.setStyleSheet("background: transparent;")
        self.list_lay = QVBoxLayout(self.holder)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        sc.setWidget(self.holder)
        v.addWidget(sc, 1)

        foot = QHBoxLayout()
        self.b_all = QPushButton("全部更新")
        self.b_all.setFixedSize(96, 30)
        self.b_all.clicked.connect(lambda *_a: self.update_all())
        foot.addWidget(self.b_all)
        foot.addStretch(1)
        b2 = QPushButton("重新读取")
        b2.setFixedSize(96, 30)
        b2.clicked.connect(lambda *_a: self.reload())
        foot.addWidget(b2)
        b3 = QPushButton("关闭")
        b3.setFixedSize(76, 30)
        b3.clicked.connect(lambda *_a: self.accept())
        foot.addWidget(b3)
        v.addLayout(foot)

        self._build_chips()
        self.reload()

    # ---------- 顶部三个固定选项 ----------
    def _build_chips(self):
        while self.chip_row.count():
            it = self.chip_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                try:
                    w.deleteLater()
                except Exception:
                    pass
        for c in CHIPS:
            b = QPushButton(c)
            b.setFixedHeight(28)
            b.setMinimumWidth(72)
            b.setCursor(Qt.PointingHandCursor)
            if c == self.cat:
                b.setStyleSheet(
                    f"QPushButton {{ background: {T.ACCENT}; color: #ffffff;"
                    f" border: none; border-radius: 8px; font-weight: 600;"
                    f" padding: 3px 14px; }}")
            else:
                b.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {T.TEXT};"
                    f" border: 1px solid rgba(255,255,255,0.14); border-radius: 8px;"
                    f" padding: 3px 14px; }}")
            b.clicked.connect(lambda *_a, _c=c: self.set_cat(_c))
            self.chip_row.addWidget(b)
        self.chip_row.addStretch(1)

    def set_cat(self, c):
        self.cat = str(c or ALL_CATS)
        self._build_chips()
        self.render()

    # ---------- 数据 ----------
    def reload(self, *_a):
        self.hint.setText("正在读取清单…")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        (self.mods, self.cfgs), self.src = fetch_index()
        self.installed = installed_versions()
        if not self.mods and not self.cfgs:
            self.hint.setText("没读到清单（可能没网或被限流）。\n" + self.src)
        self.render()

    def is_installed(self, key):
        """本地有没有这个东西（模块文件夹 / 内置目录 / data/modules）"""
        k = str(key)
        cands = []
        try:
            import modules as _M
            for attr in ("ROOT_MODULES", "MODULE_FILES", "HERE"):
                v = getattr(_M, attr, None)
                if v is not None:
                    cands.append(Path(v) / k)
        except Exception:
            pass
        try:
            import paths
            cands.append(Path(paths.app_dir()) / "modules" / k)
        except Exception:
            pass
        for dd in cands:
            try:
                if (dd / "module.py").is_file() or (dd / "ui.py").is_file():
                    return True
            except Exception:
                continue
        return k in (self.installed or {})

    def _visible(self):
        kw = (self.search.text() or "").strip().lower()

        def ok(m):
            if kw:
                blob = " ".join(str(m.get(k) or "") for k in
                                ("name", "key", "desc", "author")).lower()
                if kw not in blob:
                    return False
            if self.cat == KIND_HAS:                 # ← 「已安装」只看装过的 ✓
                return self.is_installed(str(m.get("key") or ""))
            return True

        mods = [] if self.cat == KIND_CFG else [m for m in self.mods if ok(m)]
        cfgs = [] if self.cat == KIND_MOD else [c for c in self.cfgs if ok(c)]
        return mods, cfgs

    def _updatable(self):
        out = []
        for m in list(self.mods) + list(self.cfgs):
            k = str(m.get("key") or "")
            if k in (self.installed or {}) and is_newer(m.get("version"),
                                                        self.installed.get(k)):
                out.append(m)
        return out

    def render(self):
        while self.list_lay.count() > 1:
            it = self.list_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                try:
                    w.deleteLater()
                except Exception:
                    pass
        self.rows = []
        mods, cfgs = self._visible()
        up = self._updatable()
        self.hint.setText(
            f"共 {len(self.mods)} 个模块、{len(self.cfgs)} 个配置（来源 {self.src}）"
            + (f"　有 {len(up)} 个可更新" if up else ""))
        try:
            self.b_all.setEnabled(bool(up))
        except Exception:
            pass

        def add(title, items):
            if not items:
                return
            lab = QLabel(title)
            lab.setStyleSheet(label_qss(T.DIM, 11, True))
            self.list_lay.insertWidget(self.list_lay.count() - 1, lab)
            for it in items:
                r = Row(self.holder, it, self)
                self.rows.append(r)
                self.list_lay.insertWidget(self.list_lay.count() - 1, r)

        add("模块", mods)
        add("配置", cfgs)
        if not mods and not cfgs:
            lab = QLabel("这里还没有内容")
            lab.setStyleSheet(label_qss(T.DIM, 11))
            self.list_lay.insertWidget(self.list_lay.count() - 1, lab)

    # ---------- 卸载 ----------
    def uninstall(self, item):
        """把装过的东西删掉：模块删文件夹、配置删 data/modules 里的那一份 ✓"""
        key = str((item or {}).get("key") or "")
        name = str((item or {}).get("name") or key)
        kind = "模块" if str((item or {}).get("kind") or "") == "module" else "配置"
        try:
            from PySide6.QtWidgets import QMessageBox
            ans = QMessageBox.question(
                self, "卸载", f"是否卸载这个{kind}：{name} ？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        except Exception:
            pass

        import shutil
        done, err = [], []
        # ① 模块文件夹（几个可能的位置都查）
        for getter in ("modules", "paths"):
            try:
                if getter == "modules":
                    import modules as _M
                    roots = [getattr(_M, a, None) for a in
                             ("ROOT_MODULES", "MODULE_FILES", "HERE")]
                else:
                    import paths as _p
                    roots = [Path(_p.app_dir()) / "modules"]
                for r in roots:
                    if r is None:
                        continue
                    d = Path(r) / key
                    if (d / "module.py").is_file():
                        shutil.rmtree(d, ignore_errors=True)
                        done.append("模块文件夹")
                        break
            except Exception as e:
                err.append(str(e))
        # ② 配置
        try:
            d = Path(svc_modules.modules_dir())
            for f in list(d.glob(key + ".sgmod.json")) + list(d.glob(key + ".json")):
                f.unlink(missing_ok=True)
                done.append("配置")
        except Exception as e:
            err.append(str(e))

        self.installed = installed_versions()
        row = next((r for r in self.rows if r.item is item), None)
        if row is not None:
            row.show_button()
        if err:
            self.hint.setText(f"卸载出错：{err[0]}")
        else:
            self.hint.setText(
                f"已卸载这个{kind}：{name} ✓"
                f"（{'、'.join(sorted(set(done))) if done else '没找到要删的东西'}）"
                "　重启程序后生效。")
        self.render()

    # ---------- 下载 ----------
    def install(self, item):
        row = next((r for r in self.rows if r.item is item), None)
        if row is not None:
            row.show_busy()
        self.hint.setText(f"正在获取 {(item or {}).get('name') or ''}…")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        blob, how = download(item)
        if blob is None:
            # 清单可能被 CDN 缓存 → 强制刷新一次再试 ✓
            self.hint.setText("清单可能是缓存，正在重试…")
            QApplication.processEvents()
            self.reload()
            fresh = None
            for c in (self.mods + self.cfgs):
                if str(c.get("key")) == str((item or {}).get("key")):
                    fresh = c
                    break
            if fresh is not None and str(fresh.get("file")) != str((item or {}).get("file")):
                blob, how = download(fresh)
                item = fresh
                row = next((r for r in self.rows if r.item is item), None) or row
        if blob is None:
            if row is not None:
                row.show_button()
            self.hint.setText("下载失败：" + how +
                              "\n（五条线路都不通；请检查网络/代理，或点「重新读取」再试）")
            return

        ok, info = self._save(item, blob)
        if row is not None:
            if ok:
                row.show_installed()
            else:
                row.show_button()
        self.installed = installed_versions()
        self.hint.setText(info)
        self.render()

    def _save(self, item, blob):
        """按类型装：
            模块(zip)   → 解压到 modules/<key>/
            配置(json)  → 存进 data/modules/
            配置包(zip) → 走配置包导入（附带模块，本地没有才装）
        """
        key = str((item or {}).get("key") or "")
        is_zip = str((item or {}).get("file", "")).lower().endswith(".zip")
        kind = str((item or {}).get("kind") or ("module" if is_zip else "config"))
        try:
            if kind == "config" and is_zip:
                import tempfile
                tmp = Path(tempfile.gettempdir()) / (key + ".sgmodpack.zip")
                tmp.write_bytes(blob)
                import svc_module_pack as pk
                _ok, info = pk.import_pack(tmp, ask=lambda *a: False)
                return True, str(info)
            if kind == "module" and is_zip:
                import io
                import zipfile
                import modules as _M
                tgt = Path(getattr(_M, "ROOT_MODULES"))
                tgt.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    for n in z.namelist():
                        if n.endswith("/"):
                            continue
                        out = tgt / n
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(n))
                return True, (f"已安装模块：{(item or {}).get('name') or key} ✓   "
                              "重启程序后，定时启动页就会出现它的卡片。")
        except Exception as e:
            return False, f"安装失败：{type(e).__name__}: {e}"
        ok, info = save_module(item, blob)
        if not ok:
            return False, "保存失败：" + info
        return True, (f"已下载：{(item or {}).get('name') or key} ✓ 重启程序后生效。")

    def update_all(self, *_a):
        ups = self._updatable()
        if not ups:
            return
        ok_n, bad = 0, []
        for m in ups:
            blob, how = download(m)
            if blob is None:
                bad.append(str(m.get("key")))
                continue
            ok, _info = self._save(m, blob)
            if ok:
                ok_n += 1
            else:
                bad.append(str(m.get("key")))
        self.hint.setText(f"全部更新：成功 {ok_n} 个"
                          + (f"，失败 {len(bad)} 个" if bad else ""))
        self.reload()
