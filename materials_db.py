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
