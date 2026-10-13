# -*- coding: utf-8 -*-
"""模块仓库 —— 浏览 / 下载 / 安装别人的模块（像 BetterGI 的脚本仓库）。

远端就是那两个仓库（Gitee 优先，拉不到自动试 GitHub）：
    Gitee ：https://gitee.com/Cash553/statgi-modules
    GitHub：https://github.com/Cash-553/statgi-modules

安全：仓库里**只收 .sgmod.json**（声明式，只能"启动程序 / 打开网址"），
     不执行任何第三方代码 ✓；下载后还会按 index.json 里的 sha256 校验 ✓。
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

import qt_theme as T
import svc_modules
from qt_theme import label_qss
from qt_widgets import Card, small_button

GITEE_BASE = "https://gitee.com/Cash553/statgi-modules/raw/HEAD/"
GITEE_BASE_ALT = "https://gitee.com/Cash553/statgi-modules/raw/master/"
GITHUB_BASE = "https://raw.githubusercontent.com/Cash-553/statgi-modules/master/"
GITHUB_BASE_ALT = "https://raw.githubusercontent.com/Cash-553/statgi-modules/main/"
JSDELIVR_BASE = "https://cdn.jsdelivr.net/gh/Cash-553/statgi-modules@master/"
INDEX = "index.json"
UA = "StatGI/0.9.6 (module repo)"


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _bases():
    """按优先级给出所有下载前缀（Gitee 的 raw 要用 HEAD，master 是 404）"""
    # ⚠ 顺序：先 master（我们推的就是它），再 HEAD（Gitee 的 HEAD 别名缓存会滞后）
    return ((GITEE_BASE_ALT, "Gitee(master)"), (GITEE_BASE, "Gitee"),
            (JSDELIVR_BASE, "jsDelivr"),
            (GITHUB_BASE, "GitHub"), (GITHUB_BASE_ALT, "GitHub(main)"))


def fetch_index():
    """拉清单：Gitee 先试，失败换 GitHub。返回 (modules, 来源或错误说明)"""
    errs = []
    for base, tag in _bases():
        try:
            raw = _get(base + INDEX)
            # 容错：有人用记事本/PS 写文件会带 BOM ✗
            d = json.loads(raw.decode("utf-8-sig"))
            mods = d.get("modules") or []
            return mods, tag
        except Exception as e:
            errs.append(f"{tag}: {type(e).__name__}")
    return [], "拉不到清单（" + "，".join(errs) + "）"


def _sha_ok(blob, want):
    """校验 sha256。

    ⚠ Gitee 转发文件时可能把换行改掉（LF ↔ CRLF）→ 原样算哈希会"校验不符" ✗
      所以三种形式都试一遍，命中哪种就用哪种内容 ✓
    """
    if not want:
        return True, blob
    for v in (blob, blob.replace(b"\r\n", b"\n"), blob.replace(b"\n", b"\r\n")):
        if hashlib.sha256(v).hexdigest() == want:
            return True, v
    return False, blob


def download(item):
    """下载某个模块文件并校验；返回 (字节, 来源或错误说明)"""
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


class ModuleRepoDialog(QDialog):
    """模块仓库窗口"""

    def __init__(self, parent=None, alpha=255):
        super().__init__(parent)
        self.alpha = alpha
        self.setWindowTitle("模块仓库")
        self.resize(620, 520)
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
        row.addStretch(1)
        self.b_refresh = small_button("重新读取", self.reload, alpha, width=100)
        row.addWidget(self.b_refresh)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        v.addLayout(row)

        self.reload()

    # ---------- 列表 ----------
    def reload(self):
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                try:
                    w.deleteLater()
                except Exception:
                    pass
        mods, src = fetch_index()
        installed = {}
        try:
            for m in svc_modules.external_modules():
                installed[str(m.get("key"))] = m
        except Exception:
            pass

        if not mods:
            self.hint.setText("没读到模块清单（可能没网或被限流）。\n" + src)
            return
        self.hint.setText(f"共 {len(mods)} 个模块（来源：{src}）。"
                          f"数据来自 Gitee/GitHub 的 statgi-modules 仓库。")
        for m in mods:
            self.list_lay.addWidget(self._row(m, installed))
        self.list_lay.addStretch(1)

    def _row(self, m, installed):
        card = Card(self.holder, alpha=T.panel_alpha({}) if hasattr(T, "panel_alpha") else 200)
        h = QHBoxLayout(card)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        t = QLabel(f"{m.get('name') or m.get('key')}　"
                   f"<span style='color:{T.DIM}'>v{m.get('version', '?')} · "
                   f"{(m.get('author') or '匿名')} · {m.get('size', 0)} 字节</span>")
        t.setStyleSheet(label_qss(T.TEXT, 13, True))
        t.setWordWrap(True)
        mid.addWidget(t)
        d = QLabel(str(m.get("desc") or ""))
        d.setStyleSheet(label_qss(T.DIM, 12))
        d.setWordWrap(True)
        mid.addWidget(d)
        h.addLayout(mid, 1)

        key = str(m.get("key") or "")
        if key in installed:
            h.addWidget(QLabel("已安装"))
        else:
            b = small_button("下载", lambda: self._install(m), self.alpha, width=76)
            h.addWidget(b)
        return card

    def _install(self, m):
        blob, how = download(m)
        if blob is None:
            self.hint.setText("下载失败：" + how)
            return
        try:
            d = svc_modules.modules_dir()
            Path(d).mkdir(parents=True, exist_ok=True)
            name = str(m.get("key") or "module") + ".sgmod.json"
            f = Path(d) / name
            f.write_bytes(blob)
            self.hint.setText(f"已下载并安装：{m.get('name') or m.get('key')}"
                              f"（来源 {how}）—— 回到「定时启动」页即可使用。")
        except Exception as e:
            self.hint.setText(f"保存失败：{type(e).__name__}: {e}")
            return
        self.reload()
