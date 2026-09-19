# -*- coding: utf-8 -*-
"""生成「一键安装.bat」

为什么要有这个东西：
    分卷是**按字节硬切**的 zip（不是 7-Zip 分卷），单独一个打不开，
    必须先合并再解压。让普通用户敲 copy /b 太难了，
    所以给一个小 bat，双击就自动合并+解压。

⚠ 这个 bat 必须以 **GBK** 写盘！
   cmd.exe 读 .bat 是按系统 OEM 代码页（中文系统是 GBK）解析的，
   写成 UTF-8 的话中文提示全是乱码，还可能把某行解析坏。
   （write 工具只会写 UTF-8，所以专门用这个脚本生成。）

用法：python 生成一键安装.bat.py
"""
import io
import json
import os
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
VER_FILE = os.path.join(HERE, "version.json")

TEMPLATE = '''@echo off
chcp 936 >nul
title StatGI 一键安装
cd /d "%~dp0"

echo.
echo   ==========================================
echo      StatGI  v{ver}  一键安装
echo   ==========================================
echo.
echo   这个窗口会自动完成：下载 - 合并 - 解压
echo   中途请不要关掉它。
echo.

set "P1={p1}"
set "P2={p2}"

if exist "%P1%" if exist "%P2%" goto merge

echo   [1/3] 本目录没有安装包，正在从 Gitee 下载…
echo         （一共约 143MB，看你网速，可能要几分钟）
echo.
curl -L --fail -o "%P1%" "{u1}"
if errorlevel 1 goto fail
echo.
curl -L --fail -o "%P2%" "{u2}"
if errorlevel 1 goto fail
echo.

:merge
echo   [2/3] 正在合并两个文件…
copy /b "%P1%"+"%P2%" "StatGI_安装包.zip" >nul
if errorlevel 1 goto fail

echo   [3/3] 正在解压到 StatGI 文件夹…
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath 'StatGI_安装包.zip' -DestinationPath 'StatGI' -Force"
if errorlevel 1 goto fail

del "StatGI_安装包.zip" >nul 2>nul

echo.
echo   ==========================================
echo      装好了！
echo   ==========================================
echo.
echo   打开本目录下的 StatGI 文件夹，
echo   双击里面的 StatGI.exe 就能用了。
echo.
echo   （分卷文件不用删，以后更新会自动用上）
echo.
pause
exit /b

:fail
echo.
echo   ==========================================
echo      出错了
echo   ==========================================
echo.
echo   可能是网速太慢或网络断了，重新双击本文件再试一次就行。
echo   也可以只删掉没下完的那个分卷文件，再重试。
echo.
pause
exit /b 1
'''


def main():
    with open(VER_FILE, "r", encoding="utf-8") as f:
        d = json.load(f)
    ver = str(d.get("version", "")).strip()
    upd = d.get("update") or {}
    srcs = upd.get("sources") or []
    # 优先用 Gitee（国内快）
    gitee = None
    for s in srcs:
        if s.get("label", "").startswith("Gitee"):
            gitee = s
            break
    if not gitee or len(gitee.get("parts") or []) < 2:
        print("✗ version.json 里没找到 Gitee 的分卷地址")
        print("  先跑一次「生成更新包.bat」再来。")
        return 1

    parts = gitee["parts"]
    p1 = os.path.basename(parts[0])
    p2 = os.path.basename(parts[1])
    text = TEMPLATE.format(ver=ver, p1=p1, p2=p2,
                           u1=parts[0], u2=parts[1])

    out = os.path.join(HERE, "一键安装.bat")
    with open(out, "w", encoding="gbk", errors="replace", newline="\r\n") as f:
        f.write(text)

    print(f"✓ 生成好了：{out}")
    print(f"   版本   : {ver}")
    print(f"   分卷 1 : {p1}")
    print(f"   分卷 2 : {p2}")
    print(f"   大小   : {os.path.getsize(out)} 字节")
    print()
    print("把这个文件和两个分卷一起传到 Gitee 的 v" + ver + " 发行版。")
    print("用户只要下载这个 bat 双击，它自己会下载分卷并装好。")
    print()
    print("（也可以把三个文件一起给用户：都放同一个文件夹里双击，")
    print("  它就不下载了，直接用本地的分卷合并。）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"出错了：{type(e).__name__}: {e}")
        input("按回车关闭…")
        sys.exit(1)
