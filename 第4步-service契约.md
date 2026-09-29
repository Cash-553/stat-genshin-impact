# 第 4 步 · service 层契约（4.1）

> 这是 4.1「先定契约，不写代码」的产物。**先看这份，再改代码。**
> 定于 2026-09-23，第 5 批。

---

## 一、这层到底要解决什么

架构体检的原话：

```
链 A（最主要）
   没有 service 层 → UI 直接 import 业务模块 → UI 文件"什么都知道"
   → qt_pages/qt_dialogs/qt_window 膨胀 → 改一处影响别处
```

**12 个问题里 8 个同源。** 所以这层的目标只有一句话：

> **UI 只跟 `svc_*` 打交道，不再直接 import 存储 / 业务模块。**

⚠ 但要说实话 —— **"名单"和"记录"这两块的耦合，比识别管线轻得多。**
`names_db` / `sessions` 本来就是干净的数据模块，UI 直接 import 它们没出过事。
真正的硬骨头是后面两步：

```
⬜ 4.4 命令 service（capture / detector / ocr_engine 生命周期）← 线程交界，真风险
⬜ 4.5 悬浮窗 service（bar_items）← 卡着 3 条冻结需求
```

所以这一步的定位是：**先把接缝建起来 + 把验收标准立起来**，
不是"改完架构就干净了"。

---

## 二、形态怎么定

| 决定 | 理由 |
|---|---|
| **扁平 `svc_*.py`，不建包** | 跟第 2~4 批同一条约束：项目没有 `__init__.py`，靠 spec 的 `pathex` 解析。建包要全仓库改 import + 动 spec |
| **不引入单例 / 全局状态** | 现在没有，别加。设置还是从 `settings` 参数传，跟现在一样 |
| **同签名转发优先** | 先建接缝、再收逻辑。这一版**不改任何行为**，改完识别/统计结果必须一模一样 |
| **不用 `__getattr__` 动态转发** | 那样接口就"看不见"了。契约要能一眼看懂 |

---

## 三、三张契约

### 3.1 `svc_names.py` —— 名单与过滤 ✅ 本批做

**谁在用**（改之前）：

```
qt_pages.py          filters_db 10 处 / names_db 4 处   ← 黑名单白名单那一整块
qt_dlg_material.py   names_db 4 处（存成 self.db）      ← 材料名单弹窗
qt_bar_editor.py     names_db 1 处（material_set）      ← 编辑器选材料
```

**前面挡着三样**（原来 UI 各自 import）：

```
names_db         可识别名字名单            data/names.json
filters_db       黑 / 白名单配置           存在 settings 里
generated_names  内置的默认名单           材料 + 圣遗物
```

**对外提供**：跟原来**同名同签名**，改完调用处只是换个模块名。

```
名单读写   load / save / reset_to_default
名单查询   materials / artifacts / material_set / artifact_set
内置名单   builtin_names()            ← 新加的聚合（原来 UI 自己拼
                                        set(g.MATERIAL_NAMES)|set(g.ARTIFACT_NAMES)）
名单元信息 LISTS / KEY_LABEL / KEY_KIND
过滤读写   get / names_of / is_enabled / allows / defaults / normalize
空名单提醒 empty_enabled_whitelists / empty_enabled_blacklists
```

### 3.2 `svc_records.py` —— 收益记录 ✅ 本批做

**谁在用**（改之前）：

```
qt_pages.py         sessions 23 处        ← PageRecords 整页
qt_dlg_record.py    sessions 3 处         ← 改名称 / 备注
qt_dlg_material.py  sessions 1 处         ← 「只看记录里出现过的」
qt_core.py          sessions 2 处         ← 记账（add_session + make_record）
```

**前面挡着**：`sessions`（`data/sessions.json` + `data/favorites.json`）

**对外提供**：`sessions` 的公开 API 全部**同名转发**。

```
记录    load_sessions / save_sessions / add_session / clear_sessions
        new_id / record_key / make_record
显示    default_name / display_name / display_notes / format_duration / update_record
收藏    load_favorites / save_favorites / favorite_ids / is_favorite
        add_favorite / remove_favorite / clear_favorites
```

### 3.3 `svc_bar.py` —— 悬浮窗配置 ✅ 第 7 批完成

**前面挡着**：`bar_items`（`data/bar_items.json` + `data/bar_presets.json`）

**对外提供**：`bar_items` 的公开 API 同名转发（27 个名字），外加：

```
fill_cfg(cfg)   把一份配置补全成字段完整的形状
                —— 原来 UI 里写了两遍、还去调 bar_items 私有 _fill_item 的那段
```

**⚠ 故意不转发**：`DATA_DIR` / `ITEMS_FILE` / `PRESETS_FILE`
（存储细节不该露给 UI）

**⚠ 原计划这里写的是「做完它才能解冻那 3 条冻结需求」。**
开工前核对发现那 3 条**早就修好了**（侧栏黑底 / 标签框 / 材料搜索），
第 4 条（logo 名字）用户也确认不需要了 —— 冻结清单已清空。

---

## 四、明确**不做**的事

| 不做 | 为什么 |
|---|---|
| 不动 `stats` / `DailyStats` | 那是**状态层自己的模型**，`qt_core.AppState` 持有它。不是 UI 在直接读文件 |
| 不做缓存 / 校验 / LRU | 没有证据说明需要。文档「五之三」实测过：一次模糊匹配 1.2~2.9ms，占 OCR 周期的 0.79%，而 OCR 本身 660ms。**性能不是问题** |
| 不引入 DI 容器 / 单例 / 事件总线 | 现在没有，别加。加了反而多一层看不懂的东西 |
| 不改任何函数行为 | 这一版是**同签名转发**。改完识别 / 统计结果必须一模一样 |
| 不顺手改那个 `_set_visible` bug | 冻结中，见「已知问题 17」，第 7 批一起 |

---

## 五、验收标准（这一批必须满足）

```
1. UI 层里 `import names_db / filters_db / generated_names / sessions` 必须 = 0 处
   （main.py 除外 —— 它启动时的 materials_db.migrate_library 是启动流程，不是 UI）

2. UI 层调用的每一个 svc_*.X，X 必须真的存在
   （防止转发时漏掉一个名字，那要等到运行时才炸）

3. smoke_ui.py 29 步全过（所有页面 + 对话框照旧能渲染）

4. api_snapshot.py --check 通过（模块对外表面没丢东西）

5. py_compile 全过

6. 真实 data\ / config\ 一个字节没动
```

第 1、2 条写成了脚本：`_morph\check_no_direct_imports.py`。

---

## 六、4.4 命令 service —— ✅ 已完成（2026-09-23 第 6 批）

```
svc_capture.py   挡 capture / detector / ocr_engine / dataset_collector
```

**⚠ 分工是这一步的核心决定**：

```
留在 qt_core.AppState：线程 / 队列 / 停止事件 / QTimer / 生命周期
搬到 svc_capture      ：怎么跟识别管线说话
```

线程那一套一个字没动。详见 `开发状态备忘.md` 第 6 批那节。

---

## 七、完成情况（第 5 ~ 7 批）—— **第 4 步做完了**

```
✅ svc_names.py    挡 names_db + filters_db + generated_names   （第 5 批）
✅ svc_records.py  挡 sessions                                   （第 5 批）
✅ svc_capture.py  挡 capture / detector / ocr_engine / dataset_collector（第 6 批）
✅ svc_bar.py      挡 bar_items                                  （第 7 批）
```

### 4.6 的验收标准 —— **已达成**

```
UI 层（qt_window / qt_pages / qt_dialogs / qt_bar* / qt_core 等 25 个文件）
对 names_db / filters_db / generated_names / sessions / materials_db /
   detector / capture / ocr_engine / printwindow_capture / dataset_collector /
   bar_items
的直接 import = **0 处**

（main.py 除外 —— 它启动时的 materials_db.migrate_library 是启动流程，不是 UI）
```

验收脚本：`_morph\check_no_direct_imports.py`（同时检查"UI 调用的每个 svc_*.X
都真的存在"）。

### 每块 service 各自的深检脚本

```
_morph\test_svc_roundtrip.py   svc_names / svc_records：同对象 + 写路径往返
_morph\test_svc_capture.py     svc_capture.run_detector 六条路径
_morph\test_start_stop.py      端到端跑一次启动/停止监测
_morph\test_svc_bar.py         svc_bar：fill_cfg 与原内联代码逐字等价 + 预设往返
```

### ⚠ 两处**故意**没封装进去的东西

| 东西 | 为什么 |
|---|---|
| `stats.DailyStats` | 那是**状态层自己的模型**，`qt_core.AppState` 持有。不是 UI 在读文件 |
| `main.py` 的 `materials_db.migrate_library` | 启动流程（一次性材料库重置），不是 UI |

**实际接入**（比契约里写的范围宽 —— 写路径也一起接了）：

```
qt_pages.py          sessions 24 处 / filters_db 10 处 / names_db 4 处
qt_core.py           sessions 2 处
qt_dlg_record.py     sessions 3 处
qt_dlg_material.py   names_db（self.db）+ sessions 1 处 + generated_names → builtin_names()
qt_bar_editor.py     names_db 1 处
```

**验收实测**：

```
UI 层直接 import 存储模块          0 处（25 个文件扫过）
UI 调用的 svc_names.X / svc_records.X   10 + 15 个名字全部存在
函数对象身份                        37 个全是原模块本身（7+11+19）
                                    → 行为由构造保证一致
写路径往返                          11 步全过（收藏 / 改名 / 删除 / 清空）
builtin_names()                    = 873 个（跟文档「五之三」的 574+299 对上）
api_snapshot / py_compile / smoke_ui  全过（smoke 从 29 步涨到 56 步）
真实 data\ / config\                一个字节没动
```

**这次改契约了吗**：改了两次，都记在 `开发状态备忘.md` 第 5 批那节 ——
① 写路径一起接（不然接缝没意义）；② 不分页接（靠脚本兜底更可验）。
