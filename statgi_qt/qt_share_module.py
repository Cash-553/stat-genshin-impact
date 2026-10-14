# -*- coding: utf-8 -*-
"""分享配置：把当前设置做成一个模块文件。

三种去处（由用户自己决定，**不强制审核**）：
    · 自己留着用
    · 想上架 → 到 QQ 群发给作者，作者帮你放进正式模块仓库
    · 不想上架 → 直接把文件发给朋友，他在「添加模块」里选一下就能用（自由流通）

只生成声明式内容（启动程序 / 打开网址），不含任何代码。
"""
import json
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

import qt_theme as T
from qt_theme import label_qss
from qt_widgets import Card

QQ_GROUP = "1125970274"


# ---------------- 生成内容 ----------------
def _mod_cfg(c, key):
    """取某个模块的设置。

    ⚠ 2026-10-15：模块设置现在**嵌在** `module_config.<模块名>` 里
      （autostart.module_config.bgi.bgi_exe 这种），不再平铺在顶层 ✗
      —— 之前分享一直报"没有可分享的内容"就是这个原因。
      这里把"模块自己的"盖在顶层上，老的平铺写法也照样能读 ✓
    """
    base = dict(c or {})
    try:
        mc = (c or {}).get("module_config") or {}
        m = mc.get(key) or {}
        if isinstance(m, dict):
            base.update(m)
    except Exception:
        pass
    return base


def needed_modules(cfg):
    """这份配置用到了哪些模块（决定包里要附带哪几个）"""
    out = []
    try:
        c = cfg or {}
        b = _mod_cfg(c, "bgi")
        if str(b.get("bgi_exe") or "").strip():
            out.append("bgi")
        lv = _mod_cfg(c, "live")
        hg = _mod_cfg(c, "hang")
        if str(lv.get("obs_exe") or "").strip():
            out.append("live")
        if str(hg.get("live_url") or lv.get("live_url") or "").strip():
            out.append("hang")
    except Exception:
        pass
    return out


def build_from_config(cfg):
    """从设置里提取动作（只有 exe / url 两类）。提取不到就抛 ValueError。"""
    acts = []
    c = cfg or {}
    # 只看"填没填"：填了目标启动程序就收下（开关只管平时跑不跑）
    b = _mod_cfg(c, "bgi")
    exe = str(b.get("bgi_exe") or "").strip()
    groups = [str(g).strip() for g in (b.get("groups") or []) if str(g).strip()]
    if exe:
        a = {"type": "exe", "path": exe}
        if groups:
            a["args"] = ["--startGroups"] + groups
        if str(b.get("bgi_dir") or "").strip():
            a["workdir"] = str(b.get("bgi_dir")).strip()
        acts.append(a)

    lv = _mod_cfg(c, "live")
    hg = _mod_cfg(c, "hang")
    url = str(hg.get("live_url") or lv.get("live_url") or "").strip()
    obs = str(lv.get("obs_exe") or "").strip()
    if obs:
        acts.append({"type": "exe", "path": obs,
                     "args": ["--startstreaming", "--minimize-to-tray"]})
    if url:
        acts.append({"type": "url", "url": url})

    if not acts:
        raise ValueError("当前设置里没有可分享的内容。\n"
                         "请先配置 BetterGI 程序，或开启直播 / 挂机模块并填好直播间地址。")
    return acts


def _slugify(name):
    s = re.sub(r"[^0-9a-zA-Z_]+", "_", str(name or "")).strip("_").lower()
    return s or ("mod_" + time.strftime("%m%d%H%M"))


def make_payload(cfg, name, desc, author, version="1.0", category="", changelog=""):
    d = {"key": _slugify(name),
         "name": str(name or "").strip() or "我的配置",
         "desc": str(desc or "").strip(),
         "author": str(author or "").strip() or "匿名",
         "version": str(version or "").strip() or "1.0",
         "actions": build_from_config(cfg)}
    if str(category or "").strip():
        d["category"] = str(category).strip()
    if str(changelog or "").strip():
        d["changelog"] = str(changelog).strip()
    return d


def share_text(payload):
    """给"复制内容"用的纯文字（贴 QQ 群发给作者，一眼就能看懂）"""
    lines = ["【StatGI 配置分享】",
             f"名称：{payload.get('name')}",
             f"说明：{payload.get('desc')}",
             f"作者：{payload.get('author')}",
             f"版本：{payload.get('version')}"]
    if payload.get("category"):
        lines.append(f"分类：{payload.get('category')}")
    if payload.get("changelog"):
        lines.append(f"更新：{payload.get('changelog')}")
    lines += ["", "（下面是模块文件内容，整个复制给作者即可上架）", "",
              json.dumps(payload, ensure_ascii=False, indent=2)]
    return "\n".join(lines)


# ---------------- 界面 ----------------
def _primary(text, slot, alpha=255):
    """主按钮：强调色实心"""
    b = QPushButton(text)
    b.setFixedHeight(36)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background: {T.ACCENT}; color: #ffffff; border: none;"
        f" border-radius: 8px; padding: 6px 20px; font-weight: 600; }}"
        f"QPushButton:hover {{ background: {T.ACCENT}; }}")
    b.clicked.connect(slot)
    return b


def _ghost(text, slot, width=96):
    """次按钮：描边"""
    b = QPushButton(text)
    b.setFixedHeight(36)
    b.setMinimumWidth(width)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {T.TEXT};"
        f" border: 1px solid {getattr(T, 'LINE', '#3a3f45')}; border-radius: 8px;"
        f" padding: 6px 14px; }}"
        f"QPushButton:hover {{ border-color: {T.ACCENT}; color: {T.ACCENT}; }}")
    b.clicked.connect(slot)
    return b


class ShareDialog(QDialog):
    """把当前设置做成模块文件 —— 存下来随你处置。"""

    def __init__(self, parent=None, cfg=None, alpha=255):
        super().__init__(parent)
        self.cfg = cfg or {}
        self.alpha = alpha
        self.payload = None

        self.setWindowTitle("分享配置")
        self.resize(620, 560)
        self.setStyleSheet(f"background: {T.BG};")

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(14)

        # ---- 标题 ----
        head = QVBoxLayout()
        head.setSpacing(4)
        t = QLabel("分享配置")
        t.setStyleSheet(label_qss(T.ACCENT, 18, True))
        head.addWidget(t)
        sub = QLabel("把当前设置做成一个模块文件。只包含「启动程序 / 打开网址」，"
                     "不含任何代码。")
        sub.setStyleSheet(label_qss(T.DIM, 12))
        sub.setWordWrap(True)
        head.addWidget(sub)
        v.addLayout(head)

        # ---- 填信息（装在卡片里，跟程序其它地方一致）----
        box = Card(self, alpha=200)
        grid = QGridLayout(box)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        def lab(s):
            x = QLabel(s)
            x.setStyleSheet(label_qss(T.DIM, 12))
            return x

        self.f_name = QLineEdit("我的挂机配置")
        self.f_desc = QLineEdit("到点启动 BetterGI 并按顺序执行配置组")
        self.f_author = QLineEdit("")
        self.f_ver = QLineEdit("1.0")
        self.f_cat = QLineEdit("自动化")
        for w in (self.f_name, self.f_desc, self.f_author, self.f_ver, self.f_cat):
            w.setFixedHeight(32)
            w.editingFinished.connect(self._refresh)

        grid.addWidget(lab("名称"), 0, 0)
        grid.addWidget(self.f_name, 0, 1, 1, 3)
        grid.addWidget(lab("说明"), 1, 0)
        grid.addWidget(self.f_desc, 1, 1, 1, 3)
        grid.addWidget(lab("作者"), 2, 0)
        grid.addWidget(self.f_author, 2, 1)
        grid.addWidget(lab("版本"), 2, 2)
        grid.addWidget(self.f_ver, 2, 3)
        grid.addWidget(lab("分类"), 3, 0)
        grid.addWidget(self.f_cat, 3, 1)
        v.addWidget(box)

        # ---- 预览 ----
        pv = QVBoxLayout()
        pv.setSpacing(6)
        plab = QLabel("将要保存的内容")
        plab.setStyleSheet(label_qss(T.DIM, 12))
        pv.addWidget(plab)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(170)
        self.preview.setStyleSheet(
            f"QPlainTextEdit {{ background: {T.CARD}; color: {T.TEXT};"
            f" border: 1px solid {getattr(T, 'LINE', '#3a3f45')};"
            f" border-radius: 10px; padding: 10px;"
            f" font-family: Consolas, 'Courier New', monospace; font-size: 12px; }}")
        pv.addWidget(self.preview)
        v.addLayout(pv)

        # ---- 说明 + 按钮 ----
        self.hint = QLabel("")
        self.hint.setStyleSheet(label_qss(T.DIM, 11))
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_ghost("复制内容", self._copy, 104))
        row.addWidget(_ghost("保存文件", self._save, 104))
        row.addStretch(1)
        row.addWidget(_ghost("关闭", self.accept, 80))
        v.addLayout(row)

        self._refresh()

    # ---------- 交互 ----------
    def _refresh(self, *_a):
        try:
            self.payload = make_payload(self.cfg, self.f_name.text(),
                                        self.f_desc.text(), self.f_author.text(),
                                        self.f_ver.text(), self.f_cat.text())
            self.preview.setPlainText(json.dumps(self.payload, ensure_ascii=False,
                                                 indent=2))
            self.hint.setText(
                "保存后这个文件就是你的：可以直接发给朋友（他在「添加模块」里选一下就能用）；"
                f"想让它进正式仓库，就到 QQ 群 {QQ_GROUP} 发给作者。")
        except Exception as e:
            self.payload = None
            self.preview.setPlainText("")
            self.hint.setText(str(e))

    def _copy(self, *_a):
        self._refresh()
        if not self.payload:
            return
        QGuiApplication.clipboard().setText(share_text(self.payload))
        self.hint.setText(f"已复制 —— 贴到 QQ 群 {QQ_GROUP} 发给作者即可；"
                          "也可以直接发给朋友用。")

    def _save(self, *_a):
        self._refresh()
        if not self.payload:
            return
        try:
            import paths
            import svc_module_pack as P
            from PySide6.QtWidgets import QFileDialog
            start = str(Path(paths.app_dir())
                        / (self.payload["key"] + P.EXT))
            f, _ = QFileDialog.getSaveFileName(
                self, "保存模块包", start, "StatGI 模块包 (*.zip)")
            if not f:
                return
            # ★ 2026-10-15：存成"模块包"——把用到的模块文件一起带上，
            #   对方拿到后还能按自己的需求微调（本地已有同名模块则不覆盖）
            ok, msg = P.make_pack(f, self.payload, needed_modules(self.cfg))
            self.hint.setText(msg if ok else ("保存失败：" + msg))
        except Exception as e:
            self.hint.setText("保存失败：" + str(e))


def open_share(parent=None, cfg=None, alpha=255):
    """主程序调用这个"""
    try:
        dlg = ShareDialog(parent, cfg=cfg, alpha=alpha)
        dlg.exec()
        return True
    except Exception as e:
        print("[分享] 打不开：", type(e).__name__, e, flush=True)
        return False
