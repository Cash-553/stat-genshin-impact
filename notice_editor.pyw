# -*- coding: utf-8 -*-
"""StatGI 公告编辑器

写公告 → 点「发布」→ 自动写文件 + 推送到 GitHub 和 Gitee。
不用去仓库网页、不用手打 git 命令。

双击「公告编辑器.bat」就能打开（那个 bat 会用 pythonw 启动，不带黑框）。

它是怎么发布的：
    1. 把界面上的内容写成仓库根目录的 notice.json
    2. git add notice.json
    3. git commit -m "公告更新：xxx"
    4. git push        ← 一次推两边（origin 配了两个推送地址）
    用户那边最多几分钟就能看到（Gitee 服务端缓存 60~300 秒）。
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal, QThread
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QMessageBox, QDialog)

ROOT = os.path.dirname(os.path.abspath(__file__))
NOTICE = os.path.join(ROOT, "notice.json")

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

    def __init__(self, data, do_push):
        super().__init__()
        self.data = data
        self.do_push = do_push

    def run(self):
        try:
            # 1) 写文件
            with open(NOTICE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            self.log.emit(f"已写入 {NOTICE}")

            # 2) git add
            r = self._git(["add", "notice.json"])
            if r.returncode != 0:
                self.done.emit(False, "git add 失败：\n" + r.stderr)
                return
            self.log.emit("git add notice.json ✓")

            # 3) git commit
            msg = f"公告更新：{self.data.get('title', '')}"
            r = self._git(["commit", "-m", msg])
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                if "nothing to commit" in out or "无文件要提交" in out or "working tree clean" in out:
                    self.log.emit("内容跟上次一样，没有改动需要提交")
                    if not self.do_push:
                        self.done.emit(True, "内容没变化，已跳过提交")
                        return
                else:
                    self.done.emit(False, "git commit 失败：\n" + out)
                    return
            else:
                self.log.emit("git commit ✓")

            if not self.do_push:
                self.done.emit(True, "已保存到本地（没有推送）")
                return

            # 4) git push（一次推 GitHub + Gitee）
            self.log.emit("正在推送（GitHub + Gitee）…")
            r = self._git(["push"], timeout=180)
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                # 常见的两种情况，给出人话提示
                if "rejected" in out or "non-fast-forward" in out or "fetch first" in out:
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
        self.resize(760, 660)
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
                border-radius:8px; padding:8px 18px; font-size:14px;
            }}
            QPushButton:hover {{ background:#2E2E2E; }}
            QPushButton:disabled {{ color:#666; }}
        """)

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(10)

        t = QLabel("📢  StatGI 公告编辑器")
        t.setStyleSheet(f"color:{ACCENT}; font-size:20px; font-weight:700;")
        v.addWidget(t)
        sub = QLabel("写完点「发布」，会自动提交并推送到 GitHub 和 Gitee —— 不用手打 git 命令。")
        v.addWidget(sub)
        v.addSpacing(6)

        # --- ID ---
        row = QHBoxLayout()
        row.addWidget(QLabel("公告 ID"))
        self.id_edit = QLineEdit()
        row.addWidget(self.id_edit, 1)
        b_new = QPushButton("自动生成")
        b_new.setFixedWidth(110)
        b_new.clicked.connect(self.gen_id)
        row.addWidget(b_new)
        v.addLayout(row)
        tip = QLabel("换了新 ID 用户那边才会当成「新公告」提醒。发新公告一定要换。")
        tip.setStyleSheet(f"color:{DIM}; font-size:12px;")
        v.addWidget(tip)

        # --- 标题 ---
        v.addWidget(QLabel("标题"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("例：StatGI v0.9 已发布")
        v.addWidget(self.title_edit)

        # --- 正文 ---
        v.addWidget(QLabel("正文"))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText("正文，可以换行")
        self.body_edit.setMinimumHeight(200)
        v.addWidget(self.body_edit, 1)

        # --- 链接 ---
        v.addWidget(QLabel("链接（可选，用户点「打开链接」会跳这里）"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://github.com/Cash-553/stat-genshin-impact/releases")
        v.addWidget(self.url_edit)

        # --- 按钮 ---
        v.addSpacing(4)
        btns = QHBoxLayout()
        b_load = QPushButton("读取当前公告")
        b_load.clicked.connect(self.load_current)
        b_pre = QPushButton("预览")
        b_pre.clicked.connect(self.preview)
        self.b_pub = QPushButton("发布到 GitHub + Gitee")
        self.b_pub.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#08222E; border:none;"
            f" border-radius:8px; padding:9px 22px; font-size:14px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#6FD0FF; }}"
            f"QPushButton:disabled {{ background:#3A4A52; color:#888; }}")
        self.b_pub.clicked.connect(self.publish)
        btns.addWidget(b_load)
        btns.addWidget(b_pre)
        btns.addStretch(1)
        btns.addWidget(self.b_pub)
        v.addLayout(btns)

        # --- 状态 ---
        v.addWidget(QLabel("状态"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        self.log.setStyleSheet(
            f"background:#161616; color:{DIM}; border:1px solid #2A2A2A;"
            f" border-radius:8px; padding:8px; font-family:Consolas,monospace; font-size:12px;")
        v.addWidget(self.log)

        self._worker = None
        self.load_current()
        self.gen_id()

    # ---------- 小功能 ----------
    def logline(self, s):
        self.log.appendPlainText(s)

    def gen_id(self):
        """生成一个不会重复的 id：日期 + 序号"""
        base = datetime.now().strftime("%Y-%m-%d")
        n = 1
        # 看看现有的是不是同一天，是的话序号 +1
        cur = self._read_file()
        if cur and str(cur.get("id", "")).startswith(base):
            try:
                n = int(str(cur["id"]).split("-")[-1]) + 1
            except Exception:
                n = 2
        self.id_edit.setText(f"{base}-{n}")

    def _read_file(self):
        try:
            with open(NOTICE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def load_current(self):
        d = self._read_file()
        if not d:
            self.logline("没读到现有 notice.json（当新文件处理）")
            return
        self.id_edit.setText(str(d.get("id", "")))
        self.title_edit.setText(str(d.get("title", "")))
        self.body_edit.setPlainText(str(d.get("body", "")))
        self.url_edit.setText(str(d.get("url", "")))
        self.logline(f"已读取当前公告：{d.get('title', '')}")

    def _collect(self):
        return {
            "id": self.id_edit.text().strip(),
            "title": self.title_edit.text().strip(),
            "body": self.body_edit.toPlainText().strip(),
            "url": self.url_edit.text().strip(),
            "level": "info",
        }

    def preview(self):
        d = self._collect()
        if not d["title"]:
            QMessageBox.warning(self, "提示", "标题不能空着。")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("预览（用户在程序里看到的样子）")
        dlg.resize(520, 420)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        tt = QLabel(d["title"])
        tt.setWordWrap(True)
        tt.setStyleSheet(f"color:{ACCENT}; font-size:18px; font-weight:700;")
        v.addWidget(tt)
        body = QPlainTextEdit()
        body.setPlainText(d["body"])
        body.setReadOnly(True)
        v.addWidget(body, 1)
        b = QPushButton("关闭")
        b.clicked.connect(dlg.accept)
        v.addWidget(b, alignment=Qt.AlignRight)
        dlg.exec()

    # ---------- 发布 ----------
    def publish(self):
        d = self._collect()
        if not d["id"]:
            QMessageBox.warning(self, "提示", "公告 ID 不能空着（点「自动生成」也行）。")
            return
        if not d["title"]:
            QMessageBox.warning(self, "提示", "标题不能空着。")
            return

        cur = self._read_file()
        same_id = bool(cur) and str(cur.get("id", "")) == d["id"]
        if same_id and QMessageBox.question(
                self, "确认",
                f"ID 还是「{d['id']}」，跟现在的一样。\n\n"
                "这样用户那边**不会**当成新公告提醒（因为 ID 没变）。\n"
                "如果你是想修一下现有公告的文字，那没问题；\n"
                "如果是想发一条新公告，请点「自动生成」换个 ID。\n\n"
                "确定继续发布吗？") != QMessageBox.Yes:
            return

        self.b_pub.setEnabled(False)
        self.log.clear()
        self.logline("开始发布…")

        self._thread = QThread()
        self._worker = Worker(d, do_push=True)
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
