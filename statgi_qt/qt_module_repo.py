# -*- coding: utf-8 -*-
"""模块仓库 —— 浏览 / 下载 / 更新别人的模块（像 BetterGI 的脚本仓库）。

远端：Gitee 优先，拉不到自动试 GitHub，再不行试 jsDelivr（GitHub 的镜像）：
    Gitee ：https://gitee.com/Cash553/statgi-modules
    GitHub：https://github.com/Cash-553/statgi-modules

安全：仓库里**只收 .sgmod.json**（声明式，只能"启动程序 / 打开网址"），
     不执行任何第三方代码 ✓；下载后按 index.json 里的 sha256 校验 ✓。

v0.9.7 新增（第 3 项）：
    · 已装的能看出**有没有新版本**（读本地模块文件里的 version 比对）
    · 一行一个「更新」；顶部一个「全部更新」
    · **分类筛选** + **搜索框**（名字 / 说明 / 作者）
    · 清单里可以带 category / changelog / updated / featured（没有也能用）
"""
import hashlib
import json
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QScrollArea, QVBoxLayout, QWidget)

import qt_theme as T
import svc_modules
from qt_theme import label_qss
from qt_widgets import Card, small_button

GITEE_BASE = "https://gitee.com/Cash553/statgi-modules/raw/HEAD/"
GITEE_BASE_ALT = "https://gitee.com/Cash553/statgi-modules/raw/master/"
JSDELIVR_BASE = "https://cdn.jsdelivr.net/gh/Cash-553/statgi-modules@master/"
GITHUB_BASE = "https://raw.githubusercontent.com/Cash-553/statgi-modules/master/"
GITHUB_BASE_ALT = "https://raw.githubusercontent.com/Cash-553/statgi-modules/main/"
INDEX = "index.json"
UA = "StatGI/0.9.7 (module repo)"
ALL_CATS = "全部"


def _bases():
    """按优先级给出所有下载前缀。

    ⚠ 顺序：先 master（我们推的就是它），再 HEAD（Gitee 的 HEAD 别名缓存会滞后）
    """
    return ((GITEE_BASE_ALT, "Gitee"), (GITEE_BASE, "Gitee"),
            (JSDELIVR_BASE, "jsDelivr"),
            (GITHUB_BASE, "GitHub"), (GITHUB_BASE_ALT, "GitHub(main)"))


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------- 版本比较 ----------------
def ver_tuple(s):
    """'1.10' → (1, 10)；认不出来的部分忽略（'1.2b' → (1, 2)）"""
    import re
    nums = re.findall(r"\d+", str(s or ""))
    return tuple(int(x) for x in nums) if nums else ()


def is_newer(remote, local):
    """远端版本是不是比本地新（本地没有版本号 → 视为旧）"""
    a, b = ver_tuple(remote), ver_tuple(local)
    if not a:
        return False
    if not b:
        return True
    return a > b


# ---------------- 远端 ----------------
def fetch_index():
    """拉清单：返回 (modules, 来源或错误说明)"""
    errs = []
    for base, tag in _bases():
        try:
            raw = _get(base + INDEX)
            # 容错：有人用记事本/PS 写文件会带 BOM
            d = json.loads(raw.decode("utf-8-sig"))
            return d.get("modules") or [], tag
        except Exception as e:
            errs.append(f"{tag}: {type(e).__name__}")
    return [], "拉不到清单（" + "，".join(errs) + "）"


def _sha_ok(blob, want):
    """校验 sha256。

    ⚠ Gitee 转发文件时可能把换行改掉（LF ↔ CRLF）→ 原样算会"校验不符" ✗
      三种形式都试一遍，命中哪种就用哪种内容 ✓
    """
    if not want:
        return True, blob
    for v in (blob, blob.replace(b"\r\n", b"\n"), blob.replace(b"\n", b"\r\n")):
        if hashlib.sha256(v).hexdigest() == want:
            return True, v
    return False, blob


def download(item):
    """下载并校验；返回 (字节, 来源或错误说明)"""
    rel = str(item.get("file") or "")
    if not rel:
        return None, "清单里没写 file"
    want = str(item.get("sha256") or "").lower()
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


# ---------------- 本地已装 ----------------
def installed_versions():
    """{key: 本地版本号} —— 直接读已装的模块文件，不依赖其它缓存"""
    out = {}
    try:
        d = Path(svc_modules.modules_dir())
    except Exception:
        return out
    for f in list(d.glob("*.sgmod.json")) + list(d.glob("*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8-sig"))
            k = str(j.get("key") or "")
            if k:
                out[k] = str(j.get("version") or "")
        except Exception:
            continue
    return out


def save_module(item, blob):
    """把下载到的内容装进 data/modules/。返回 (成功?, 说明)"""
    try:
        d = Path(svc_modules.modules_dir())
        d.mkdir(parents=True, exist_ok=True)
        name = str(item.get("key") or "module") + ".sgmod.json"
        (d / name).write_bytes(blob)
        return True, name
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ============================================================
class ModuleRepoDialog(QDialog):
    """模块仓库窗口"""

    def __init__(self, parent=None, alpha=255):
        super().__init__(parent)
        self.alpha = alpha
        self.mods = []
        self.src = ""
        self.installed = {}
        self.cat = ALL_CATS
        self.setWindowTitle("模块仓库")
        self.resize(680, 560)
        self.setStyleSheet(f"background: {T.BG};")

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        self.title = QLabel("模块仓库")
        self.title.setStyleSheet(label_qss(T.TEXT, 16, True))
        v.addWidget(self.title)

        self.hint = QLabel("正在读取清单…")
        self.hint.setStyleSheet(label_qss(T.DIM, 12))
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名字 / 说明 / 作者…")
        self.search.setFixedHeight(32)
        self.search.textChanged.connect(lambda _t: self._render_list())
        v.addWidget(self.search)

        self.cat_row = QHBoxLayout()
        self.cat_row.setSpacing(6)
        v.addLayout(self.cat_row)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.viewport().setAutoFillBackground(False)
        self.holder = QWidget()
        self.holder.setStyleSheet("background: transparent;")
        self.list_lay = QVBoxLayout(self.holder)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(8)
        sc.setWidget(self.holder)
        v.addWidget(sc, 1)

        row = QHBoxLayout()
        self.b_update_all = small_button("全部更新", self._update_all, alpha, width=100)
        row.addWidget(self.b_update_all)
        row.addStretch(1)
        row.addWidget(small_button("重新读取", self.reload, alpha, width=100))
        row.addWidget(small_button("关闭", self.accept, alpha, width=80))
        v.addLayout(row)

        self._build_cats()
        self.reload()

    # ---------- 分类 ----------
    def _cats(self):
        out = []
        for m in self.mods:
            c = str(m.get("category") or "").strip()
            if c and c not in out:
                out.append(c)
        return [ALL_CATS] + out

    def _build_cats(self):
        while self.cat_row.count():
            it = self.cat_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                try:
                    w.deleteLater()
                except Exception:
                    pass
        for c in self._cats():
            b = small_button(("· " + c + " ·") if c == self.cat else c,
                             lambda _c=c: self._set_cat(_c), self.alpha, width=0)
            try:
                b.setMinimumWidth(64)
            except Exception:
                pass
            self.cat_row.addWidget(b)
        self.cat_row.addStretch(1)

    def _set_cat(self, c):
        self.cat = c
        self._build_cats()
        self._render_list()

    # ---------- 数据 ----------
    def reload(self):
        self.mods, self.src = fetch_index()
        self.installed = installed_versions()
        if not self.mods:
            self.hint.setText("没读到模块清单（可能没网或被限流）。\n" + self.src)
            self._render_list()
            return
        self._build_cats()
        self._render_list()

    def _visible(self):
        kw = (self.search.text() or "").strip().lower()
        out = []
        for m in self.mods:
            if self.cat != ALL_CATS and str(m.get("category") or "") != self.cat:
                continue
            if kw:
                blob = " ".join(str(m.get(k) or "") for k in
                                ("name", "key", "desc", "author")).lower()
                if kw not in blob:
                    continue
            out.append(m)
        return out

    def _updatable(self):
        out = []
        for m in self.mods:
            k = str(m.get("key") or "")
            if k in self.installed and is_newer(m.get("version"), self.installed.get(k)):
                out.append(m)
        return out

    def _render_list(self):
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                try:
                    w.deleteLater()
                except Exception:
                    pass
        if not self.mods:
            return
        vis, up = self._visible(), self._updatable()
        self.hint.setText(
            f"共 {len(self.mods)} 个模块（来源：{self.src}）"
            + (f"，其中 {len(up)} 个有新版本" if up else "")
            + ("　已装：" + "、".join(sorted(self.installed)) if self.installed else ""))
        try:
            self.b_update_all.setEnabled(bool(up))
        except Exception:
            pass
        for m in vis:
            self.list_lay.addWidget(self._row(m, self.installed))
        if not vis:
            lab = QLabel("没有符合条件的模块")
            lab.setStyleSheet(label_qss(T.DIM, 12))
            self.list_lay.addWidget(lab)
        self.list_lay.addStretch(1)

    # ---------- 一行 ----------
    def _row(self, m, installed):
        card = Card(self.holder, alpha=200)
        h = QHBoxLayout(card)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)
        mid = QVBoxLayout()
        mid.setSpacing(2)

        cat = str(m.get("category") or "").strip()
        upd = str(m.get("updated") or "").strip()
        star = "★ " if m.get("featured") else ""
        head = (f"{star}{m.get('name') or m.get('key')}　"
                f"<span style='color:{T.DIM}'>v{m.get('version', '?')} · "
                f"{(m.get('author') or '匿名')}"
                + (f" · {cat}" if cat else "")
                + (f" · {upd}" if upd else "")
                + "</span>")
        t = QLabel(head)
        t.setStyleSheet(label_qss(T.TEXT, 13, True))
        t.setWordWrap(True)
        mid.addWidget(t)

        d = QLabel(str(m.get("desc") or ""))
        d.setStyleSheet(label_qss(T.DIM, 12))
        d.setWordWrap(True)
        mid.addWidget(d)

        chg = str(m.get("changelog") or "").strip()
        if chg:
            c = QLabel("更新：" + chg)
            c.setStyleSheet(label_qss(T.DIM, 11))
            c.setWordWrap(True)
            mid.addWidget(c)
        h.addLayout(mid, 1)

        key = str(m.get("key") or "")
        local = installed.get(key, "")
        if key in installed:
            if is_newer(m.get("version"), local):
                h.addWidget(QLabel(f"已装 v{local}"))
                h.addWidget(small_button("更新", lambda _m=m: self._install(_m),
                                         self.alpha, width=64))
            else:
                h.addWidget(QLabel(f"已装 v{local}（最新）"))
        else:
            h.addWidget(small_button("下载", lambda _m=m: self._install(_m),
                                     self.alpha, width=64))
        return card

    # ---------- 装 ----------
    def _install(self, m):
        blob, how = download(m)
        if blob is None:
            self.hint.setText("下载失败：" + how)
            return
        was = str(m.get("key")) in self.installed
        ok, info = save_module(m, blob)
        if not ok:
            self.hint.setText("保存失败：" + info)
            return
        self.hint.setText(
            f"{'已更新' if was else '已下载'}：{m.get('name') or m.get('key')} "
            f"v{m.get('version')}（来源 {how}）—— 回到「定时启动」页即可使用。")
        self.reload()

    def _update_all(self):
        ups = self._updatable()
        if not ups:
            return
        ok_n, bad = 0, []
        for m in ups:
            blob, how = download(m)
            if blob is None:
                bad.append(f"{m.get('key')}({how})")
                continue
            ok, info = save_module(m, blob)
            if ok:
                ok_n += 1
            else:
                bad.append(f"{m.get('key')}({info})")
        self.hint.setText(f"全部更新完成：成功 {ok_n} 个"
                          + (f"，失败 {len(bad)} 个：" + "、".join(bad[:3]) if bad else ""))
        self.reload()
