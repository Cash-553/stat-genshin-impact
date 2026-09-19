@echo off
rem ============================================================
rem  StatGI release tool -- double click to run
rem
rem  Splits the chosen release zip into <100MB parts for Gitee,
rem  generates the one-click installer, and updates version.json
rem
rem  NOTE: keep this file pure ASCII. cmd.exe reads .bat in the
rem  OEM codepage (GBK here); UTF-8 Chinese in the body would break
rem  (that is also why the .pyw next to it has an ASCII name).
rem ============================================================
cd /d "%~dp0"

set "PYW=C:\Users\ASUS\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"

if exist "%PYW%" (
    start "" "%PYW%" "%~dp0release_tool.pyw"
) else (
    rem fallback: use python (a console window will show up)
    python "%~dp0release_tool.pyw"
)
