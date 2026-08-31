# -*- mode: python ; coding: utf-8 -*-
# 文件夹版（onedir）打包：比单文件版稳定（单文件版在部分机器上
# onnxruntime 后台线程会 fail-fast 闪退，文件夹版不会）。
from PyInstaller.utils.hooks import collect_all

datas = [('icons', 'icons'), ('models', 'models'), ('app_icon.ico', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'functorch', 'torchgen', 'triton'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StatGI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StatGI',
)
