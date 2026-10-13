# -*- coding: utf-8 -*-
"""外部模块导入（声明式，不执行第三方代码）。

设计（2026-10-13 用户要求"以后定制的模块发给别人可以直接导入"）：
    · 自定义模块 = 一个 **JSON 文件**（`.sgmod.json`），只声明"到点做什么"
    · 支持的动作类型复用程序已有的能力：`exe`（启动程序 + 参数）、`url`（打开网址）
    · **不执行任何外部代码** —— 这样发来发去也不担心有人塞恶意脚本，
      同时我们能保证它一定能跑起来
    · 导入后放进 `data/modules/`，在「添加模块 / 卸载模块」里出现，可装可卸
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths                                                        # noqa: E402

MODULE_SUFFIX = ".sgmod.json"
ACTION_TYPES = ("exe", "url")


def modules_dir(base=None):
    d = Path(base or paths.app_dir()) / "data" / "modules"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(text):
    s = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", str(text or "").strip())
    return (s or "module")[:40]


def parse_module_json(text, source=""):
    """校验并规范一个模块定义。返回规范化的 dict，不合法就抛 ValueError。

    规范后的形状：
        {"name": str, "desc": str, "version": int, "source": str,
         "actions": [{"type": "exe", "label": str, "path": str, "args": [str],
                      "delay": int},
                     {"type": "url", "label": str, "url": str, "delay": int}]}
    """
    try:
        raw = json.loads(text)
    except Exception as e:
        raise ValueError(f"不是合法的 JSON：{e}") from None
    if not isinstance(raw, dict):
        raise ValueError("顶层必须是一个对象")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("缺少 name（模块名字）")
    if len(name) > 24:
        raise ValueError("name 太长（最多 24 个字）")
    acts = raw.get("actions")
    if not isinstance(acts, list) or not acts:
        raise ValueError("缺少 actions（到点要做什么，至少一条）")
    if len(acts) > 10:
        raise ValueError("actions 太多了（最多 10 条）")
    out_acts = []
    for i, a in enumerate(acts, 1):
        if not isinstance(a, dict):
            raise ValueError(f"第 {i} 条 actions 不是对象")
        t = str(a.get("type") or "").strip().lower()
        if t not in ACTION_TYPES:
            raise ValueError(f"第 {i} 条 type 不支持：{t or '（空）'}"
                             f"（只支持 {'/'.join(ACTION_TYPES)}）")
        try:
            delay = max(0, int(a.get("delay") or 0))
        except Exception:
            delay = 0
        label = str(a.get("label") or "").strip() or (
            "启动程序" if t == "exe" else "打开网页")
        item = {"type": t, "label": label, "delay": delay}
        if t == "exe":
            p = str(a.get("path") or "").strip()
            if not p:
                raise ValueError(f"第 {i} 条缺少 path（程序路径）")
            args = a.get("args") or []
            if isinstance(args, str):
                args = [args]
            if not isinstance(args, list) or any(
                    not isinstance(x, (str, int, float)) for x in args):
                raise ValueError(f"第 {i} 条 args 必须是字符串数组")
            item["path"] = p
            item["args"] = [str(x) for x in args]
        else:
            u = str(a.get("url") or "").strip()
            if not u.lower().startswith(("http://", "https://")):
                raise ValueError(f"第 {i} 条 url 必须以 http:// 或 https:// 开头")
            item["url"] = u
        out_acts.append(item)
    return {"name": name,
            "desc": str(raw.get("desc") or "").strip()[:60],
            "version": int(raw.get("version") or 1),
            "source": str(source or ""),
            "actions": out_acts}


def module_files(base=None):
    """已导入的外部模块文件（按名字排序）"""
    d = modules_dir(base)
    return sorted([p for p in d.glob("*" + MODULE_SUFFIX) if p.is_file()],
                  key=lambda p: p.name.lower())


def external_modules(base=None):
    """已导入的外部模块列表（坏文件跳过，不让一个坏模块拖垮整个页面）"""
    out = []
    for f in module_files(base):
        try:
            info = parse_module_json(f.read_text(encoding="utf-8"), source=str(f))
            info["key"] = "ext:" + f.name[:-len(MODULE_SUFFIX)]
            info["file"] = str(f)
            out.append(info)
        except Exception:
            continue
    return out


def import_module_file(src, base=None):
    """把一个 .sgmod.json 导入进来。返回 (模块 dict, 说明)；失败抛 ValueError。"""
    src = Path(src)
    if not src.is_file():
        raise ValueError("文件不存在")
    try:
        text = src.read_text(encoding="utf-8")
    except Exception as e:
        raise ValueError(f"读不了这个文件：{e}") from None
    info = parse_module_json(text, source=str(src))     # 先校验，坏的绝不落盘
    d = modules_dir(base)
    target = d / (_slug(info["name"]) + MODULE_SUFFIX)
    n = 2
    while target.exists():                              # 重名自动加序号，不覆盖
        target = d / (_slug(info["name"]) + f"_{n}" + MODULE_SUFFIX)
        n += 1
    target.write_text(json.dumps(
        {"name": info["name"], "desc": info["desc"], "version": info["version"],
         "actions": info["actions"]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    info["key"] = "ext:" + target.name[:-len(MODULE_SUFFIX)]
    info["file"] = str(target)
    return info, f"已导入模块「{info['name']}」（{len(info['actions'])} 个动作）"


def remove_module_file(key, base=None):
    """删除一个外部模块文件。key 形如 ext:xxx"""
    if not str(key).startswith("ext:"):
        return False
    name = str(key)[4:] + MODULE_SUFFIX
    p = modules_dir(base) / name
    try:
        if p.is_file():
            p.unlink()
            return True
    except Exception:
        pass
    return False


def export_module_file(key, dest, base=None):
    """把某个外部模块另存出去（方便分享给别人）"""
    if not str(key).startswith("ext:"):
        raise ValueError("只有外部模块能导出")
    p = modules_dir(base) / (str(key)[4:] + MODULE_SUFFIX)
    if not p.is_file():
        raise ValueError("找不到这个模块文件")
    shutil.copy2(p, Path(dest))
    return Path(dest)


def external_steps(c):
    """已启用的外部模块 → 到点要执行的步骤（跟 live_steps 同一个形状）"""
    if not c:
        return []
    enabled = c.get("external_on") or {}
    if not isinstance(enabled, dict):
        return []
    steps = []
    for m in external_modules():
        if not enabled.get(m["key"]):
            continue
        for a in m["actions"]:
            if a["type"] == "exe":
                steps.append({"label": f"{m['name']}：{a['label']}", "exe": a["path"],
                              "args": list(a.get("args") or []), "url": "",
                              "steam_url": "", "delay": a.get("delay", 0)})
            else:
                steps.append({"label": f"{m['name']}：{a['label']}", "exe": "",
                              "args": [], "url": a["url"], "steam_url": "",
                              "delay": a.get("delay", 0)})
    return steps
