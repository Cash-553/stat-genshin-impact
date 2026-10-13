# -*- coding: utf-8 -*-
"""定时启动的模块目录：**一个模块一个文件夹**。

    modules/bgi/module.py        BetterGI 模块（内置）
    modules/live/module.py       直播插件（OBS）
    modules/hang/module.py       直播间挂机
    modules/external/module.py   外部导入模块（读 data/modules/*.sgmod.json）

删掉某个文件夹 = 删掉那个模块（清单里没有、界面不显示、也不执行）。
加载不上（没有 module.py / 元信息不全）的文件夹会被安静跳过 —— 不会因为
一个坏文件夹把整个页面搞崩。
"""
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def external_root():
    r"""程序旁边那个 modules 文件夹（用户能看见、能删的那个）。

    打包版里就是 `StatGI_v0.9.6\modules\`；源码运行时就放在项目根下的
    `modules\`（没有就算了，用内置的）。
    """
    import paths
    d = Path(paths.app_dir()) / "modules"
    return d


def roots():
    """模块搜索目录：**程序旁边那个优先**，内置的兜底。

    这样"删掉旁边的文件夹 = 删掉模块"；而 bgi 这种暂时只放内置的模块，
    照样能用（它不在旁边那个文件夹里）。
    """
    out = []
    ext = external_root()
    if ext.is_dir():
        out.append(ext)
    out.append(HERE)
    return out


def _iter_dirs():
    """遍历所有搜索目录（旁边的优先；同名只认先找到的那个）"""
    seen = set()
    for root in roots():
        try:
            subs = sorted(root.iterdir())
        except Exception:
            continue
        for d in subs:
            if (d.is_dir() and not d.name.startswith("_")
                    and (d / "module.py").is_file() and d.name not in seen):
                seen.add(d.name)
                yield d


def _load_one(d):
    """按文件路径直接加载（不依赖它在哪个包下面）"""
    import importlib.util
    f = d / "module.py"
    spec = importlib.util.spec_from_file_location("statgi_mod_" + d.name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_ui(key):
    """取某个模块的 ui.py（没有就返回 None）。

    通用：置顶功能靠它拿到"这个模块的开关卡片 + 选项区"，新模块自动生效。
    """
    import importlib.util
    for root in roots():
        f = root / key / "ui.py"
        try:
            if f.is_file():
                spec = importlib.util.spec_from_file_location(
                    "statgi_ui_" + key, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        except Exception:
            continue
    return None


def load_all():
    """扫描模块文件夹，返回 [{"key","name","desc","builtin","order","path"}]"""
    out = []
    for d in _iter_dirs():
        try:
            mod = _load_one(d)
        except Exception:
            continue
        try:
            name = str(getattr(mod, "NAME", "")).strip()
            if not name:
                continue
            out.append({
                "key": str(getattr(mod, "KEY", d.name)).strip() or d.name,
                "name": name,
                "desc": str(getattr(mod, "DESC", "")).strip(),
                "builtin": bool(getattr(mod, "BUILTIN", False)),
                "order": int(getattr(mod, "ORDER", 100)),
                "folder": d.name,
                "path": str(d),
            })
        except Exception:
            continue
    out.sort(key=lambda m: (m["order"], m["name"]))
    return out


def folder_of(key):
    for m in load_all():
        if m["key"] == key:
            return m["folder"]
    return ""
