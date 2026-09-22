# -*- coding: utf-8 -*-
"""图标库 —— 只保留三个默认图标，其余让用户自己导入。

设计（2026-09-23 定）：
    · 界面里**只列**三个默认图标 + 用户自己导入的
    · 原来那 80 多个材料图标是程序内置的，已移到 ``icons/_已移除/`` 备份
    · 用户点「导入…」从任意位置挑图片，拷进 ``icons/``

为什么不直接删材料图标：``icons/`` 在 .gitignore 里（不进仓库），
删掉没有 git 可回滚，所以统一「移走而不是删」。
"""
import shutil
from pathlib import Path

import paths

# 三个默认图标：(显示名, 文件名)
# 文件名保持原样，免得已经存在配置里的引用失效。
# ⚠ 经典预设用的是 _bar_slot1/2/3.png，所以「摩拉/材料/狗粮」就绑这三个；
#   根目录那个 mora.png 是旧的单图，留着兼容老配置，不进下拉框。
DEFAULTS = [
    ("摩拉", "_bar_slot1.png"),
    ("材料", "_bar_slot2.png"),
    ("狗粮", "_bar_slot3.png"),
]

# 兼容老配置：这些文件名也要当成「在库里」，但不列进下拉框
HIDDEN_BUT_AVAILABLE = ["mora.png", "artifact.png"]

BACKUP_DIRNAME = "_已移除"

_IMG_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def backup_dir() -> Path:
    return paths.icons_dir() / BACKUP_DIRNAME


def default_files() -> list:
    return [f for _n, f in DEFAULTS]


def label_by_file() -> dict:
    """文件名 -> 显示名（只有三个默认图标有）"""
    return {f: n for n, f in DEFAULTS}


def _iter_png(d: Path):
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in _IMG_SUFFIXES)


def user_files() -> list:
    """用户自己导入的图标。

    排除默认三个、排除 ``_`` 开头的内部资源（``_bar_slot*`` 这类）、
    也排除 HIDDEN_BUT_AVAILABLE 那些只用来兼容老配置的旧文件。
    """
    keep = set(default_files()) | set(HIDDEN_BUT_AVAILABLE)
    return [p.name for p in _iter_png(paths.icons_dir())
            if p.name not in keep and not p.name.startswith("_")]


def available_files() -> list:
    """界面里该列的全部图标：默认三个在前，然后是用户导入的"""
    return default_files() + user_files()


def display(name: str) -> str:
    """给下拉框用的显示文字：默认图标配中文说明，导入的原样显示"""
    if not name:
        return "（无）"
    lab = label_by_file().get(name)
    return f"{lab}（{name}）" if lab else name


def is_available(name: str) -> bool:
    """文件在不在 icons/ 里 —— 「能用」和「列进下拉框」是两回事"""
    return bool(name) and (paths.icons_dir() / name).is_file()


def import_files(paths_in) -> tuple:
    """把外面的图片拷进 icons/。

    返回 (成功导入的文件名列表, 跳过的说明列表)
    """
    dst_dir = paths.icons_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    ok, skipped = [], []
    for src in paths_in:
        src = Path(src)
        if not src.is_file():
            skipped.append(f"{src.name}：找不到文件")
            continue
        if src.suffix.lower() not in _IMG_SUFFIXES:
            skipped.append(f"{src.name}：不是图片格式")
            continue
        dst = dst_dir / src.name
        if dst.exists():
            stem, i = src.stem, 2
            while (dst_dir / f"{stem}_{i}{src.suffix}").exists():
                i += 1
            dst = dst_dir / f"{stem}_{i}{src.suffix}"
        try:
            shutil.copy2(src, dst)
            ok.append(dst.name)
        except Exception as e:
            skipped.append(f"{src.name}：{e}")
    return ok, skipped


def remove_user_icon(name: str) -> bool:
    """删掉一个用户导入的图标。

    只允许删「确实是自己导入的」——默认三个、以及只在老配置里露脸的
    兼容文件（mora.png / artifact.png）都不许删。
    删之前先备份到 ``_已移除/``。
    """
    if name not in user_files():
        return False
    p = paths.icons_dir() / name
    if not p.is_file():
        return False
    try:
        b = backup_dir()
        b.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(b / name))
        return True
    except Exception:
        return False


def archive_builtin_icons(dry_run=False) -> tuple:
    """把内置的材料图标移到 ``icons/_已移除/`` 备份。

    只动「看起来是内置材料图标」的文件：PNG、不是默认三个、不以 _ 开头。
    返回 (移动列表, 跳过列表)。
    """
    moved, skipped = [], []
    keep = set(default_files())
    for p in _iter_png(paths.icons_dir()):
        if p.name in keep or p.name.startswith("_"):
            continue
        try:
            if not dry_run:
                b = backup_dir()
                b.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(b / p.name))
            moved.append(p.name)
        except Exception as e:
            skipped.append(f"{p.name}：{e}")
    return moved, skipped


# ------------------------------------------------------------
#  自动更新：别把用户导入的图标冲掉
# ------------------------------------------------------------
# 更新.bat 里 `robocopy` 用 /XD icons 整个跳过 icons 目录（见 qt_updater），
# 所以这里负责「把新版本带的图标补齐」。

ALWAYS_REPLACE = (
    "_bar_slot1.png", "_bar_slot2.png", "_bar_slot3.png",
    "mora.png", "artifact.png",
)


def bundled_icons_dir():
    """打包内置的图标目录（PyInstaller 会把 ``icons`` 放在 _MEIPASS 下）。

    开发模式下没有这个目录（返回 None）—— 那说明 icons/ 就是源目录本身，
    不需要补。
    """
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    p = Path(base) / "icons"
    return p if p.is_dir() else None


def sync_bundled_icons(log=None) -> list:
    """把新版本自带的图标补进 ``icons/``。

    规则：
      · 三个 slot + mora/artifact（外观基线）→ **永远**用新版本的覆盖，
        否则我们自己改了图标也发不出去；
      · 其余文件（新版本新增的默认图标）→ **只在缺失时**补，
        绝不覆盖 —— 用户的同名文件得以保留。

    用户自己导入的图标不会被碰（新版本里没有这些文件）。

    返回实际写入/更新的文件名列表。
    """
    src_dir = bundled_icons_dir()
    if src_dir is None:
        return []
    dst_dir = paths.icons_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for p in _iter_png(src_dir):
        dst = dst_dir / p.name
        must = p.name in ALWAYS_REPLACE
        if dst.exists() and not must:
            continue
        try:
            shutil.copy2(p, dst)
            done.append(p.name)
            if log:
                log(f"  补齐图标 {p.name}")
        except Exception as e:
            if log:
                log(f"  图标 {p.name} 没能写入：{e}")
    return done
