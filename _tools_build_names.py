# -*- coding: utf-8 -*-
"""从用户提供的 txt 名单生成 Python 列表，写入 materials_db.py"""
import re
from pathlib import Path

NEW_DIR = Path(__file__).resolve().parent / "新建文件夹"
ART_TXT = NEW_DIR / "原神全部具体圣遗物物品名称_2026-08-25.txt"
MAT_TXT = NEW_DIR / "原神普通与精英敌人掉落物_完整名单_2026-08-25.txt"
OUT = Path(__file__).resolve().parent / "generated_names.py"


def parse_lines(txt):
    names = []
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        name = line.split("：", 1)[-1]  # 去掉前缀（冒号后是名字）; 若无冒号则整行
        # 圣遗物 txt: "生之花：冒险家之花" → 冒险家之花
        # 材料 txt: "1. 破损的面具" → 破损的面具
        name = re.sub(r"^\d+\.\s*", "", name)  # 去掉 "1. "
        name = name.strip()
        if not name or name.isdigit():
            continue
        # 排除日期行(如 2026-08-25) 和任何含数字连字符的行
        if re.match(r"^\d{4}-\d{2}-\d{2}$", name):
            continue
        if len(name) < 2:
            continue
        # 排除标题/说明行
        if any(k in name for k in ("名称", "日期", "共 ", "合计", "【", "整理")):
            continue
        if name not in names:
            names.append(name)
    return names


def build():
    art = parse_lines(ART_TXT.read_text(encoding="utf-8"))
    mat = parse_lines(MAT_TXT.read_text(encoding="utf-8"))

    # 材料名单略去非法字符
    mat_clean = [n for n in mat if not n.endswith("?")]  # "不祥的面具像?" 有问号
    print(f"圣遗物: {len(art)} 个, 材料: {len(mat_clean)} 个")

    # 生成 Python 文件
    lines = []
    lines.append("# -*- coding: utf-8 -*-")
    lines.append("# 自动生成：圣遗物(狗粮)与材料名单（来自用户提供的 txt）")
    lines.append("# 不要手动改；需要更新时重新运行 _tools_build_names.py")
    lines.append("")
    lines.append("ARTIFACT_NAMES = [")
    for n in art:
        lines.append(f"    {n!r},")
    lines.append("]")
    lines.append("")
    lines.append("MATERIAL_NAMES = [")
    for n in mat_clean:
        lines.append(f"    {n!r},")
    lines.append("]")
    lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入: {OUT}")


if __name__ == "__main__":
    build()
