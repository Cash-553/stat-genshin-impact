# -*- mode: python ; coding: utf-8 -*-
# StatGI V0.8（Qt 版）打包配置 —— 文件夹版（onedir）
#
# 跟 Tk 版的 StatGI.spec 是两份独立配置，互不影响：
#   StatGI.spec     打包 app.py（Tk 版，v0.7）
#   StatGI_qt.spec  打包 app_qt.py（Qt 版，v0.8）← 这个
from PyInstaller.utils.hooks import collect_all

datas = [('icons', 'icons'), ('models', 'models'), ('app_icon.ico', '.')]
binaries = []
hiddenimports = []

# rapidocr 自带模型和 onnxruntime 的 dll，必须整包收
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# 用不到的 Qt 模块排掉。PySide6 全量有两百多 MB，
# 排除掉网络引擎 / QML / 3D / 多媒体这些，能省一大截。
excludes = [
    # 这些是 Tk 版的依赖，Qt 版用不到。
    # errlog 里的 Tk 钩子有 try/except 兜着，排掉 tkinter 不会出问题。
    'tkinter', '_tkinter', 'customtkinter', 'pystray',
    # 训练相关的大件（TORCH 动辄几个 G）
    'torch', 'torchvision', 'functorch', 'torchgen', 'triton',
    # Qt 里没用到的模块
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtSpatialAudio',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtGraphsWidgets',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning',
    'PySide6.QtLocation', 'PySide6.QtSerialPort', 'PySide6.QtSensors',
    'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtHelp',
    'PySide6.QtTest', 'PySide6.QtSql', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech', 'PySide6.QtNetworkAuth', 'PySide6.QtHttpServer',
    # 注意：QtOpenGL / QtSvg / QtXml / QtPrintSupport 这几个**不能排**
    # —— QtWidgets 内部可能会用到，排掉的话打包版一启动就崩，
    #   而且报错是「plugin not found」之类，很难看出原因。省那几 MB 不值得。
    # 科学计算里用不到的部分
    'matplotlib', 'scipy', 'pandas', 'sklearn', 'skimage',
    'IPython', 'jupyter', 'notebook', 'pytest',
]

a = Analysis(
    ['app_qt.py'],
    # pathex 一定要带上 statgi_qt，否则 qt_window / qt_pages 这些
    # 在子目录里的模块分析不到，打出来的 exe 一启动就 ImportError
    pathex=['.', 'statgi_qt'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
