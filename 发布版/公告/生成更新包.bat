@echo off
rem ============================================================
rem  StatGI update-package builder -- double click to run
rem
rem  Splits the release zip into <100MB parts for Gitee, computes
rem  the SHA256, and writes both into 发布版\公告\version.json
rem
rem  NOTE: keep this file pure ASCII. cmd.exe reads .bat in the
rem  OEM codepage (GBK here); UTF-8 Chinese in the body would break
rem  (that is also why the .py next to it has an ASCII name).
rem ============================================================
cd /d "%~dp0"
chcp 65001 >nul
python "%~dp0build_update.py"
pause
