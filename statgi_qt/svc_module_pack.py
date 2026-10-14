# -*- coding: utf-8 -*-
"""模块包（带模块文件的分享包）。

用户要的（2026-10-15）：
    · 分享时**把用到的模块文件一起带上** → 对方拿到后还能按自己需求微调 ✓
    · 导入时**先看本地有没有这些模块** → 没有才装 ✓ 有了就跳过（不覆盖人家的 ✗）

包的结构（就是一个 zip，后缀 .sgmodpack.zip）：
    StatGI模块包/
        module.sgmod.json      ← 配置（actions / 名称 / 说明 …）
        modules/live/…         ← 用到的模块文件夹（整份带上）
        modules/hang/…
        README.txt             ← 给人看的两句话

兼容：还支持**裸的** `.sgmod.json`（老文件照样能导入 ✓）。
"""
import json
import re
import shutil
import zipfile
from pathlib import Path

PACK_MARK = "StatGI模块包/module.sgmod.json"
PACK_README = "StatGI模块包/README.txt"
PREFIX = "StatGI模块包/"
EXT = ".sgmodpack.zip"

README = """这是 StatGI 的模块包。

怎么用：
  · 打开 StatGI → 定时启动 → 「添加模块」→ 选这个文件 → 自动装好
  · 里面附带了它用到的模块文件；如果你本地已经有同样的模块，会跳过、不覆盖

想自己改：
  · 用记事本打开 module.sgmod.json，里面的路径改成你自己电脑上的即可
"""


def _mod_roots():
    """能放模块的地方（跟程序找模块的顺序一致）"""
    out = []
    try:
        import modules as M
        for p in (getattr(M, "ROOT_MODULES", None), getattr(M, "MODULE_FILES", None),
                  getattr(M, "HERE", None)):
            if p is not None:
                out.append(Path(p))
    except Exception:
        pass
    return out


def _mod_version(mod_dir):
    """从模块文件夹的 module.py 里读 VERSION（读不到就当空）"""
    try:
        f = Path(mod_dir) / "module.py"
        m = re.search(r'^\s*VERSION\s*=\s*["\']([^"\']+)["\']',
                      f.read_text(encoding="utf-8"), re.M)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def _ver_tuple(v):
    import re as _re
    nums = _re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in nums) if nums else ()


def _is_newer(remote, local):
    a, b = _ver_tuple(remote), _ver_tuple(local)
    if not a:
        return False
    if not b:
        return True
    return a > b


def find_module_dir(name):
    """按名字找模块文件夹（找到就返回路径，找不到 None）"""
    for r in _mod_roots():
        try:
            d = Path(r) / str(name)
            if d.is_dir() and (d / "module.py").is_file():
                return d
        except Exception:
            continue
    return None


def make_pack(dst_zip, payload, module_keys=()):
    """把配置 + 用到的模块文件打成一个包。

    dst_zip   目标文件名（会自动补 .sgmodpack.zip）
    payload   配置 dict（.sgmod.json 的内容）
    module_keys  要带上的模块名（例如 ["live", "hang"]）
    返回 (成功?, 说明)
    """
    dst = Path(dst_zip)
    if not str(dst).lower().endswith(".zip"):
        dst = Path(str(dst) + EXT)
    packed, missing = [], []
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(PREFIX + "module.sgmod.json",
                       json.dumps(payload, ensure_ascii=False, indent=2))
            z.writestr(PACK_README, README)
            for key in module_keys:
                d = find_module_dir(key)
                if d is None:
                    missing.append(str(key))
                    continue
                for f in sorted(d.rglob("*")):
                    if f.is_file() and "__pycache__" not in f.parts:
                        rel = f.relative_to(d.parent)          # 形如 live/ui.py
                        z.write(f, PREFIX + "modules/" + str(rel).replace("\\", "/"))
                packed.append(str(key))
    except Exception as e:
        return False, f"打包失败：{type(e).__name__}: {e}"
    kb = dst.stat().st_size / 1024 if dst.is_file() else 0
    msg = f"已保存：{dst.name}（{kb:.0f} KB）"
    if packed:
        msg += "\n附带了模块文件：" + "、".join(packed)
    if missing:
        msg += "\n（没找到这些模块，未附带：" + "、".join(missing) + "）"
    return True, msg


def is_pack(path):
    """这个文件是不是"模块包"（zip 且里面有 module.sgmod.json）"""
    p = Path(path)
    if not p.is_file() or p.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
        return any(n.endswith("module.sgmod.json") for n in names)
    except Exception:
        return False


def peek(path):
    """看看包里有什么（给界面提示用）"""
    p = Path(path)
    out = {"config": None, "modules": []}
    try:
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.endswith("module.sgmod.json"):
                    out["config"] = json.loads(z.read(n).decode("utf-8-sig"))
                elif n.startswith(PREFIX + "modules/") and n.count("/") >= 2:
                    key = n.split("/")[2]
                    if key and key not in out["modules"]:
                        out["modules"].append(key)
    except Exception:
        pass
    return out


def _packed_version(z, mod_key):
    """从包里读某个模块的版本号（读不到就当空）"""
    try:
        txt = z.read(PREFIX + "modules/" + mod_key + "/module.py").decode(
            "utf-8", "replace")
        m = re.search(r'^\s*VERSION\s*=\s*["\']([^"\']+)["\']',
                      txt, re.M)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def import_pack(src_zip, ask=None):
    """导入一个模块包。

    返回 (成功?, 说明文字)
    做法：
        ① 装配置（放进 data/modules/，跟裸的 .sgmod.json 一样）
        ② 对包里附带的每个模块：本地**没有**才拷进去；有就跳过 ✓（不覆盖）
    """
    src = Path(src_zip)
    if not is_pack(src):
        return False, "这个文件不是 StatGI 模块包"
    try:
        import svc_modules as S
        target = Path(S.modules_dir())
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"找不到模块目录：{type(e).__name__}: {e}"

    installed, skipped, failed, updated, kept = [], [], [], [], []
    try:
        with zipfile.ZipFile(src) as z:
            # ① 配置
            cfg_name = None
            for n in z.namelist():
                if n.endswith("module.sgmod.json"):
                    cfg_name = n
                    break
            if cfg_name is None:
                return False, "包里没有 module.sgmod.json"
            data = z.read(cfg_name)
            try:
                payload = json.loads(data.decode("utf-8-sig"))
            except Exception as e:
                return False, f"包里的配置读不了：{e}"
            key = str(payload.get("key") or "module")
            (target / (key + ".sgmod.json")).write_bytes(data)

            # ② 模块文件：本地没有才装
            keys = [n.split("/")[2] for n in z.namelist()
                    if n.startswith(PREFIX + "modules/") and n.count("/") >= 2]
            for mod_key in sorted(set(keys)):
                if not mod_key:
                    continue
                local_dir = find_module_dir(mod_key)
                if local_dir is not None:
                    # ★ C 方案：本地已有 → 比版本
                    local_v = _mod_version(local_dir)
                    pack_v = _packed_version(z, mod_key)
                    if _is_newer(pack_v, local_v):
                        # 分享文件内的更新 → 按用户指定的文案问一句
                        take = False
                        if ask is not None:
                            try:
                                take = bool(ask(mod_key, local_v, pack_v))
                            except Exception:
                                take = False
                        if take:
                            updated.append(mod_key)
                        else:
                            kept.append((mod_key, local_v, pack_v))
                        if not take:
                            continue
                    else:
                        skipped.append(mod_key)
                        continue
                dst_dir = None
                for r in _mod_roots():
                    try:
                        Path(r).mkdir(parents=True, exist_ok=True)
                        dst_dir = Path(r) / mod_key
                        break
                    except Exception:
                        continue
                if dst_dir is None:
                    failed.append(mod_key)
                    continue
                try:
                    for n in z.namelist():
                        if not n.startswith(PREFIX + "modules/" + mod_key + "/"):
                            continue
                        if n.endswith("/"):
                            continue
                        rel = n[len(PREFIX + "modules/" + mod_key + "/"):]
                        out = dst_dir / rel
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(n))
                    installed.append(mod_key)
                except Exception:
                    failed.append(mod_key)
    except Exception as e:
        return False, f"导入失败：{type(e).__name__}: {e}"

    lines = [f"模块包已导入：{payload.get('name') or key}"]
    if installed:
        lines.append("装上了附带的模块：" + "、".join(installed)
                     + "（重启程序后生效）")
    if skipped:
        lines.append("这些模块你本地已经有，跳过了：" + "、".join(skipped))
    if failed:
        lines.append("这些没装成：" + "、".join(failed))
    lines.append("它要启动的程序路径可能需要改成你自己的（用记事本打开看看）。")
    return True, "\n".join(lines)
