# -*- coding: utf-8 -*-
"""真的连一次 GitHub，验证检测更新"""
import io, os, sys, time, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = r'E:\收益识别'
os.chdir(os.path.join(ROOT, 'statgi_qt'))
sys.path.append(ROOT)

TMP = os.path.join(ROOT, '_tmp_qt_test')
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(os.path.join(TMP, 'config'), exist_ok=True)
import config_manager
from pathlib import Path
config_manager.CONFIG_DIR = Path(TMP) / 'config'
config_manager.SETTINGS_FILE = config_manager.CONFIG_DIR / 'settings.json'
config_manager.save_settings(dict(config_manager.DEFAULT_SETTINGS))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
app = QApplication(sys.argv)
_msgs = []
from PySide6.QtCore import qInstallMessageHandler
qInstallMessageHandler(lambda m, c, s: _msgs.append(s))


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


import qt_window
import qt_pages
print("本地版本 VERSION =", qt_pages.VERSION)
print("查询的仓库       =", qt_pages.UPDATE_REPO)
print()

# 先直接查一次 API，看远端到底是什么
import urllib.request
import json
try:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{qt_pages.UPDATE_REPO}/releases/latest",
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read().decode('utf-8'))
    tag = d.get('tag_name', '')
    print("远端最新 tag     =", tag)
    latest = tag[1:] if tag[:1].lower() == 'v' else tag
    print("远端最新版本     =", latest)
    print("是不是比本地新   =", qt_pages.is_newer_version(latest, qt_pages.VERSION),
          "  （本地 0.8、远端 0.7，应该是 False = 已是最新）")
except Exception as e:
    print("直接查 API 失败:", e)

print()
print("=== 走界面按钮完整跑一遍 ===")
win = qt_window.MainWindow()
win.show()
pump(1.0)
sp = win.pages[4]
win.show_page(4)
sp._on_tab(5)              # 其它
pump(0.4)
sp.update_btn.click()
for _ in range(80):
    pump(0.1)
    if sp.update_status.text() not in ("正在检测…", ""):
        break
print("   状态栏显示:", sp.update_status.text())
print("   （本地 0.8 / 远端 0.7 -> 应该是「已是最新版本（0.8）」，")
print("     绝不该弹出「发现新版本 0.7」）")

win.really_quit()
pump(0.3)
shutil.rmtree(TMP, ignore_errors=True)
print()
print("Qt 消息:", _msgs[:5] if _msgs else "无 ✓")
