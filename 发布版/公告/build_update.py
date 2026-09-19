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


def find_zip(ver):
    """找要切分的发布包

    顺序：
      1. 命令行传的路径（最优先，双击 bat 的话没有）
      2. 发布版\\StatGI_v<版本>_*.zip   比如「StatGI_v0.8_修复版.zip」
      3. 发布版\\StatGI_v<版本>.zip
      4. 发布版\\StatGI*.zip 里最新的那个
    """
    pub = os.path.join(ROOT, "发布版")
    if not os.path.isdir(pub):
        return None
    names = sorted(os.listdir(pub))

    def pick(pred):
        got = [os.path.join(pub, x) for x in names
               if x.lower().endswith(".zip") and pred(x)]
        if not got:
            return None
        got.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return got[0]

    if ver:
        p = pick(lambda x: x.startswith(f"StatGI_v{ver}_"))
        if p:
            return p
        p = pick(lambda x: x == f"StatGI_v{ver}.zip")
        if p:
            return p
    return pick(lambda x: x.startswith("StatGI"))


def main():
    print("=" * 60)
    print("  StatGI 更新包生成器")
    print("=" * 60)
    print()

    # 先读版本号（决定分卷名字和 Gitee 发行版的 tag）
    ver = ""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            ver = str(json.load(f).get("version", "")).strip()
    except Exception:
        pass

    # 发布包：命令行给了就用它，没给就自动找
    zip_path = sys.argv[1] if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else None
    if not zip_path:
        zip_path = find_zip(ver)
    if not zip_path:
        print("✗ 没找到发布包（发布版\\StatGI_v?.zip）")
        print("  可以这样指定：")
        print("     python build_update.py \"E:\\收益识别\\发布版\\StatGI_v0.8_修复版.zip\"")
        return 1

    size = os.path.getsize(zip_path)
    print(f"版本号：{ver or '（version.json 里没写）'}")
    print(f"发布包：{zip_path}")
    print(f"大小  ：{size/1024/1024:.1f} MB")
    print()
    # 让用户确认一下，别切错文件
    try:
        ans = input("是这个文件吗？(直接回车=对，输 n=不对) ").strip().lower()
    except Exception:
        ans = ""
    if ans in ("n", "no", "不是"):
        print("那就把要切的 zip 拖到 bat 上、或者命令行传路径进来。")
        return 1
    print()

    tag = f"v{ver}" if ver else "v0.0"
    # 分卷名用 ASCII（URL 里更稳，不用转义）
    stem = f"StatGI_{tag}"

    if size <= CHUNK:
        print("包不超过 95MB，其实不用切分。")
        parts = [zip_path]
    else:
        n = (size + CHUNK - 1) // CHUNK
        print(f"要切成 {n} 块（每块约 {CHUNK/1024/1024:.0f}MB）")
        os.makedirs(PART_DIR, exist_ok=True)
        for x in os.listdir(PART_DIR):
            try:
                os.remove(os.path.join(PART_DIR, x))
            except Exception:
                pass

        parts = []
        with open(zip_path, "rb") as f:
            for i in range(1, n + 1):
                data = f.read(CHUNK)
                p = os.path.join(PART_DIR, f"{stem}.part{i}")
                with open(p, "wb") as g:
                    g.write(data)
                parts.append(p)
                print(f"   ✓ 第 {i} 块  {len(data)/1024/1024:5.1f} MB  {os.path.basename(p)}")
    print()

    print("算整包的 SHA256（软件更新前会用它校验）…")
    digest = sha256_of(zip_path)
    print(f"   {digest}")
    print()

    # 分卷的下载地址：Gitee 发行版附件
    import urllib.parse
    gitee_parts = [f"{GITEE_RAW}/{tag}/{os.path.basename(p)}" for p in parts]

    # 写回 version.json
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            vj = json.load(f)
    except Exception:
        vj = {}
    # GitHub 那边的附件名按惯例是 StatGI_v<版本>.zip
    # （发布时要把 zip 改名成这个再传，否则这条备用地址会 404）
    gh_asset = f"StatGI_{tag}.zip"
    vj["update"] = {
        "size": size,
        "sha256": digest,
        "sources": [
            {"label": "Gitee（国内快）", "parts": gitee_parts},
            {"label": "GitHub", "parts": [
                vj.get("url_github", "").rstrip("/") + f"/download/{tag}/{gh_asset}"]},
        ],
    }
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(vj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("✓ 已把分卷地址 + 校验值写进 version.json")
    print()

    # 顺手生成「一键安装.bat」—— 给还没有软件的人用：
    # 分卷是硬切的 zip，单独一个打不开，得先合并。
    # 让普通用户敲 copy /b 太难，所以给个小 bat 双击就装好。
    try:
        import subprocess
        r = subprocess.run([sys.executable,
                            os.path.join(HERE, "make_installer.py")],
                           cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print("✓ 已生成「一键安装.bat」（给还没有软件的人用）")
        else:
            print("（一键安装.bat 没生成成功，不影响分卷）")
    except Exception as e:
        print(f"（一键安装.bat 没生成：{e}）")
    print()

    print("=" * 60)
    print("  接下来你要做的")
    print("=" * 60)
    print()
    print("① 到 Gitee 建发行版（版本号填 " + tag + "），把这几个附件传上去：")
    print()
    for p in parts:
        print(f"     {p}")
    print(f"     {os.path.join(HERE, '一键安装.bat')}   ← 给还没有软件的人")
    print()
    print("   ⚠ 两件重要的事：")
    print("     · 必须传在「发行版附件」里 —— Gitee 仓库里的单文件")
    print("       最大只有 50M，放不进仓库。")
    print("     · 传完记得把**上一个版本**的分卷附件删掉！")
    print("       附件总配额只有 1G，一个版本占 143M，不删的话")
    print("       大概 7 个版本就满了，满了就传不上新东西。")
    print()
    print("   用户怎么装：")
    print("     · 已经有软件的 → 软件里点「检测更新 → 立即更新」")
    print("     · 还没有软件的 → 下载「一键安装.bat」双击，")
    print("       它会自己下载分卷、合并、解压好")
    print()
    print("② 到 GitHub 建发行版（" + tag + "），传原来的整包：")
    print(f"     {zip_path}")
    print()
    print("   ⚠ 附件名必须是 " + gh_asset + "！")
    print("     自动更新会按这个名字去 GitHub 找备用包，")
    print("     名字对不上的话，Gitee 那边出问题时就退不到 GitHub。")
    print("     （发布页上先把旧附件删掉，再传这个改好名的）")
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
