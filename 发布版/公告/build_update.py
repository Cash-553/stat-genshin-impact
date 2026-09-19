# -*- coding: utf-8 -*-
"""StatGI 更新包生成器（打包分卷用）

每次发新版跑一下这个，它会：
  1. 把你的发布包（zip）切成几块 —— Gitee 单个附件不能超过 100MB
  2. 算出整包的 SHA256（软件更新前会校验，防止下载不全）
  3. 把分卷地址和校验值写进 发布版/公告/version.json
  4. 告诉你哪些文件要传到 Gitee

切法是**直接按字节切**（不是 7z 分卷）—— 因为软件是自己下载、
自己拼回去的，按字节切合并最简单（两段接起来就是原文件）。

怎么用：
  · 双击「生成更新包.bat」
  · 或者命令行： python 生成更新包.py
"""
import hashlib
import io
import json
import os
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))          # 发布版/公告
ROOT = os.path.dirname(os.path.dirname(HERE))              # 仓库根目录

VERSION_FILE = os.path.join(HERE, "version.json")
PART_DIR = os.path.join(HERE, "更新包分卷")
CHUNK = 95 * 1024 * 1024        # 每块 95MB（留点余量，Gitee 限制 100MB）

# 分卷上传到哪（Gitee 发行版附件）
GITEE_RAW = "https://gitee.com/Cash553/stat-genshin-impact/releases/download"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def find_zip():
    """自动找发布包：优先 发布版\\StatGI_v<版本>.zip"""
    ver = ""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            ver = str(json.load(f).get("version", "")).strip()
    except Exception:
        pass
    cands = []
    pub = os.path.join(ROOT, "发布版")
    if ver:
        cands.append(os.path.join(pub, f"StatGI_v{ver}.zip"))
    # 再扫一遍所有 zip，挑最新的
    if os.path.isdir(pub):
        zips = [os.path.join(pub, x) for x in os.listdir(pub)
                if x.lower().endswith(".zip") and x.startswith("StatGI")]
        zips.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        cands += zips
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def main():
    print("=" * 60)
    print("  StatGI 更新包生成器")
    print("=" * 60)
    print()

    zip_path = find_zip()
    if not zip_path:
        print("✗ 没找到发布包（发布版\\StatGI_v?.zip）")
        print("  请先打包出 zip，再跑这个。")
        return 1
    print(f"发布包：{zip_path}")
    size = os.path.getsize(zip_path)
    print(f"大小  ：{size/1024/1024:.1f} MB")
    print()

    if size <= CHUNK:
        print("包不超过 95MB，其实不用切分。")
        parts = [zip_path]
    else:
        n = (size + CHUNK - 1) // CHUNK
        print(f"要切成 {n} 块（每块约 {CHUNK/1024/1024:.0f}MB）")
        os.makedirs(PART_DIR, exist_ok=True)
        # 先清掉上次的
        for x in os.listdir(PART_DIR):
            os.remove(os.path.join(PART_DIR, x))

        base = os.path.basename(zip_path)
        parts = []
        with open(zip_path, "rb") as f:
            for i in range(1, n + 1):
                data = f.read(CHUNK)
                p = os.path.join(PART_DIR, f"{base}.part{i}")
                with open(p, "wb") as g:
                    g.write(data)
                parts.append(p)
                print(f"   ✓ 第 {i} 块  {len(data)/1024/1024:5.1f} MB  {os.path.basename(p)}")
    print()

    print("算整包的 SHA256（软件更新前会用它校验）…")
    digest = sha256_of(zip_path)
    print(f"   {digest}")
    print()

    # 分卷的下载地址：Gitee 发行版附件。文件名里的中文/特殊字符要转义
    import urllib.parse
    ver = ""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            ver = str(json.load(f).get("version", "")).strip()
    except Exception:
        pass
    tag = f"v{ver}" if ver else "v0.0"
    gitee_parts = [f"{GITEE_RAW}/{tag}/{urllib.parse.quote(os.path.basename(p))}"
                   for p in parts]

    # 写回 version.json
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            vj = json.load(f)
    except Exception:
        vj = {}
    vj["update"] = {
        "size": size,
        "sha256": digest,
        "sources": [
            {"label": "Gitee（国内快）", "parts": gitee_parts},
            {"label": "GitHub", "parts": [
                vj.get("url_github", "").rstrip("/") + f"/download/{tag}/"
                + urllib.parse.quote(os.path.basename(zip_path))]},
        ],
    }
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(vj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("✓ 已把分卷地址 + 校验值写进 version.json")
    print()

    print("=" * 60)
    print("  接下来你要做的")
    print("=" * 60)
    print()
    print("① 到 Gitee 建发行版（版本号填 " + tag + "），把这几个附件传上去：")
    print()
    for p in parts:
        print(f"     {p}")
    print()
    print("   ⚠ 两件重要的事：")
    print("     · 必须传在「发行版附件」里 —— Gitee 仓库里的单文件")
    print("       最大只有 50M，放不进仓库。")
    print("     · 传完记得把**上一个版本**的分卷附件删掉！")
    print("       附件总配额只有 1G，一个版本占 143M，不删的话")
    print("       大概 7 个版本就满了，满了就传不上新东西。")
    print()
    print("② 到 GitHub 建发行版（" + tag + "），传原来的整包：")
    print(f"     {zip_path}")
    print("   （GitHub 那边不用切，整包直接传）")
    print()
    print("③ 推一下代码，让 version.json 生效：")
    print("     cd " + ROOT)
    print("     git add -A && git commit -m \"发版 " + tag + "\" && git push")
    print()
    print("④ 装一个旧版试一下「检测更新 → 立即更新」，确认能跑通")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n出错了：{type(e).__name__}: {e}")
        input("\n按回车关闭…")
        sys.exit(1)
