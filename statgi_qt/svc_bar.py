# -*- coding: utf-8 -*-
"""悬浮窗配置服务 —— UI 只跟这里打交道，不直接 import bar_items。

第 4 步（service 层）4.5。**这是 service 层的最后一块。**

背后挡着 `bar_items`：

    data/bar_items.json    当前的动态项目列表 + 整体窗口
    data/bar_presets.json  用户自己存的预设（内置预设写在代码里）

跟第 5、6 批一样是**同签名转发**，但这一批多做了两件事：

⚠ 1) **收掉编辑器对私有函数的伸手。**
      `qt_bar_editor` 原来在两处（`_closest_preset` / `_cfg_matches`）
      各自写了一遍一模一样的：

          cand = {"window": dict(p.get("window") or bar_items.DEFAULT_WINDOW),
                  "items": [bar_items._fill_item(x) for x in ...]}

      —— 同一段代码写两遍，还去调 `bar_items` 的**私有** `_fill_item`。
      现在收成 `fill_cfg()` 一个函数。UI 不用再知道预设内部长什么样。

⚠ 2) **`bar_items` 的三个存储路径常量**（DATA_DIR / ITEMS_FILE / PRESETS_FILE）
      **故意不转发** —— 那是存储细节，UI 不该看见。
      （现在确实没有 UI 用到；`_morph` 里的测试脚本要重定向数据目录，
        仍然直接改 `bar_items`。）

⚠ 契约见根目录 `第4步-service契约.md`。
"""
import bar_items as _bar
from bar_items import (ALIGNMENTS, ALIGN_QSS, BUILTIN_PRESETS, DEFAULT_WINDOW,
                       LAYOUTS, SOURCE_DESC, SOURCE_LABEL, SOURCES,
                       all_presets, apply_preset, default_config, default_items,
                       delete_preset, format_rate, format_value, full_text,
                       is_builtin_preset, load, new_item, preset_names,
                       raw_number, rename_preset, reset, save, save_preset,
                       should_hide, user_presets)


def fill_cfg(cfg):
    """把一份配置补全成**字段完整**的形状。

    为什么要它：
      · `all_presets()` 给的是**原始项**，字段可能不全；
        而 `load()` 出来的当前配置每一项都补过默认值。
        两边字段数不一样 → JSON 永不相等 → 比对永远失败。
      · 所以预设那边也要走一遍补全才公平（原来这段在 UI 里写了两遍）。

    `cfg` 传 None / {} 也安全。
    """
    cfg = cfg or {}
    return {"window": dict(cfg.get("window") or DEFAULT_WINDOW),
            "items": [_bar._fill_item(x) for x in (cfg.get("items") or [])]}
