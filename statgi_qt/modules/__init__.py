# -*- coding: utf-8 -*-
"""定时启动的模块目录：**一个模块一个文件夹**。

    module_files/bgi/module.py        BetterGI 模块（内置）
    module_files/live/module.py       直播插件（OBS）
    module_files/hang/module.py       直播间挂机
    modules/external/module.py   外部导入模块（读 data/modules/*.sgmod.json）

模块由注册表发现；UI、逻辑和配置入口按唯一 key 动态加载。
加载不上（没有 module.py / 元信息不全）的文件夹会被安静跳过。
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_FILES = HERE.parent / "module_files"
# 保留 modules.bgi 等导入接口，业务文件集中存放。
__path__.append(str(MODULE_FILES))


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
    out.append(MODULE_FILES)
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
    info = module_info(key)
    if not info:
        return None
    folder = info["folder"]
    preferred = Path(info["path"])
    f = preferred / "ui.py"
    candidates = [f] + [r / folder / "ui.py" for r in roots()
                        if (r / folder / "ui.py") != f]
    for f in candidates:
        try:
            if f.is_file():
                # Nested module imports (e.g. `modules.bgi.logic`) use this
                # directory as their package search path in source and frozen apps.
                if str(f.parent.parent) not in __import__("sys").path:
                    __import__("sys").path.insert(0, str(f.parent.parent))
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


def module_info(key):
    """模块唯一身份查询；界面、设置和调度均使用同一份扫描结果。"""
    return next((m for m in load_all() if m["key"] == str(key)), None)


def load_logic(key):
    """读取模块逻辑；模块不存在或逻辑文件异常时返回 None。"""
    import importlib.util
    info = module_info(key)
    if not info:
        return None
    folder = info["folder"]
    preferred = Path(info["path"])
    f = preferred / "logic.py"
    candidates = [f] + [r / folder / "logic.py" for r in roots()
                        if (r / folder / "logic.py") != f]
    for f in candidates:
        if not f.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                "statgi_logic_" + str(key), f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        except Exception:
            continue
    return None


def load_config(key, settings):
    """取模块自己的配置分区；模块之间不共享业务字段空间。"""
    all_config = (settings or {}).get("module_config") or {}
    value = all_config.get(str(key))
    return dict(value) if isinstance(value, dict) else {}


def config_defaults(key):
    """可选：从模块 logic 的 defaults() 读取模块默认设置。"""
    logic = load_logic(key)
    if logic is not None and hasattr(logic, "defaults"):
        try:
            value = logic.defaults()
            return dict(value) if isinstance(value, dict) else {}
        except Exception:
            pass
    return {}


def save_config(key, settings, values):
    """更新模块自己的配置分区，保留其他模块和公共调度配置。"""
    if not isinstance(settings, dict):
        raise TypeError("settings must be a dict")
    all_config = settings.setdefault("module_config", {})
    current = load_config(key, settings)
    current.update(values or {})
    all_config[str(key)] = current
    return current


def folder_of(key):
    for m in load_all():
        if m["key"] == key:
            return m["folder"]
    return ""
