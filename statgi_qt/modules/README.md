# 定时运行模块说明

三个业务模块集中在 `statgi_qt/module_files/`，每个模块放在自己的目录中，由公共调度页面按模块注册信息加载。页面只负责通用设置和调用模块接口；模块自己的业务配置、界面、启动动作及重置逻辑应放在本目录对应的模块文件中。

## 文件结构

```text
modules/
    __init__.py          模块注册表与动态加载器
  common.py
module_files/
  <模块目录>/
    module.py   模块名称、唯一 key、顺序和内置/外置标记
    logic.py    模块自己的探测逻辑与 steps(config)
    ui.py       模块自己的 build/collect/apply/toggle/reset/desc
```

## 公共接口

- `module.py`：提供 `KEY`、`NAME`、`DESC`、`BUILTIN`、`ORDER`。
- `logic.steps(config)`：返回标准动作列表；可使用 `label`、`exe`、`args`、`url`、`steam_url`、`cwd`、`delay`、`kill_process` 和 `pre_delay`。
- `logic.defaults()`：可选；声明该模块的默认配置字段，用于旧配置自动迁移和初始值。
- `ui.build(tab)`：构建模块自己的卡片与设置，返回 `key`、`card`、`box`、`switch`。
- `ui.collect(tab, config)`：把该模块界面字段写入配置。
- `ui.apply(tab, enabled)`：更新该模块界面的启用状态和显隐。
- `ui.toggle(tab, enabled)`：可选；实现模块自己的启停保存行为。
- `ui.reset(tab, config)`：可选；卸载时清理模块自己的字段与控件。
- `ui.desc(tab)`：可选；提供模块卡片摘要。
- `ui.module_tools(tab)`：可选；提供该模块自己的工具按钮（如查看该程序日志）。

主页面不应根据模块 key 分支处理 OBS、浏览器或 BetterGI 字段。新增模块应通过注册信息和这些通用接口接入。删除某个可选模块时，应同时确认其他模块和公共内核不再直接引用它的业务字段。

## 配置保存

公共调度项保存在 `autostart` 下；模块开关放在 `modules` 映射；各模块自己的设置放在 `module_config` 下，以模块 key 分区。旧版顶层模块字段会在读取时迁入对应分区。

## 当前模块

| 模块 | 主要职责 |
|---|---|
| `bgi` | BetterGI 路径、配置组及启动/监测动作 |
| `live` | OBS 启动和开播参数 |
| `hang` | 直播间网址与浏览器启动 |

外部声明式模块仍由 `svc_modules.py` 处理；它不执行模块携带的任意 Python 代码。

“打开目录”优先打开 `module_files/`；公共代码和说明保留在 `modules/`。
