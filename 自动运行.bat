@echo off
chcp 65001 >nul
setlocal
rem 由 StatGI 自动生成 —— 改了会在下次保存时被覆盖

rem ==== 先启动 StatGI（没开就没人在记账）==== 
start "" /D "E:\收益识别" "C:\Users\ASUS\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" "E:\收益识别\statgi_qt\main.py"

rem ---- 启动 BetterGI ----
taskkill /IM "BetterGI.exe" /F >nul 2>&1
timeout /t 5 /nobreak >nul
start "" /D "D:\BetterGI" "D:\BetterGI\BetterGI.exe"

rem ---- OBS 开播（Steam） ----
timeout /t 60 /nobreak >nul
start "" "steam://rungameid/1905180"


endlocal
