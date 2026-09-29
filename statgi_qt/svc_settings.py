# -*- coding: utf-8 -*-
"""设置读写的一个**窄入口** —— 页面只该通过它碰设置。

第 4 步（service 层）5.1 的产物。为什么需要它：

    `PageSettings` 有 1346 行、7 个标签页。原来它握着整个 `AppState` ——
    那个对象上挂着 `toggle()`（**会启动识别**）、`stop()`、`snapshot()`、
    `stats`…… 一个「外观」标签页没有任何理由能碰到识别器的启停。

    换成这个对象之后，页面能干的就只有三件：读设置 / 写设置 /
    把改动推给正在跑的识别器。

⚠ 它**不是**新的一层存储：`config_manager` 仍然是唯一落盘的地方。
  这个类只是把 `AppState` 上跟设置有关的那几个方法圈出来，
  一步都不多绕 —— 所以行为跟直接调 `state.set_setting()` 完全一样。

⚠ `raw` 给出来的是**活的** settings 字典（跟 AppState 共用同一个对象）。
  只在确实需要整份字典的地方用（比如传给 `svc_names` 的那些函数）。
"""
from PySide6.QtCore import QObject


class Settings(QObject):
    """页面读写设置的唯一入口。

    （继承 QObject 只是为了让它的生命周期跟 Qt 那边一致；
      它没有自己的信号，也不持有任何 UI。）
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self._state = state

    @property
    def raw(self):
        """活的 settings 字典（跟 AppState 共用同一个对象）。"""
        return self._state.settings

    def get(self, path, default=None):
        """读一个设置项。`path` 支持点号，比如 `"stat_bar.opacity"`。"""
        return self._state.get_setting(path, default)

    def set(self, path, value):
        """改一个设置项并**立即存盘**（这个程序没有保存按钮）。"""
        self._state.set_setting(path, value)

    def apply_live(self):
        """把改动推给**正在运行**的识别线程。

        ⚠ 识别器在构造时把一部分值 copy 成自己的属性，光改 settings 它不会变，
          必须显式推一把。具体推哪几个见 `svc_capture.apply_live_settings`。
        """
        self._state.apply_live_settings()
