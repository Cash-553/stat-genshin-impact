# -*- coding: utf-8 -*-
"""StatGI 发布工具

发新版时跑这个：
  1. 选要发布的版本（自动扫 发布版\\StatGI_v*.zip）
  2. 切成分卷（Gitee 单文件不能超过 100MB）
  3. 算整包 SHA256（程序更新前会校验，防止下载不全）
  4. 生成「一键安装.bat」（给还没有软件的人）
  5. 把分卷地址和校验值写进 发布版\\公告\\version.json
  6. 告诉你这几个文件该传到哪

输出目录：发布版\\v<版本号>\\
     StatGI_v<版本号>.part1
     StatGI_v<版本号>.part2
     一键安装.bat

双击同目录的「发布工具.bat」打开（它用 pythonw 启动，不带黑框）。

⚠ 生成的 bat 要按**系统 OEM 代码页**写盘，而且开头 chcp 要切到同一个值。
   cmd.exe 读 .bat 就是按控制台代码页解析的：
     文件 UTF-8 + cmd 按 GBK 读  → 中文乱码
     文件 GBK   + chcp 65001     → 一样乱，连路径都会读错
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QComboBox,
                               QMessageBox, QFileDialog)

HERE = os.path.dirname(os.path.abspath(__file__))


def find_repo_root(start):
    """往上找仓库根目录（有 statgi_qt/ 或 README.md 的那一层）

    为什么要「找」而不是写死往上几层：
    这个工具放在 发布版\\ 或 发布版\\发布\\ 里都可能（就被挪过一次），
    写死相对层数的话一挪位置路径全错 —— 而 pythonw 不带控制台，
    报错是**看不见**的，表现就是「双击没反应 / 只能开一次」。
    """
    p = os.path.abspath(start)
    for _ in range(8):
        if (os.path.isdir(os.path.join(p, "statgi_qt"))
                or os.path.isfile(os.path.join(p, "README.md"))):
            return p
        up = os.path.dirname(p)
        if up == p:
            break
        p = up
    return None


ROOT = find_repo_root(HERE)
PUB = os.path.join(ROOT, "发布版") if ROOT else None
VERSION_FILE = os.path.join(PUB, "公告", "version.json") if PUB else None
# 分卷输出到这里：发布版\发布\v<版本号>\
OUT_ROOT = os.path.join(PUB, "发布") if PUB else None
# 发布包（zip）放在 发布版\ 下
ZIP_DIR = PUB

CHUNK = 95 * 1024 * 1024        # 每块 95MB（Gitee 限制 100MB，留点余量）

FONT = "Microsoft YaHei UI"
BG, CARD, TEXT, DIM = "#1C1C1C", "#242424", "#E8E8E8", "#9A9A9A"
ACCENT, DANGER = "#4CC2FF", "#E06C5A"

# Gitee 发行版附件地址前缀
GITEE_RAW = "https://gitee.com/Cash553/stat-genshin-impact/releases/download"


def oem():
    """系统控制台代码页（中文 Windows = 936）"""
    try:
        cp = int(ctypes.windll.kernel32.GetOEMCP())
        if cp > 0:
            return f"cp{cp}", cp
    except Exception:
        pass
    return "cp936", 936


def sha256_of(path, on_step=None):
    h = hashlib.sha256()
    size = os.path.getsize(path)
    read = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(4 * 1024 * 1024)
            if not b:
                break
            h.update(b)
            read += len(b)
            if on_step:
                on_step(read, size)
    return h.hexdigest()


# ============================================================
INSTALLER_TMPL = '''@echo off
chcp {cp} >nul
title StatGI 一键安装
cd /d "%~dp0"

echo.
echo   ==========================================
echo      StatGI  v{ver}  一键安装
echo   ==========================================
echo.
echo   这个窗口会自动完成：下载 - 合并 - 解压
echo   中途请不要关掉它。
echo.

set "P1={p1}"
set "P2={p2}"

if exist "%P1%" if exist "%P2%" goto merge

echo   [1/3] 本目录没有安装包，正在从 Gitee 下载…
echo         （一共约 143MB，看你网速，可能要几分钟）
echo.
curl -L --fail -o "%P1%" "{u1}"
if errorlevel 1 goto fail
echo.
curl -L --fail -o "%P2%" "{u2}"
if errorlevel 1 goto fail
echo.

:merge
echo   [2/3] 正在合并两个文件…
copy /b "%P1%"+"%P2%" "StatGI_安装包.zip" >nul
if errorlevel 1 goto fail

echo   [3/3] 正在解压到 StatGI 文件夹…
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath 'StatGI_安装包.zip' -DestinationPath 'StatGI' -Force"
if errorlevel 1 goto fail

del "StatGI_安装包.zip" >nul 2>nul

echo.
echo   ==========================================
echo      装好了！
echo   ==========================================
echo.
echo   打开本目录下的 StatGI 文件夹，
echo   双击里面的 StatGI.exe 就能用了。
echo.
echo   （分卷文件不用删，以后更新会自动用上）
echo.
pause
exit /b

:fail
echo.
echo   ==========================================
echo      出错了
echo   ==========================================
echo.
echo   可能是网速太慢或网络断了，重新双击本文件再试一次就行。
echo   也可以只删掉没下完的那个分卷文件，再重试。
echo.
pause
exit /b 1
'''


# ============================================================
class Tool(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StatGI 发布工具")
        self.resize(760, 680)
        self.setStyleSheet(f"""
            QWidget {{ background:{BG}; color:{TEXT}; font-family:'{FONT}'; font-size:14px; }}
            QLabel {{ color:{DIM}; }}
            QComboBox {{
                background:{CARD}; color:{TEXT}; border:1px solid #333;
                border-radius:8px; padding:7px; font-size:13px;
            }}
            QComboBox:hover {{ border:1px solid {ACCENT}; }}
            QComboBox QAbstractItemView {{
                background:{CARD}; color:{TEXT}; border:1px solid #333;
                selection-background-color:{ACCENT}; selection-color:#08222E;
            }}
            QPushButton {{
                background:{CARD}; color:{TEXT}; border:1px solid #333;
                border-radius:8px; padding:8px 16px; font-size:13px;
            }}
            QPushButton:hover {{ background:#2E2E2E; }}
            QPushButton:disabled {{ color:#666; }}
        """)

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(9)

        t = QLabel("📦  StatGI 发布工具")
        t.setStyleSheet(f"color:{ACCENT}; font-size:20px; font-weight:700;")
        v.addWidget(t)
        sub = QLabel("把发布包切成分卷（Gitee 单个附件不能超过 100MB）"
                     "，并生成一键安装脚本。")
        v.addWidget(sub)
        v.addSpacing(6)

        # 选版本
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("要发布的版本"))
        self.dd = QComboBox()
        self.dd.currentIndexChanged.connect(self.on_pick)
        r1.addWidget(self.dd, 1)
        b_scan = QPushButton("重新扫描")
        b_scan.setFixedWidth(100)
        b_scan.clicked.connect(self.scan)
        r1.addWidget(b_scan)
        v.addLayout(r1)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(f"color:{DIM}; font-size:12px;")
        v.addWidget(self.info)

        v.addSpacing(4)
        r2 = QHBoxLayout()
        self.b_go = QPushButton("开始切割并生成")
        self.b_go.setMinimumHeight(40)
        self.b_go.setCursor(Qt.PointingHandCursor)
        self.b_go.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#08222E; border:none;"
            f" border-radius:8px; padding:10px 24px; font-size:15px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#6FD0FF; }}"
            f"QPushButton:disabled {{ background:#3A4A52; color:#888; }}")
        self.b_go.clicked.connect(self.run)
        b_open = QPushButton("打开输出目录")
        b_open.setMinimumHeight(40)
        b_open.setCursor(Qt.PointingHandCursor)
        b_open.clicked.connect(self.open_out)
        r2.addWidget(self.b_go)
        r2.addWidget(b_open)
        r2.addStretch(1)
        v.addLayout(r2)

        v.addWidget(QLabel("状态"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            f"background:#161616; color:{DIM}; border:1px solid #2A2A2A;"
            f" border-radius:8px; padding:8px; font-family:Consolas,monospace; font-size:12px;")
        v.addWidget(self.log, 1)

        self.ver = ""
        self.scan()

    # ---------- 扫描 ----------
    def scan(self):
        """扫 发布版\\StatGI_v*.zip"""
        got = []
        try:
            for f in os.listdir(ZIP_DIR):
                if not f.lower().endswith(".zip"):
                    continue
                m = re.match(r"^StatGI_v(.+)\.zip$", f, re.I)
                if not m:
                    continue
                p = os.path.join(ZIP_DIR, f)
                got.append((m.group(1), p, os.path.getsize(p)))
        except Exception:
            pass
        # 版本号新一点的排前面（按修改时间倒序更实在）
        got.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)

        self.dd.blockSignals(True)
        self.dd.clear()
        for ver, p, sz in got:
            self.dd.addItem(f"v{ver}    （{sz/1024/1024:.1f} MB）", (ver, p))
        self.dd.blockSignals(False)

        if not got:
            self.info.setText("没找到发布包 —— 发布版\\StatGI_v<版本号>.zip")
            self.b_go.setEnabled(False)
            self.logline("没找到发布包。先打包出 zip，再点「重新扫描」。")
            return
        self.b_go.setEnabled(True)
        self.on_pick(0)
        self.logline(f"扫到 {len(got)} 个发布包")

    def on_pick(self, i):
        d = self.dd.itemData(i)
        if not d:
            return
        self.ver, self.zip_path = d[0], d[1]
        out = os.path.join(OUT_ROOT, f"v{self.ver}")
        self.info.setText(
            f"发布包：{os.path.basename(self.zip_path)}\n"
            f"输出到：{out}\\    （分卷 + 一键安装.bat）")
        if os.path.isdir(out):
            try:
                old = sorted(os.listdir(out))
            except Exception:
                old = []
            if old:
                self.info.setText(self.info.text() +
                                  f"\n注意：这个目录已有 {len(old)} 个文件，会被覆盖。")

    # ---------- 干活 ----------
    def logline(self, s):
        self.log.appendPlainText(str(s))
        QApplication.processEvents()

    def open_out(self):
        d = os.path.join(HERE, f"v{self.ver}")
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)      # noqa  Windows
        except Exception as e:
            QMessageBox.warning(self, "打不开", str(e))

    def run(self):
        if not self.ver:
            return
        size = os.path.getsize(self.zip_path)
        if QMessageBox.question(
                self, "确认",
                f"要发布的是这个文件吗？\n\n{self.zip_path}\n"
                f"大小 {size/1024/1024:.1f} MB\n"
                f"版本号 v{self.ver}\n\n"
                f"会对它做：切分卷 → 算校验值 → 生成一键安装.bat → "
                f"写进 version.json"
        ) != QMessageBox.Yes:
            return

        self.b_go.setEnabled(False)
        self.log.clear()
        try:
            self.do_it()
        except Exception as e:
            self.logline(f"✗ 出错了：{type(e).__name__}: {e}")
            QMessageBox.warning(self, "出错了", f"{type(e).__name__}: {e}")
        finally:
            self.b_go.setEnabled(True)

    def do_it(self):
        ver = self.ver
        out = os.path.join(OUT_ROOT, f"v{ver}")
        stem = f"StatGI_v{ver}"

        self.logline(f"发布包：{self.zip_path}")
        size = os.path.getsize(self.zip_path)
        self.logline(f"大小  ：{size/1024/1024:.1f} MB")
        self.logline("")

        # 1) 切分卷
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out, exist_ok=True)
        n = max(1, (size + CHUNK - 1) // CHUNK)
        self.logline(f"切成 {n} 块…")
        parts = []
        with open(self.zip_path, "rb") as f:
            for i in range(1, n + 1):
                data = f.read(CHUNK)
                p = os.path.join(out, f"{stem}.part{i}")
                with open(p, "wb") as g:
                    g.write(data)
                parts.append(p)
                self.logline(f"   ✓ {os.path.basename(p)}   {len(data)/1024/1024:.1f} MB")
        self.logline("")

        # 2) 校验值
        self.logline("算整包 SHA256…")
        last = [0]

        def step(a, b):
            pct = int(a * 100 / b) if b else 0
            if pct >= last[0] + 25:
                last[0] = pct
                self.logline(f"   {pct}%")

        digest = sha256_of(self.zip_path, step)
        self.logline("   " + digest)
        self.logline("")

        # 3) 一键安装.bat
        enc, cp = oem()
        urls = [f"{GITEE_RAW}/v{ver}/{os.path.basename(p)}" for p in parts]
        text = INSTALLER_TMPL.format(ver=ver, cp=cp,
                                     p1=os.path.basename(parts[0]),
                                     p2=(os.path.basename(parts[1]) if len(parts) > 1
                                         else os.path.basename(parts[0])),
                                     u1=urls[0],
                                     u2=(urls[1] if len(urls) > 1 else urls[0]))
        bat = os.path.join(out, "一键安装.bat")
        with open(bat, "w", encoding=enc, errors="replace", newline="\r\n") as f:
            f.write(text)
        self.logline(f"✓ 生成 {os.path.basename(bat)}（{os.path.getsize(bat)} 字节）")

        # 4) 写 version.json（保留 url_github / url_gitee 等原有字段）
        try:
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                vj = json.load(f) or {}
        except Exception:
            vj = {}
        vj["version"] = ver
        gh_asset = f"StatGI_v{ver}.zip"
        vj["update"] = {
            "size": size,
            "sha256": digest,
            "sources": [
                {"label": "Gitee（国内快）", "parts": urls},
                {"label": "GitHub", "parts": [
                    str(vj.get("url_github", "")).rstrip("/")
                    + f"/download/v{ver}/{gh_asset}"]},
            ],
        }
        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(vj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        self.logline("✓ 已写进 公告\\version.json（版本号 + 分卷地址 + 校验值）")
        self.logline("")

        # 5) 告诉用户下一步
        self.logline("=" * 52)
        self.logline("  接下来你要做的")
        self.logline("=" * 52)
        self.logline("")
        self.logline(f"① Gitee 新建/编辑发行版  v{ver}，附件传这 {len(parts)+1} 个：")
        for p in parts:
            self.logline(f"     {p}")
        self.logline(f"     {bat}")
        self.logline("")
        self.logline("   ⚠ 传「发行版附件」，不能放进仓库（仓库单文件限 50M）")
        self.logline("   ⚠ 传完把**上一个版本**的分卷附件删掉！")
        self.logline("      （附件总额度只有 1G，一个版本占 143M）")
        self.logline("")
        self.logline(f"② GitHub 新建/编辑发行版  v{ver}，附件传整包：")
        self.logline(f"     {self.zip_path}")
        self.logline(f"   ⚠ 附件名必须是 {gh_asset}")
        self.logline("")
        self.logline("③ 推代码让 version.json 生效：")
        self.logline("     cd " + ROOT)
        self.logline("     git add -A && git commit -m \"发版 v" + ver + "\" && git push")
        self.logline("")
        self.logline("④ 用户怎么装：")
        self.logline("     · 已经有软件的 → 软件里点「检测更新 → 立即更新」")
        self.logline("     · 还没有软件的 → 下载「一键安装.bat」双击")
        self.logline("")
        self.logline("完成 ✓")

        QMessageBox.information(
            self, "完成",
            f"v{ver} 的分卷和一键安装脚本已经生成在：\n{out}\n\n"
            "version.json 也更新好了。\n"
            "下面「状态」里写着要传哪些文件。")


# ============================================================
CRASH_LOG = os.path.join(HERE, "发布工具_报错.log")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("StatGI 发布工具")

    if not ROOT:
        QMessageBox.critical(
            None, "找不到项目目录",
            "这个工具必须放在 StatGI 项目里面（发布版\\ 或 发布版\\发布\\ 都行）。\n\n"
            f"现在它在：\n{HERE}\n\n"
            "它要找的是仓库根目录（有 statgi_qt 或 README.md 的那一层）。")
        return 1

    w = Tool()
    w.show()
    return app.exec()


def _entry():
    """入口兜底：pythonw 没有控制台，出错必须写到文件里 + 弹个框

    不然表现就是「双击没反应」，完全不知道哪里错了。
    """
    try:
        return main()
    except Exception:
        tb = traceback.format_exc()
        try:
            with open(os.path.join(HERE, "发布工具_报错.log"), "w",
                      encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication as QA, QMessageBox as QB
            app = QA.instance() or QA(sys.argv)
            QB.critical(None, "发布工具出错了",
                        "出错了，详情写在这里：\n"
                        + os.path.join(HERE, "发布工具_报错.log")
                        + "\n\n" + tb[-800:])
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(_entry())
