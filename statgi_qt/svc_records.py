# -*- coding: utf-8 -*-
"""收益记录服务 —— UI 只跟这里打交道，不直接 import sessions。

第 4 步（service 层）第一版：**同签名转发，不改任何行为**。
`sessions` 的公开 API 原样搬过来，调用处只是把模块名换掉：

    - import sessions
    - sessions.load_sessions()
    + import svc_records
    + svc_records.load_sessions()

背后挡着：`sessions`（`data/sessions.json` + `data/favorites.json`）

⚠ 契约见根目录 `第4步-service契约.md`。
⚠ 这一版**故意不改任何行为** —— 换完结果必须跟换之前一模一样。
"""
from sessions import (add_favorite, add_session, clear_favorites,
                      clear_sessions, default_name, display_name,
                      display_notes, favorite_ids, format_duration,
                      is_favorite, load_favorites, load_sessions,
                      make_record, new_id, record_key, remove_favorite,
                      save_favorites, save_sessions, update_record)
