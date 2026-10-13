# -*- coding: utf-8 -*-
"""「精确模式」设置弹窗 —— 风险告知 + 主程序内下载安装 + 启动/停止/卸载。

用户的决定（2026-10-04）：**发给所有用户**，按社区惯例由使用者自担封号风险。
所以这个弹窗承担三件事：

    1. **把风险说清楚**（必须勾选才能启用；不勾选就只能看，不能装/开）
    2. **在主程序里下载安装**（Gitee 优先、自动切 GitHub、sha256 校验）
    3. 管理模块进程：启动 / 停止 / 卸载 / 打开目录

⚠ **主程序自己不注入、不读游戏内存** —— 它只负责"把模块拉起来 + 读它写的文件"。
  注入那部分是模块自己的事，模块由用户自己下载、自己承担后果。
"""
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

import config_manager
import qt_theme as T
import svc_module
from qt_dlg_card import CardDialog
from qt_theme import label_qss
from qt_widgets import bind_cb

RISK_TEXT = (
    "「精确模式」需要另外安装一个**独立模块**：它直接读取游戏进程里的掉落事件，"
    "所以数据是精确的（材料 / 狗粮 / 摩拉一笔不差），识别界面也就不用再截图了。\n\n"
    "⚠ **风险由使用者自行承担**：\n"
    "· 读取游戏进程属于第三方软件行为，违反游戏用户协议；\n"
    "· 存在**账号被封禁**的可能，且不可申诉；\n"
    "· 模块每次游戏更新后可能需要跟着更新，否则会失效（失效后本程序自动退回识别模式）。\n\n"
    "主程序本身**不注入、不读内存**，它只负责把模块启动起来、读模块写出的数据。"
    "不想要精确模式的话，卸载模块即可，本程序功能不受任何影响。"
)


class PreciseModeDialog(CardDialog):
    """状态 + 风险确认 + 下载 / 启动 / 停止 / 卸载。"""

    def __init__(self, parent=None, alpha=150, settings=None, on_save=None):
        super().__init__(parent, alpha, title="精确模式（需另装模块）", width=430)
        self.settings = settings if settings is not None else {}
        self.on_save = on_save
        self._worker = None
        self._result = None
        self._poller = QTimer(self)
        self._poller.setInterval(120)
        self._poller.timeout.connect(self._poll)

        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        self.state_label.setStyleSheet(label_qss(T.DIM, 12))

        info = QLabel(RISK_TEXT.replace("**", ""))
        info.setWordWrap(True)
        info.setStyleSheet(label_qss(T.TEXT, 12))

        # ⚠ 勾选框**自己建**（不用 `add_checkbox`）：它那个会被塞到页脚区，
        #   结果跑到按钮**下面**去了（真渲染出来才发现）。
        #   用 `add_widget` 放进内容区，顺序才是 说明 → 状态 → 确认 → 按钮。
        from PySide6.QtWidgets import QCheckBox
        self.ack = QCheckBox("我已了解风险，愿意自行承担（可能封号）")
        self.ack.setChecked(bool(self.settings.get("precise_mode", False)))
        self.ack.setCursor(Qt.PointingHandCursor)

        self.add_widget(info)
        self.add_widget(self.state_label)
        self.add_widget(self.ack)
        self.progress = self.add_progress(show=False)

        # 按钮排（用 add_layout 塞到选项区，别用整宽的确认按钮）
        row = QHBoxLayout()
        row.setSpacing(8)
        self.b_dl = self._mk_btn("下载并安装", self._download)
        self.b_run = self._mk_btn("启动模块", self._start)
        self.b_stop = self._mk_btn("停止模块", self._stop)
        row.addWidget(self.b_dl)
        row.addWidget(self.b_run)
        row.addWidget(self.b_stop)
        row.addStretch(1)
        self.add_layout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.b_un = self._mk_btn("卸载模块", self._uninstall)
        self.b_dir = self._mk_btn("打开目录", self._open_dir)
        row2.addWidget(self.b_un)
        row2.addWidget(self.b_dir)
        row2.addStretch(1)
        self.add_layout(row2)

        self.log_label = QLabel("")
        self.log_label.setWordWrap(True)
        self.log_label.setStyleSheet(label_qss(T.DIM, 11))
        self.add_widget(self.log_label)

        self.add_confirm("关闭", action=self.accept)
        self._refresh()
        self.fit_to_subtitle(0.85)

    # ------------------------------------------------------------ 小工具
    def _mk_btn(self, text, cb):
        from PySide6.QtWidgets import QPushButton
        from qt_theme import btn_qss
        b = QPushButton(text)
        b.setFixedHeight(30)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(btn_qss("normal", self._alpha))
        b.clicked.connect(bind_cb(cb))
        return b

    def _say(self, text):
        self.log_label.setText(str(text))
        try:
            QTimer.singleShot(0, lambda: None)
        except Exception:
            pass

    def _save(self):
        try:
            if self.on_save is not None:
                self.on_save()
            else:
                config_manager.save_settings(self.settings)
        except Exception:
            pass

    # ------------------------------------------------------------ 状态刷新
    def _refresh(self):
        st = svc_module.status()
        inst = svc_module.installed()
        running = svc_module.module_running()
        state = st["state"]
        if state == "online":
            txt = f"状态：**模块在供数**（{st.get('mod') or '模块'}）—— 识别已暂停"
        elif running:
            txt = "状态：模块进程在跑，但还没收到心跳（等几秒）"
        elif inst and state == "stale":
            age = st.get("age")
            txt = (f"状态：模块没在运行（上次心跳 "
                   f"{int(age)} 秒前）—— 当前用的是识别模式")
        elif inst:
            txt = "状态：已安装，未启动 —— 当前用的是识别模式"
        else:
            txt = "状态：未安装 —— 当前用的是识别模式（OCR，零风险）"
        if inst:
            txt += f"\n模块版本：{inst.get('version')}"
        self.state_label.setText(txt.replace("**", ""))

        self.b_dl.setText("检查更新" if inst else "下载并安装")
        self.b_dl.setVisible(True)
        self.b_run.setVisible(bool(inst) and not running)
        self.b_stop.setVisible(bool(running))
        self.b_un.setVisible(bool(inst))
        self.b_dir.setVisible(bool(inst))

    def _apply_enabled(self):
        """勾选框 → 设置里的 precise_mode（即时生效，不用重启监测）"""
        want = bool(self.ack.isChecked())
        if bool(self.settings.get("precise_mode", False)) != want:
            self.settings["precise_mode"] = want
            self._save()

    # ------------------------------------------------------------ 后台任务
    def _bg(self, fn, *args):
        """跑一个后台任务：结果塞进 self._result，由定时器取（避免卡界面）"""
        if self._worker is not None and self._worker.is_alive():
            self._say("上一个任务还在跑，稍等…")
            return
        self._result = None
        self.b_dl.setEnabled(False)
        self.b_run.setEnabled(False)
        self.b_un.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)

        def _run():
            try:
                self._result = ("ok", fn(*args))
            except Exception as e:
                self._result = ("err", f"{type(e).__name__}: {e}")

        self._worker = threading.Thread(target=_run, daemon=True)
        self._worker.start()
        self._poller.start()

    def _poll(self):
        if self._result is None:
            return
        self._poller.stop()
        kind, payload = self._result
        self._result = None
        self.b_dl.setEnabled(True)
        self.b_run.setEnabled(True)
        self.b_un.setEnabled(True)
        if kind == "err":
            self.progress.setVisible(False)
            self._say(f"出错了：{payload}")
        else:
            self._on_done(payload)
        self._refresh()

    # ------------------------------------------------------------ 下载安装
    def _download(self):
        if not self.ack.isChecked():
            self._say("要先勾选上面的风险确认才能下载。")
            return
        self._say("正在获取模块清单…")
        self._bg(self._install_task)

    def _install_task(self):
        """后台线程里跑：拉清单 → 下载 → 校验 sha256 → 解压安装"""
        man, ch, err = svc_module.fetch_manifest()
        if not man:
            return {"ok": False, "msg": f"拉不到模块清单：{err}"}
        self._progress_msg(f"清单来自 {ch}，版本 {man['version']}"
                           f"（{svc_module.human_size(man['size'])}）")
        import os
        import tempfile
        parts = man["sources"][0]["parts"]
        tmp = os.path.join(tempfile.gettempdir(), "statgi_mod_dl.zip")
        got = False
        last = ""
        for src in man["sources"]:
            try:
                with open(tmp, "wb") as out:
                    done = 0
                    for u in src["parts"]:
                        f = os.path.join(tempfile.gettempdir(),
                                         "statgi_mod_part")
                        svc_module.download(u, f)
                        with open(f, "rb") as fh, open(tmp, "ab") as out2:
                            while True:
                                b = fh.read(1024 * 1024)
                                if not b:
                                    break
                                out2.write(b)
                                done += len(b)
                                self._progress_bytes(done, man["size"])
                        try:
                            os.remove(f)
                        except Exception:
                            pass
                got = True
                break
            except Exception as e:
                last = f"{src.get('label')}: {type(e).__name__}: {e}"
                continue
        if not got:
            return {"ok": False, "msg": f"下载失败（{last or '所有渠道都不行'}）"}
        if man["sha256"]:
            real = svc_module.sha256_file(tmp)
            if real.lower() != man["sha256"].lower():
                return {"ok": False, "msg": "校验不一致，已丢弃（可能下载不完整）"}
        data = open(tmp, "rb").read()
        try:
            os.remove(tmp)
        except Exception:
            pass
        rec, why = svc_module.install_zip(data, sha256=man["sha256"],
                                         version=man["version"],
                                         source=ch)
        if not rec:
            return {"ok": False, "msg": f"安装失败：{why}"}
        return {"ok": True, "msg": f"装好了：{rec.get('name')} v{rec.get('version')}"
                                   f"（来自 {ch}）"}

    def _progress_msg(self, text):
        self._result = self._result      # 只更新文案
        try:
            QTimer.singleShot(0, lambda: self._say(text))
        except Exception:
            pass

    def _progress_bytes(self, done, total):
        pct = int(done * 100 / total) if total else 0
        try:
            QTimer.singleShot(
                0, lambda: self.progress.setValue(max(0, min(100, pct))))
        except Exception:
            pass

    def _on_done(self, res):
        if isinstance(res, dict):
            self._say(res.get("msg", "完成"))
            if res.get("ok"):
                self.progress.setValue(100)
                self.settings["precise_mode"] = True
                self.ack.setChecked(True)
                self._save()
        else:
            self._say("完成")
        self.progress.setVisible(False)

    # ------------------------------------------------------------ 进程管理
    def _start(self):
        pid, why = svc_module.start_module()
        self._say(f"已启动（PID {pid}）" if pid else f"启动失败：{why}")
        if pid:
            self._apply_enabled()
        self._refresh()

    def _stop(self):
        svc_module.stop_module()
        self._say("已停止模块（30 秒内自动回退识别模式）")
        self._refresh()

    def _uninstall(self):
        svc_module.uninstall()
        self.settings["precise_mode"] = False
        self.ack.setChecked(False)
        self._save()
        self._say("模块已卸载，本程序回到识别模式（功能不受影响）")
        self._refresh()

    def _open_dir(self):
        try:
            import os
            d = svc_module.module_dir()
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))            # noqa  Windows
            self._say(f"已打开：{d}")
        except Exception as e:
            self._say(f"打不开目录：{e}")

    # ------------------------------------------------------------ 关闭
    def closeEvent(self, e):
        self._poller.stop()
        self._apply_enabled()
        super().closeEvent(e)

    def accept(self):
        self._poller.stop()
        self._apply_enabled()
        super().accept()
