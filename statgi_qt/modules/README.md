# 定时启动的模块（一个模块一个文件夹）

> 目标：**删掉文件夹 = 删掉模块**。删完之后清单里没有它、界面不显示卡片、
> 到点也不会执行它 —— 不是"藏起来"，是代码真的不在了。

## 目录约定

```
modules/
    __init__.py          加载器：扫描下面的文件夹，读 module.py 的元信息
    common.py            模块共用的小工具（找 exe / 脱离启动 / bat 行）
    <模块名>/
        module.py        必需：元信息（有它才算"这个模块存在"）
        logic.py         可选：干活的代码（探测、生成动作步骤）
        ui.py            可选：界面卡片
```

## module.py（必需）

```python
KEY = "hang"                  # 唯一标识（配置里用它，别乱改）
NAME = "直播间挂机"           # 界面上显示的名字
DESC = "到点用浏览器打开直播间页面挂机"
BUILTIN = False               # True = 内置（只能开关，不能卸载）
ORDER = 30                    # 界面上排前面的小
```

## logic.py（可选）

```python
def steps(c):        # c = 自动运行配置 dict
    """到点要执行什么。返回统一形状的列表：
       {"label": 中文名, "exe": 程序路径 或 "", "args": [参数...],
        "url": 网址 或 "", "steam_url": steam:// 链接 或 "", "delay": 秒}
       不想执行就返回 []（装没装、开关开没开，自己在这里判断）"""
```

## ui.py（可选）

```python
def build(tab):      # tab = AutostartTab（能拿 alpha / _c / 回调）
    """造卡片，返回：{"key","box","switch","card","uninstall_card"…}"""

def collect(tab, c):  """把界面上的值收进配置 dict c"""
def apply(tab, on):   """按模块状态显隐自己的卡片"""
def desc(tab):        """卡片下面那句说明"""
```

主程序（`AutostartTab`）只做三件事：调 `build()` 插进页面、调 `collect()` 收值、
调 `apply()` 显隐 —— 它**不认识**模块里的具体字段。

## 现状（2026-10-13）

| 模块 | module.py | logic.py | ui.py |
|---|---|---|---|
| bgi | ✅ | ❌ 还在 svc_autostart | ❌ 还在 qt_settings_tabs |
| live | ✅ | ✅ | ❌ 还在 qt_settings_tabs |
| hang | ✅ | ✅ | ✅ **完整样板** |
| external | ✅ | （用 svc_modules.py） | （弹窗里几行） |

搬运顺序建议：live 的 ui → bgi 的 logic → bgi 的 ui。
**每搬一刀都要跑 `_morph/test_autostart.py`**（剪多了编译器看不出来，只有测试能抓）。
