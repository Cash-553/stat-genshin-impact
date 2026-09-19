@echo off
rem ============================================================
rem  StatGI notice editor -- double click this file to open
rem
rem  Why this bat exists:
rem    1) .pyw has no file association on this PC, double click won't run it
rem    2) the WindowsApps pythonw.exe stub does not forward properly
rem  So we call the real pythonw.exe directly (no console window).
rem
rem  NOTE: keep this file pure ASCII. cmd.exe reads .bat in the OEM
rem  codepage (GBK here), so UTF-8 Chinese in the body would be garbled.
rem ============================================================
cd /d "%~dp0"

set "PYW=C:\Users\ASUS\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"

if exist "%PYW%" (
    start "" "%PYW%" "%~dp0notice_editor.pyw"
) else (
    rem fallback: use python (a console window will show up)
    python "%~dp0notice_editor.pyw"
)
