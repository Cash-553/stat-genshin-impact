# -*- mode: python ; coding: utf-8 -*-
# StatGI 打包配置 —— 文件夹版（onedir）
#
# v0.9 起只有这一个版本了：界面是 Qt（PySide6）。
# （v0.7 及以前那套 Tk 界面和它的 StatGI.spec 已经删掉了。）
from PyInstaller.utils.hooks import collect_all
from PyInstaller.building.datastruct import TOC

datas = [('icons', 'icons'), ('models', 'models'), ('app_icon.ico', '.'),
         # 内置公告：远程（Gitee / GitHub）都拉不到时，用它兜底。
         # 源文件在 发布版\公告\ 里，打包后落在 _internal\notice.json
         # （这个路径同时也是仓库里给 raw 地址读的那份 —— 见 qt_notice.NOTICE_REL）
         ('发布版/公告/notice.json', '.')]
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
    # v0.9 起 Tk 版已经删掉，这些依赖彻底用不到了 —— 排掉能明显减小体积。
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
    ['app.py'],
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

# ============================================================
#  瘦身：把确认用不到的大文件剔出去（省约 58MB）
#
#  为什么要在 Analysis 之后手动过滤，而不是写进 excludes：
#    excludes 只管「Python 模块导不导入」，管不了「PyInstaller 顺手拷进来的
#    DLL / 数据文件」。这些 Qt 的 dll 和插件是被依赖链带进来的，不会因为
#    excludes 就不拷 —— 只能在生成 binaries / datas 列表之后自己删。
#
#  每一条都确认过项目里没用到（全局搜过 VideoCapture / QtNetwork /
#  QtQml / QPdf / avif 等，都没有）：
#    · opencv 的视频解码  29.4MB  我们只处理图片，不碰视频
#    · Qt6Quick/Qml       12.3MB  界面用的是 Widgets，没用 QML
#    · PIL 的 avif 插件    7.5MB  AVIF 图片格式极罕见
#    · Qt6Pdf              4.4MB  PDF 完全不碰
#    · Qt6Network          2.7MB  联网用的是 Python 的 urllib
#    · 用不到的图片插件    约 1MB  tiff/icns/gif/svg
#
#  ⚠ webp 插件**必须留** —— 自定义背景图的文件对话框里允许选 *.webp。
#  ⚠ opengl32sw.dll 也**必须留** —— 没装显卡驱动的机器靠它软件渲染，
#    删了一启动就崩。省那 19.7MB 不值得。
# ============================================================
_DROP_KEYWORDS = (
    'opencv_videoio_ffmpeg',        # OpenCV 视频解码
    'qt6quick', 'qt6qml',           # QML / Quick
    '_avif',                        # AVIF 图片插件
    'qt6pdf',                       # PDF
    'qt6network', 'qtnetwork',      # Qt 的网络模块
)
_DROP_IMAGE_PLUGINS = ('qtiff', 'qicns', 'qgif', 'qsvg', 'qpdf')


def _drop(name):
    low = str(name).lower().replace('\\', '/')
    if any(k in low for k in _DROP_KEYWORDS):
        return True
    base = low.rsplit('/', 1)[-1]
    if 'imageformats' in low and any(base.startswith(p) for p in _DROP_IMAGE_PLUGINS):
        return True
    return False


_before = sum(1 for _ in a.binaries) + sum(1 for _ in a.datas)
a.binaries = TOC([x for x in a.binaries if not _drop(x[0])])
a.datas = TOC([x for x in a.datas if not _drop(x[0])])
_after = len(a.binaries) + len(a.datas)
print(f'[瘦身] 过滤掉 {_before - _after} 个用不到的文件')

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
