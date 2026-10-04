# -*- coding: utf-8 -*-
"""qt_dialogs —— 转发壳（兼容层）。

这里原来是 985 行、塞了 5 个互不相干的对话框。第 2 批按功能拆成了平级模块：

    qt_dlg_icons.py     ICONS_DIR / SLOTS / builtin_name / custom_name
                        / _auto_trim / IconManagerDialog
    qt_dlg_material.py  MaterialDialog
    qt_dlg_region.py    RegionSelector / select_region
    qt_dlg_record.py    RecordEditDialog / NameListDialog

⚠ **这个文件的名字必须留着** —— qt_pages / qt_window，还有 _morph 里一堆脚本，
  都还是 `import qt_dialogs` / `from qt_dialogs import XXX`。
  下面这些转发保证它们照旧能用（`api_snapshot.py` 会盯着别漏）。

⚠ 为什么不做成 `dialogs/` 包：项目是扁平模块（statgi_qt 没有 __init__.py，
  靠 StatGI.spec 的 pathex 解析），拆包要全仓库改 import + 动 spec。
  见 重构步骤细化.md 约束 1。
"""
from qt_dlg_icons import IconManagerDialog
from qt_dlg_material import MaterialDialog
from qt_dlg_region import RegionSelector, select_region
from qt_dlg_record import NameListDialog, RecordEditDialog, StopSummaryDialog
# 2026-10-04 新增：卡片式弹窗基类 + 退出确认窗
from qt_dlg_card import CardDialog, ExitDialog
