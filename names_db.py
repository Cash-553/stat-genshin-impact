# -*- coding: utf-8 -*-
"""识别名单 —— 决定"认得出什么"。

两份：
    generated_names.py     内置默认（574 个材料 + 299 个圣遗物），**永远不动**
    data/names.json        你自己的名单（第一次运行时从内置拷一份）

设计成"副本 + 默认"两份，是为了能「恢复默认名单」——
删掉 names.json 就会重新从内置生成。

列表结构：
    {"materials": ["破损的面具", ...], "artifacts": ["冒险家之花", ...]}

⚠ 名单全删光的话什么都识别不到（认不出来的名字现在不入账），
   所以界面上必须有红字警告 + 恢复默认的入口。
"""
import json

from pathlib import Path

import paths

DATA_DIR = paths.app_dir() / "data"
NAMES_FILE = DATA_DIR / "names.json"


def _builtin():
    """内置默认名单（来自 generated_names.py）"""
    import generated_names as g
    return {
        "materials": list(g.MATERIAL_NAMES),
        "artifacts": list(g.ARTIFACT_NAMES),
    }


def load():
    """读识别名单。文件不存在/损坏 → 用内置的（并写出一份）"""
    if NAMES_FILE.exists():
        try:
            d = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
            mats = [str(x).strip() for x in d.get("materials", []) if str(x).strip()]
            arts = [str(x).strip() for x in d.get("artifacts", []) if str(x).strip()]
            # 两个都空了就当坏了，回退内置（防止用户误删导致完全识别不到）
            if mats or arts:
                return {"materials": mats, "artifacts": arts}
        except Exception:
            pass
    return reset_to_default()


def save(names):
    """保存识别名单"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    d = {
        "materials": [str(x).strip() for x in names.get("materials", []) if str(x).strip()],
        "artifacts": [str(x).strip() for x in names.get("artifacts", []) if str(x).strip()],
    }
    NAMES_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def reset_to_default():
    """恢复默认名单：删掉自己的那份，重新从内置生成"""
    try:
        NAMES_FILE.unlink()
    except FileNotFoundError:
        pass
    return save(_builtin())


def materials():
    return load()["materials"]


def artifacts():
    return load()["artifacts"]


def material_set():
    return set(materials())


def artifact_set():
    return set(artifacts())
