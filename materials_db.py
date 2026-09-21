# -*- coding: utf-8 -*-
"""
材料数据库模块
数据保存在 data/materials.json，方便以后自己添加材料。
每种材料：{"name": "材料名称", "icon": "图标文件名.png"}
"""
import json
from pathlib import Path
import paths

BASE_DIR = paths.app_dir()
DATA_DIR = BASE_DIR / "data"
MATERIALS_FILE = DATA_DIR / "materials.json"

# 初始材料列表（常见怪物掉落素材，按系列分组）
INITIAL_MATERIALS = [
    # 丘丘人面具
    "破损的面具", "污秽的面具", "不祥的面具",
    # 史莱姆
    "史莱姆凝液", "史莱姆清", "史莱姆原浆",
    # 丘丘人弓箭手
    "牢固的箭簇", "锐利的箭簇", "历战的箭簇",
    # 愚人众
    "新兵的徽记", "士官的徽记", "尉官的徽记",
    # 盗宝团
    "寻宝鸦印", "藏银鸦印", "攫金鸦印",
    # 骗骗花
    "骗骗花蜜", "微光花蜜", "原素花蜜",
    # 丘丘萨满 / 深渊法师
    "导能绘卷", "封魔绘卷", "禁咒绘卷",
    # 龙蜥 / 幼岩龙蜥
    "脆弱的骨片", "结实的骨片", "沉重的骨片",
    # 野伏众 / 海乱鬼
    "破旧的刀镡", "影打刀镡", "名刀镡",
    # 深渊法师 / 深渊使徒
    "地脉的旧枝", "地脉的枯叶", "地脉的新芽",
    # 萤术士
    "雾虚花粉", "雾虚草囊", "雾虚灯芯",
    # 遗迹系列
    "混沌装置", "混沌回路", "混沌炉心",
    # 蕈兽
    "蕈兽孢子", "荧光孢粉", "孢囊晶尘",
    # 镀金旅团
    "褪色红绸", "镶边红绸", "织金红绸",
    # 漂浮灵
    "浮游核", "浮游晶核", "浮游晶化核",
    # 深渊使徒(水/雷)
    "晦暗刻像", "夤夜刻像", "幽邃刻像",
    # 愚人众·藏镜仕女 / 讨债人（祭刀）
    "猎兵祭刀", "特工祭刀", "督察长祭刀",
    # 愚人众·雷萤/冰萤（棱镜）
    "黯淡棱镜", "混浊棱晶", "辉光棱晶",
    # 幼岩龙蜥 / 岩龙蜥（尖齿）
    "稚嫩的尖齿", "老练的坚齿", "横行霸者的利齿",
    # 丘丘王（号角）
    "沉重号角", "黑铜号角", "黑晶号角",
    # 遗迹守卫（齿轮）
    "啮合齿轮", "机关正齿轮", "奇械机芯齿轮",
    # 秘源机兵（秘源）
    "秘源机鞘", "秘源轴", "秘源真芯",
    # 蚀灭/玄莲（灵犀）
    "蚀灭的鳞羽", "蚀灭的灵犀", "蚀灭的阳焰",
    # 聚结晶（聚燃）新怪
    "聚燃的游像眼", "聚燃的命种", "聚燃的石块",
    # 纳塔/新地区怪（月铁、剑柄、横脊、执凭）
    "无秽的月铁", "残损的月铁", "空竭的月铁",
    "残缺的剑柄", "裂断的剑柄", "未熄的剑柄",
    "密固的横脊", "锲纹的横脊", "残毁的横脊",
    "磨损的执凭", "精致的执凭", "霜镌的执凭",
]


def load_materials():
    """读取材料列表；文件不存在时自动创建初始列表"""
    if MATERIALS_FILE.exists():
        try:
            data = json.loads(MATERIALS_FILE.read_text(encoding="utf-8"))
            mats = data.get("materials", [])
            if mats:
                return mats
        except Exception:
            pass
    return create_default()


def create_default():
    """创建并保存初始材料数据库"""
    mats = [{"name": n, "icon": n + ".png"} for n in INITIAL_MATERIALS]
    save_materials(mats)
    return mats


def save_materials(mats):
    """保存材料列表到 data/materials.json"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MATERIALS_FILE.write_text(
        json.dumps({"materials": mats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def reset_to_default():
    """恢复成内置材料列表（把自动登记进去的那些错名字清掉）"""
    try:
        MATERIALS_FILE.unlink()
    except FileNotFoundError:
        pass
    return create_default()


def is_builtin(name):
    """这个名字是不是内置的（不是自动登记进来的）"""
    return str(name) in set(INITIAL_MATERIALS)


# 材料库的"版本"。改动这个数字会让所有用户**下次启动时重置一次**材料库。
#
# ⚠⚠ 目前故意停在 0（= 不重置），原因见下 ⚠⚠
#
# 这个机制本来是给「清掉自动登记的那些错名字」用的。
# 但 2026-09-21 查了用户的真实材料库（147 个）之后发现：
#   **自动登记的 76 个几乎全是对的，错的是内置的 INITIAL_MATERIALS！**
#
#     内置 牢固的箭簇          / 自动登记 牢固的箭镞      ← 镞（箭头）才对
#     内置 浮游核 浮游晶核      / 自动登记 浮游干核 浮游幽核
#     内置 混沌装置 混沌回路 混沌炉心
#                              / 自动登记 混沌机关 混沌枢纽 混沌真眼
#
#   而且自动登记的名字都是**成套**出现的（卫从的木哨 / 战士的铁哨 /
#   龙冠武士的金哨…），这是 OCR 连续读对的特征，不是零星错字。
#
#   => 一旦重置，会把用户 76 个正确的名字删掉、只留下 84 个带错的，正好反了。
#
# 真要做的话顺序应该反过来：先修 INITIAL_MATERIALS 里的错字，再谈重置。
# 在那之前保持 0，别动。
#
# 0 -> 1：清掉自动登记的名字，只留内置那份（INITIAL_MATERIALS，84 个）
LIB_VERSION = 0


def migrate_library(settings):
    """按需重置材料库（一次性）。

    返回 True 表示这次动过——调用方要把 settings 存回去。
    """
    cur = int(settings.get("materials_lib_version", 0) or 0)
    if cur >= LIB_VERSION:
        return False
    reset_to_default()
    settings["materials_lib_version"] = LIB_VERSION
    return True
