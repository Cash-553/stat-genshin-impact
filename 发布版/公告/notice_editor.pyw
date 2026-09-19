# -*- coding: utf-8 -*-
"""StatGI 公告编辑器

写新公告 / 改往期公告 → 点「发布」→ 自动写文件 + 推送到 GitHub 和 Gitee。
不用去仓库网页、不用手打 git 命令。

双击同目录的「公告编辑器.bat」就能打开（那个 bat 用 pythonw 启动，不带黑框）。

它是怎么发布的：
    1. 把左侧列表里的**全部**公告写成 发布版\\公告\\notice.json（最新在最前面）
    2. git add + git commit + git push（一次推两边）
    用户那边最多几分钟就能看到（Gitee 服务端缓存 60~300 秒）。
"""
import json
import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal, QThread
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QMessageBox, QDialog, QListWidget, QListWidgetItem,
                               QSplitter)

# 本文件在 发布版/公告/ 里，往上三层才是仓库根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NOTICE_REL = "发布版/公告/notice.json"
NOTICE = os.path.join(ROOT, *NOTICE_REL.split("/"))

FONT = "Microsoft YaHei UI"
BG, CARD, TEXT, DIM = "#1C1C1C", "#242424", "#E8E8E8", "#9A9A9A"
ACCENT, DANGER = "#4CC2FF", "#E06C5A"


# ============================================================
class Worker(QObject):
    """后台干活的：写文件 + git 提交 + 推送

    为什么放后台：git push 要联网，可能好几秒，放主线程界面会假死。
    """
    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, notices, do_push):
        super().__init__()
        self.notices = notices
        self.do_push = do_push

    def run(self):
        try:
            with open(NOTICE, "w", encoding="utf-8") as f:
                json.dump({"notices": self.notices}, f, ensure_ascii=False, indent=2)
                f.write("\n")
            self.log.emit(f"已写入 {len(self.notices)} 条公告")

            r = self._git(["add", NOTICE_REL])
            if r.returncode != 0:
                self.done.emit(False, "git add 失败：\n" + (r.stderr or ""))
                return
            self.log.emit("git add ✓")

            r = self._git(["commit", "-m", "公告更新"])
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                if ("nothing to commit" in out or "无文件要提交" in out
                        or "working tree clean" in out):
                    self.log.emit("内容跟上次一样，没有改动需要提交")
                else:
                    self.done.emit(False, "git commit 失败：\n" + out)
                    return
            else:
                self.log.emit("git commit ✓")

            if not self.do_push:
                self.done.emit(True, "已保存到本地（没有推送）")
                return

            self.log.emit("正在推送（GitHub + Gitee）…")
            r = self._git(["push"], timeout=180)
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                if ("rejected" in out or "non-fast-forward" in out
                        or "fetch first" in out):
                    tip = ("推送被拒绝了：远端有你本地没有的提交。\n\n"
                           "解决办法：在仓库目录执行 git pull，然后再发布一次。")
                elif "Authentication failed" in out or "could not read Username" in out:
                    tip = ("推送需要登录。\n\n"
                           "第一次推 Gitee 会要账号：\n"
                           "  用户名 Cash553\n"
                           "  密码   填「Gitee 私人令牌」（不是登录密码）\n"
                           "令牌在 https://gitee.com/profile/personal_access_tokens 生成")
                else:
                    tip = "git push 失败：\n" + out
                self.done.emit(False, tip)
                return

            for line in out.splitlines():
                if "->" in line or line.strip().startswith("To "):
                    self.log.emit("   " + line.strip())
            self.done.emit(True, "发布成功！GitHub 和 Gitee 都更新了")

        except subprocess.TimeoutExpired:
            self.done.emit(False, "git 命令超时了（网络太慢？）")
        except Exception as e:
            self.done.emit(False, f"出错了：{type(e).__name__}: {e}")

    def _git(self, args, timeout=120):
        return subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)


# ============================================================
class Editor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StatGI 公告编辑器")
        self.resize(1020, 720)
        self.setStyleSheet(f"""
            QWidget {{ background:{BG}; color:{TEXT}; font-family:'{FONT}'; font-size:14px; }}
            QLabel {{ color:{DIM}; }}
            QLineEdit, QPlainTextEdit {{
                background:{CARD}; color:{TEXT}; border:1px solid #333;
                border-radius:8px; padding:8px; font-size:14px;
            }}
            QLineEdit:focus, QPlainTextEdit:focus {{ border:1px solid {ACCENT}; }}
            QPushButton {{
                background:{CARD}; color:{TEXT}; border:1px solid #333;
                border-radius:8px; padding:7px 14px; font-size:13px;
            }}
            QPushButton:hover {{ background:#2E2E2E; }}
            QPushButton:disabled {{ color:#666; }}
            QListWidget {{
                background:{CARD}; color:{TEXT}; border:1px solid #333;
                border-radius:8px; padding:4px; font-size:13px;
            }}
            QListWidget::item {{ padding:8px 6px; border-radius:6px; }}
            QListWidget::item:selected {{ background:{ACCENT}; color:#08222E; }}
        """)

        self.notices = []          # 全部公告（最新在前）
        self.cur = -1              # 当前编辑的是第几条

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        t = QLabel("📢  StatGI 公告编辑器")
        t.setStyleSheet(f"color:{ACCENT}; font-size:20px; font-weight:700;")
        root.addWidget(t)
        sub = QLabel("左边是全部公告（最新在最上面）。改哪条点哪条；"
                     "点「发布」会自动提交并推送到 GitHub + Gitee。")
        root.addWidget(sub)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # ---------- 左边：公告列表 ----------
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 8, 8, 0)
        lv.setSpacing(6)
        lv.addWidget(QLabel("全部公告（最新在上）"))
        self.listw = QListWidget()
        self.listw.currentRowChanged.connect(self.on_pick)
        lv.addWidget(self.listw, 1)

        row = QHBoxLayout()
        row.setSpacing(4)
        b_new = QPushButton("＋ 新建")
        b_new.clicked.connect(self.new_notice)
        b_up = QPushButton("↑")
        b_up.setFixedWidth(38)
        b_up.setToolTip("往上移（更靠前）")
        b_up.clicked.connect(lambda: self.move(-1))
        b_dn = QPushButton("↓")
        b_dn.setFixedWidth(38)
        b_dn.setToolTip("往下移")
        b_dn.clicked.connect(lambda: self.move(1))
        b_del = QPushButton("🗑")
        b_del.setFixedWidth(38)
        b_del.setToolTip("删除这条")
        b_del.setStyleSheet(
            f"QPushButton {{ background:{CARD}; color:{DANGER};"
            f" border:1px solid #4A2A2A; border-radius:8px; padding:7px; }}"
            f"QPushButton:hover {{ background:#3A2020; }}")
        b_del.clicked.connect(self.delete_notice)
        for b in (b_new, b_up, b_dn, b_del):
            row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        # ---------- 右边：编辑区 ----------
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 0, 0)
        rv.setSpacing(8)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("公告 ID"))
        self.id_edit = QLineEdit()
        r1.addWidget(self.id_edit, 1)
        b_newid = QPushButton("换个新 ID")
        b_newid.clicked.connect(self.gen_id)
        r1.addWidget(b_newid)
        rv.addLayout(r1)
        tip = QLabel("换了新 ID 用户那边才会当成「新公告」提醒。发新公告一定要换。")
        tip.setStyleSheet(f"color:{DIM}; font-size:12px;")
        rv.addWidget(tip)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("时间"))
        self.time_edit = QLineEdit()
        self.time_edit.setPlaceholderText("2026-09-20 23:10（显示给用户看的）")
        r2.addWidget(self.time_edit, 1)
        rv.addLayout(r2)

        rv.addWidget(QLabel("标题"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("例：StatGI v0.9 已发布")
        rv.addWidget(self.title_edit)

        rv.addWidget(QLabel("正文"))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText("正文，可以换行")
        rv.addWidget(self.body_edit, 1)

        rv.addWidget(QLabel("链接（可选，用户点「打开链接」会跳这里）"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "https://github.com/Cash-553/stat-genshin-impact/releases")
        rv.addWidget(self.url_edit)

        rv.addWidget(QLabel("状态"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(80)
        self.log.setStyleSheet(
            f"background:#161616; color:{DIM}; border:1px solid #2A2A2A;"
            f" border-radius:8px; padding:8px; font-family:Consolas,monospace; font-size:12px;")
        rv.addWidget(self.log)
        split.addWidget(right)
        split.setSizes([340, 660])

        # ---------- 底部按钮 ----------
        btns = QHBoxLayout()
        b_reload = QPushButton("↻ 放弃改动，重新读取")
        b_reload.clicked.connect(self.reload)
        b_pre = QPushButton("预览")
        b_pre.clicked.connect(self.preview)
        btns.addWidget(b_reload)
        btns.addWidget(b_pre)
        btns.addStretch(1)
        self.b_pub = QPushButton("发布到 GitHub + Gitee")
        self.b_pub.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#08222E; border:none;"
            f" border-radius:8px; padding:9px 22px; font-size:14px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#6FD0FF; }}"
            f"QPushButton:disabled {{ background:#3A4A52; color:#888; }}")
        self.b_pub.clicked.connect(self.publish)
        btns.addWidget(self.b_pub)
        root.addLayout(btns)

        self.reload()

    # ---------- 数据 ----------
    def logline(self, s):
        self.log.appendPlainText(s)

    def read_file(self):
        """读 notice.json —— 兼容旧的单条格式"""
        try:
            with open(NOTICE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return []
        items = d.get("notices")
        if not isinstance(items, list):
            items = [d]
        out = []
        for it in items:
            if not isinstance(it, dict) or not str(it.get("id", "")).strip():
                continue
            out.append({
                "id": str(it.get("id", "")),
                "title": str(it.get("title", "")),
                "body": str(it.get("body", "")),
                "url": str(it.get("url", "")),
                "time": str(it.get("time", "")),
            })
        return out

    def reload(self):
        self.cur = -1
        self.notices = self.read_file()
        self.refresh_list()
        self.logline(f"已读取 {len(self.notices)} 条公告")
        if self.notices:
            self.listw.setCurrentRow(0)
            self.cur = -1
            self.on_pick(0)
        else:
            for w in (self.id_edit, self.title_edit, self.url_edit, self.time_edit):
                w.clear()
            self.body_edit.clear()

    def refresh_list(self):
        self.listw.blockSignals(True)
        self.listw.clear()
        for n in self.notices:
            tm = n.get("time", "")
            it = QListWidgetItem(f"{tm}  {n.get('title', '')}".strip())
            it.setToolTip(n.get("title", ""))
            self.listw.addItem(it)
        self.listw.blockSignals(False)

    # ---------- 选择 / 编辑 ----------
    def stash_current(self):
        """把编辑区的内容存回 self.notices（切走之前先存一下）"""
        if not (0 <= self.cur < len(self.notices)):
            return
        self.notices[self.cur] = {
            "id": self.id_edit.text().strip(),
            "title": self.title_edit.text().strip(),
            "body": self.body_edit.toPlainText().strip(),
            "url": self.url_edit.text().strip(),
            "time": self.time_edit.text().strip(),
        }
        self.refresh_list()

    def on_pick(self, row):
        if row == self.cur or not (0 <= row < len(self.notices)):
            return
        if self.cur >= 0:
            self.stash_current()
        self.cur = row
        n = self.notices[row]
        self.id_edit.setText(n.get("id", ""))
        self.title_edit.setText(n.get("title", ""))
        self.body_edit.setPlainText(n.get("body", ""))
        self.url_edit.setText(n.get("url", ""))
        self.time_edit.setText(n.get("time", ""))

    def new_notice(self):
        if self.cur >= 0:
            self.stash_current()
        n = {
            "id": self.make_id(),
            "title": "",
            "body": "",
            "url": "https://github.com/Cash-553/stat-genshin-impact/releases",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.notices.insert(0, n)          # 新的放最前面
        self.refresh_list()
        self.cur = -1
        self.listw.setCurrentRow(0)
        self.on_pick(0)
        self.title_edit.setFocus()
        self.logline("新建了一条，填完记得发布")

    def make_id(self):
        """生成一个不会重复的 id：日期 + 序号"""
        base = datetime.now().strftime("%Y-%m-%d")
        n = 1
        for x in self.notices:
            if str(x.get("id", "")).startswith(base):
                n += 1
        return f"{base}-{n}"

    def gen_id(self):
        self.id_edit.setText(self.make_id())

    def move(self, d):
        r = self.listw.currentRow()
        t = r + d
        if r < 0 or not (0 <= t < len(self.notices)):
            return
        self.stash_current()
        self.notices[r], self.notices[t] = self.notices[t], self.notices[r]
        self.refresh_list()
        self.cur = -1
        self.listw.setCurrentRow(t)
        self.on_pick(t)

    def delete_notice(self):
        r = self.listw.currentRow()
        if r < 0:
            return
        title = self.notices[r].get("title", "")
        if QMessageBox.question(
                self, "确认",
                f"确定删掉这条公告吗？\n\n{title}\n\n（发布后用户那边也会消失）"
        ) != QMessageBox.Yes:
            return
        self.cur = -1
        self.notices.pop(r)
        self.refresh_list()
        if self.notices:
            row = min(r, len(self.notices) - 1)
            self.listw.setCurrentRow(row)
            self.on_pick(row)
        else:
            for w in (self.id_edit, self.title_edit, self.url_edit, self.time_edit):
                w.clear()
            self.body_edit.clear()
        self.logline("已删除一条（还没发布）")

    # ---------- 预览 / 发布 ----------
    def preview(self):
        if self.cur >= 0:
            self.stash_current()
        if not (0 <= self.cur < len(self.notices)):
            return
        n = self.notices[self.cur]
        if not n.get("title"):
            QMessageBox.warning(self, "提示", "标题不能空着。")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("预览（用户在程序里看到的样子）")
        dlg.resize(540, 430)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        tt = QLabel(n["title"])
        tt.setWordWrap(True)
        tt.setStyleSheet(f"color:{ACCENT}; font-size:18px; font-weight:700;")
        v.addWidget(tt)
        tm = QLabel(n.get("time", ""))
        tm.setStyleSheet(f"color:{DIM}; font-size:12px;")
        v.addWidget(tm)
        body = QPlainTextEdit()
        body.setPlainText(n.get("body", ""))
        body.setReadOnly(True)
        v.addWidget(body, 1)
        b = QPushButton("关闭")
        b.clicked.connect(dlg.accept)
        v.addWidget(b, alignment=Qt.AlignRight)
        dlg.exec()

    def publish(self):
        if self.cur >= 0:
            self.stash_current()
        if not self.notices:
            QMessageBox.warning(self, "提示", "一条公告都没有。")
            return
        for i, n in enumerate(self.notices):
            if not n.get("id"):
                QMessageBox.warning(self, "提示", f"第 {i+1} 条没填 ID。")
                return
            if not n.get("title"):
                QMessageBox.warning(self, "提示", f"第 {i+1} 条没填标题。")
                return
        ids = [n["id"] for n in self.notices]
        if len(ids) != len(set(ids)):
            QMessageBox.warning(self, "提示", "有两条公告的 ID 重复了，改一下再发布。")
            return

        if QMessageBox.question(
                self, "确认发布",
                f"将要发布 {len(self.notices)} 条公告到 GitHub + Gitee。\n\n"
                f"最新的一条是：\n  {self.notices[0].get('title', '')}\n\n确定吗？"
        ) != QMessageBox.Yes:
            return

        self.b_pub.setEnabled(False)
        self.log.clear()
        self.logline("开始发布…")

        self._thread = QThread()
        self._worker = Worker(self.notices, do_push=True)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self.logline)
        self._worker.done.connect(self._on_done)
        self._thread.start()

    def _on_done(self, ok, msg):
        self._thread.quit()
        self._thread.wait(3000)
        self.b_pub.setEnabled(True)
        self.logline(("✅ " if ok else "❌ ") + msg.split("\n")[0])
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "发布成功" if ok else "发布失败", msg)


# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("StatGI 公告编辑器")
    w = Editor()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
