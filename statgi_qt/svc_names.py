# -*- coding: utf-8 -*-
"""名单与过滤服务 —— UI 只跟这里打交道，不直接 import names_db / filters_db。

第 4 步（service 层）第一版：**同签名转发，不改任何行为**。
目的是先把"接缝"建起来：以后要合并查询、加缓存、加校验，都改这一个文件，
不用再去 qt_pages 里翻十几处。

背后挡着三样（原来 UI 各自 import）：

    names_db         可识别名字名单        data/names.json
    filters_db       黑 / 白名单配置       存在 settings 里
    generated_names  内置的默认名单        材料 + 圣遗物

用法跟原来一样，只是把模块名换掉：

    - import filters_db
    - checked=filters_db.is_enabled(settings, key)
    + import svc_names
    + checked=svc_names.is_enabled(settings, key)

⚠ 契约见根目录 `第4步-service契约.md`。要加东西先改那份，再改这里。
"""
# ---- 可识别名字名单（data/names.json）----
from names_db import (artifacts, artifact_set, load, materials, material_set,
                      reset_to_default, save)
# ---- 黑 / 白名单配置（存在 settings 里）----
from filters_db import (KEY_KIND, KEY_LABEL, LISTS, allows, defaults,
                        empty_enabled_blacklists, empty_enabled_whitelists,
                        get, is_enabled, names_of, normalize)


def builtin_names():
    """内置的默认名单（材料 + 圣遗物），用来判断某个名字是不是"自己加的"。

    这一条是**新加的聚合** —— 原来 UI（qt_dlg_material._builtin）自己去拼
    `set(g.MATERIAL_NAMES) | set(g.ARTIFACT_NAMES)`，还要自己处理生成文件缺失。
    收进来之后，UI 不用知道 generated_names 这个模块存在。

    生成文件缺失 / 损坏时退回空集（跟原来那层 try/except 的行为一致）。
    """
    try:
        import generated_names as g
        return set(g.MATERIAL_NAMES) | set(g.ARTIFACT_NAMES)
    except Exception:
        return set()
