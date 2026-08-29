# -*- coding: utf-8 -*-
"""
printwindow_capture.py — 用 Win32 PrintWindow API 只截取"指定窗口本身"的内容
（而不是 mss 那样截屏幕区域，屏幕区域会带上盖在游戏上的其它窗口）。

纯 ctypes 实现，不依赖 pywin32（本机 Python 3.14 也未安装 pywin32），
依赖只有 numpy（可选：若没有 numpy 则回退到 PIL 输出）。

捕获策略（按可靠性从高到低自动降级，一旦拿到非全黑帧就返回）：
  1. PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)   —— Win8.1+，对 D3D/DWM 渲染的
     无边框游戏窗口（Unity/Unreal）最有效，官方用于解决"截出来是黑屏"的方案。
  2. PrintWindow(hwnd, hdc, 0)                      —— 普通窗口默认路径。
  3. PrintWindow(hwnd, hdc, PW_CLIENTONLY)          —— 只要客户区。
  4. BitBlt 从窗口 DC 抓取                          —— 老式 GDI 应用有效。
  5. DWM 缩略图（DwmRegisterThumbnail 到隐藏窗口再抓）—— OBS Window Capture 同款思路，
     对付 PrintWindow 也黑屏的特殊窗口（部分反作弊 / D3D12 / 受保护内容）。

已知限制：
  - 独占全屏（Exclusive Fullscreen）的游戏：DWM 不参与合成，PrintWindow/缩略图全黑，
    只能退回到屏幕捕获（mss / DXGI Desktop Duplication）。请让游戏用"无边框窗口"。
  - 最小化窗口通常抓不到内容（返回 None）。
  - 个别带反作弊保护的游戏（如部分 EAC/BattlEye 游戏）会强制 PrintWindow 返回黑图。
  - PW_RENDERFULLCONTENT 在 RTL（从右向左）布局窗口上有镜像 bug（已知 Windows 问题）。

对外接口（与项目现有 capture.py 的 ScreenCapture.grab 约定一致：返回 BGR 三通道数组）：
  capture_window_bgr(hwnd)  -> np.ndarray (H, W, 3) BGR | None
  capture_window_rgb(hwnd)  -> np.ndarray (H, W, 3) RGB | None
  capture_window_pil(hwnd)  -> PIL.Image (RGB) | None
  capture_window(hwnd, want="bgr"|"rgb"|"pil", force_method=None) -> 见上
  find_game_window_hwnd()   -> (hwnd, {"x","y","w","h"}) | None  （沿用项目原神匹配规则）
  find_hwnd(keywords, class_name=None) -> hwnd | None
  list_windows()            -> [(hwnd, title, class_name), ...]

命令行自测：
  python printwindow_capture.py --list
  python printwindow_capture.py --find-game
  python printwindow_capture.py --capture "记事本" --out shot.png [--method auto|printwindow|bitblt|dwm]
"""
import ctypes
import sys
import time
from ctypes import wintypes

import numpy as np

# ---------------------------------------------------------------- Win32 常量
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002

DWM_TNP_RECTDESTINATION = 0x00000001
DWM_TNP_RECTSOURCE = 0x00000002
DWM_TNP_OPACITY = 0x00000004
DWM_TNP_VISIBLE = 0x00000008
DWM_TNP_SOURCECLIENTAREAONLY = 0x00000010

DWMWA_EXTENDED_FRAME_BOUNDS = 9

WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0

S_OK = 0

# DPI_AWARENESS_CONTEXT 句柄（Win10 1703+ 可用 SetThreadDpiAwarenessContext）
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4).value
DPI_AWARENESS_CONTEXT_SYSTEM_AWARE = ctypes.c_void_p(-2).value

# ---------------------------------------------------------------- Win32 API
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)

user32.PrintWindow.restype = wintypes.BOOL
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]

user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]

user32.GetWindowDC.restype = wintypes.HDC
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
SRCCOPY = 0x00CC0020

dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmRegisterThumbnail.restype = ctypes.c_long
dwmapi.DwmRegisterThumbnail.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.HANDLE)]
dwmapi.DwmUpdateThumbnailProperties.restype = ctypes.c_long
dwmapi.DwmUpdateThumbnailProperties.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
dwmapi.DwmUnregisterThumbnail.restype = ctypes.c_long
dwmapi.DwmUnregisterThumbnail.argtypes = [wintypes.HANDLE]

user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.DestroyWindow.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.MoveWindow.restype = wintypes.BOOL
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
# GetModuleHandleW 在 kernel32 里（供 DWM 缩略图路径创建隐藏窗口用）
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

# SetThreadDpiAwarenessContext 在 Win10 1703+ 才有，动态探测
try:
    user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    _HAVE_THREAD_DPI = True
except AttributeError:  # pragma: no cover
    _HAVE_THREAD_DPI = False


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wintypes.DWORD),
        ("rcDestination", wintypes.RECT),
        ("rcSource", wintypes.RECT),
        ("opacity", ctypes.c_ubyte),
        ("fVisible", wintypes.BOOL),
        ("fSourceClientAreaOnly", wintypes.BOOL),
    ]


# ---------------------------------------------------------------- DPI 感知
_g_dpi_aware_done = False


def enable_dpi_awareness(global_=False):
    """
    让 GetWindowRect/GetClientRect 返回物理像素（而不是被 DPI 虚拟化缩放过的值），
    否则高分屏上截出来的图和窗口实际大小不一致。
    global_=False（默认）：只影响当前线程 —— 推荐，避免改动 Tkinter 主线程的布局。
    global_=True ：整进程 Per-Monitor DPI Aware（可能影响 GUI 布局，慎用）。
    """
    global _g_dpi_aware_done
    if _g_dpi_aware_done:
        return
    if global_:
        try:
            shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            _g_dpi_aware_done = True
            return
        except Exception:
            pass
        try:
            user32.SetProcessDPIAware()
            _g_dpi_aware_done = True
        except Exception:
            pass
    # 线程级：在每次取窗口尺寸 / PrintWindow 前临时设置
    _g_dpi_aware_done = True


def _thread_dpi_aware():
    """返回 (ctx, restore) —— 进入 Per-Monitor 感知；失败则退回系统感知。"""
    if _HAVE_THREAD_DPI:
        try:
            prev = user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            if prev:
                return True, lambda: user32.SetThreadDpiAwarenessContext(prev)
        except Exception:
            pass
        try:
            prev = user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_SYSTEM_AWARE)
            if prev:
                return True, lambda: user32.SetThreadDpiAwarenessContext(prev)
        except Exception:
            pass
    return False, lambda: None


# ---------------------------------------------------------------- 尺寸
def get_window_rect(hwnd):
    """窗口外框（屏幕坐标，物理像素）。失败返回 None。"""
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def get_client_rect(hwnd):
    """客户区尺寸（相对窗口左上角）。失败返回 None。"""
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def get_visible_rect(hwnd):
    """
    窗口"实际可见"外框：优先用 DWM 的 DWMWA_EXTENDED_FRAME_BOUNDS（无边框窗口下
    与客户区基本重合，不含阴影），失败退回 GetWindowRect。
    """
    r = wintypes.RECT()
    hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                      ctypes.byref(r), ctypes.sizeof(r))
    if hr == S_OK:
        return (r.left, r.top, r.right, r.bottom)
    return get_window_rect(hwnd)


# ---------------------------------------------------------------- 核心抓取
def _dib_to_bgr(buf, w, h):
    """32bpp DIB 缓冲区（BGRX，自顶向下）转 BGR (H,W,3) ndarray。"""
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
    return np.ascontiguousarray(arr[:, :, :3])  # BGR


def _capture_into_dc(hwnd, hdc, w, h, flag):
    """
    用 PrintWindow 把 hwnd 渲染进内存 DC（尺寸 w×h），返回 BGR ndarray 或 None。
    这是真正的核心：PrintWindow 请求 DWM 交出"这个窗口自己的内容"，
    所以盖上来的其它窗口不会出现在结果里。
    """
    if w <= 0 or h <= 0 or w > 16384 or h > 16384:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    if not mem_dc:
        return None
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    if not bmp:
        gdi32.DeleteDC(mem_dc)
        return None
    old = gdi32.SelectObject(mem_dc, bmp)
    ok = user32.PrintWindow(hwnd, mem_dc, flag)
    out = None
    if ok:
        # 用 GetDIBits 读出像素（32bpp 自顶向下，BGRX）
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # 负数 = 自顶向下
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        if got == h:
            out = _dib_to_bgr(buf, w, h)
    if old:
        gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    return out


def _printwindow(hwnd, flag):
    """带线程 DPI 感知的 PrintWindow 抓取。返回 (bgr|None, 实际尺寸)。"""
    aware, restore = _thread_dpi_aware()
    try:
        if flag == PW_CLIENTONLY:
            rc = get_client_rect(hwnd)
            if not rc:
                return None, None
            w, h = rc[2] - rc[0], rc[3] - rc[1]
        else:
            rc = get_visible_rect(hwnd)
            if not rc:
                return None, None
            w, h = rc[2] - rc[0], rc[3] - rc[1]
        hdc = user32.GetWindowDC(hwnd)
        if not hdc:
            return None, None
        try:
            img = _capture_into_dc(hwnd, hdc, w, h, flag)
        finally:
            user32.ReleaseDC(hwnd, hdc)
        return img, (w, h)
    finally:
        restore()


def _bitblt(hwnd):
    """老式 GDI 路径：直接从窗口 DC BitBlt。对纯 GDI 应用有效；对 DWM 合成窗口常黑屏。"""
    aware, restore = _thread_dpi_aware()
    try:
        rc = get_visible_rect(hwnd)
        if not rc:
            return None
        w, h = rc[2] - rc[0], rc[3] - rc[1]
        if w <= 0 or h <= 0 or w > 16384 or h > 16384:
            return None
        hdc = user32.GetWindowDC(hwnd)
        if not hdc:
            return None
        try:
            mem_dc = gdi32.CreateCompatibleDC(hdc)
            bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
            if not mem_dc or not bmp:
                return None
            old = gdi32.SelectObject(mem_dc, bmp)
            gdi32.BitBlt(mem_dc, 0, 0, w, h, hdc, 0, 0, SRCCOPY)
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
            out = _dib_to_bgr(buf, w, h) if got == h else None
            if old:
                gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)
            return out
        finally:
            user32.ReleaseDC(hwnd, hdc)
    finally:
        restore()


def _dwm_thumbnail(hwnd):
    """
    DWM 缩略图路径（OBS Window Capture 同思路）：
    把源窗口注册成一个隐藏目标窗口的 DWM 缩略图，再抓目标窗口。
    用于 PrintWindow 也黑屏的窗口。带反作弊 / 受保护内容的窗口此路也可能不通。
    注意：DWM 要求源与目标在同一 DPI 的同一显示器上，否则 DwmRegisterThumbnail 失败。
    """
    if user32.IsIconic(hwnd):
        return None
    src_rc = get_visible_rect(hwnd)
    if not src_rc:
        return None
    sw, sh = src_rc[2] - src_rc[0], src_rc[3] - src_rc[1]
    if sw <= 0 or sh <= 0 or sw > 16384 or sh > 16384:
        return None

    hinst = kernel32.GetModuleHandleW(None)
    # 隐藏的顶层窗口作为缩略图目标（用内置 STATIC 类，无需注册）
    dest = user32.CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "STATIC", "",
                                  WS_POPUP, 0, 0, sw, sh, None, None, hinst, None)
    if not dest:
        return None
    thumb = wintypes.HANDLE()
    try:
        hr = dwmapi.DwmRegisterThumbnail(dest, hwnd, ctypes.byref(thumb))
        if hr != S_OK or not thumb.value:
            return None

        props = DWM_THUMBNAIL_PROPERTIES()
        props.dwFlags = DWM_TNP_VISIBLE | DWM_TNP_RECTDESTINATION | DWM_TNP_SOURCECLIENTAREAONLY
        props.fVisible = True
        props.fSourceClientAreaOnly = True
        props.rcDestination = wintypes.RECT(0, 0, sw, sh)
        props.rcSource = wintypes.RECT(0, 0, sw, sh)
        if dwmapi.DwmUpdateThumbnailProperties(thumb, ctypes.byref(props)) != S_OK:
            return None
        # DWM 合成是异步的，等一两个合成周期（仅此兜底路径会等）
        out = None
        for _ in range(3):
            time.sleep(0.05)
            img, _ = _printwindow(dest, PW_RENDERFULLCONTENT)
            if img is not None and not _is_blank(img):
                out = img
                break
        if out is None:
            # 隐藏窗口抓不到就挪到屏幕外显示再试一次
            user32.MoveWindow(dest, -32000, -32000, sw, sh, True)
            user32.ShowWindow(dest, SW_SHOWNOACTIVATE)
            for _ in range(3):
                time.sleep(0.05)
                img, _ = _printwindow(dest, PW_RENDERFULLCONTENT)
                if img is not None and not _is_blank(img):
                    out = img
                    break
        return out
    finally:
        if thumb.value:
            dwmapi.DwmUnregisterThumbnail(thumb)
        user32.DestroyWindow(dest)


def _is_blank(bgr, sample=4096):
    """粗略判断画面是否全黑（PrintWindow 失败时通常返回纯黑）。"""
    if bgr is None:
        return True
    h, w = bgr.shape[:2]
    if h == 0 or w == 0:
        return True
    step = max(1, int((h * w / sample) ** 0.5))
    return not bool(np.count_nonzero(bgr[::step, ::step]))


# ---------------------------------------------------------------- 对外接口
_METHODS = {
    "printwindow": lambda hwnd: _printwindow(hwnd, PW_RENDERFULLCONTENT)[0],
    "printwindow_plain": lambda hwnd: _printwindow(hwnd, 0)[0],
    "clientonly": lambda hwnd: _printwindow(hwnd, PW_CLIENTONLY)[0],
    "bitblt": _bitblt,
    "dwm": _dwm_thumbnail,
}
_METHOD_ORDER = ["printwindow", "printwindow_plain", "clientonly", "bitblt", "dwm"]


def capture_window(hwnd, want="bgr", force_method=None, verbose=False):
    """
    截取 hwnd 窗口自身内容。
    want: "bgr" -> BGR ndarray (H,W,3)（项目内模板匹配/OCR 的约定）
          "rgb" -> RGB ndarray (H,W,3)
          "pil" -> PIL.Image (RGB)
    force_method: None=自动降级 | "printwindow" | "printwindow_plain" |
                  "clientonly" | "bitblt" | "dwm"
    返回对应类型或 None（失败/全黑/窗口无效）。
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    if user32.IsIconic(hwnd):
        # 最小化窗口抓不到有意义的内容（GetWindowRect 在 -32000 处）
        if verbose:
            print("[printwindow_capture] 窗口已最小化，无法截取")
        return None
    enable_dpi_awareness(global_=False)

    methods = [force_method] if force_method else _METHOD_ORDER
    last = None
    for m in methods:
        if m not in _METHODS:
            continue
        try:
            img = _METHODS[m](hwnd)
        except Exception as e:  # 兜底：单条路径失败不应中断
            last = f"{m}:{e}"
            continue
        if img is None:
            last = f"{m}:None"
            continue
        if _is_blank(img):
            last = f"{m}:blank"
            continue
        if verbose:
            print(f"[printwindow_capture] 用 {m} 成功, 尺寸 {img.shape[1]}x{img.shape[0]}")
        break
    else:
        if verbose:
            print(f"[printwindow_capture] 所有方法都失败: {last}")
        return None

    if want == "bgr":
        return img
    if want == "rgb":
        return np.ascontiguousarray(img[:, :, ::-1])
    if want == "pil":
        from PIL import Image
        return Image.fromarray(img[:, :, ::-1])  # BGR -> RGB
    raise ValueError("want 必须是 bgr / rgb / pil")


def capture_window_bgr(hwnd, **kw):
    """返回 BGR (H,W,3) ndarray，与项目 capture.ScreenCapture.grab 的返回约定一致。"""
    return capture_window(hwnd, want="bgr", **kw)


def capture_window_rgb(hwnd, **kw):
    return capture_window(hwnd, want="rgb", **kw)


def capture_window_pil(hwnd, **kw):
    return capture_window(hwnd, want="pil", **kw)


class WindowCapture:
    """
    与现有 capture.ScreenCapture 同形状的类，但 grab 的参数是窗口句柄而不是屏幕区域：
        wc = WindowCapture()
        frame_bgr = wc.grab(hwnd)     # BGR (H,W,3)，失败返回 None
    """

    def __init__(self, force_method=None, verbose=False):
        self.force_method = force_method
        self.verbose = verbose

    def grab(self, hwnd):
        return capture_window(hwnd, want="bgr", force_method=self.force_method, verbose=self.verbose)

    def grab_pil(self, hwnd):
        return capture_window(hwnd, want="pil", force_method=self.force_method, verbose=self.verbose)

    def close(self):
        pass


# ---------------------------------------------------------------- 窗口查找
def list_windows():
    """枚举所有可见顶层窗口：[(hwnd, title, class_name), ...]"""
    result = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value
            cls_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls_buf, 64)
            result.append((hwnd, title, cls_buf.value))
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return result


def find_hwnd(keywords, class_name=None):
    """按标题关键字（子串，忽略大小写）找窗口句柄；可再加类名过滤。"""
    kw = [k.lower() for k in keywords]
    for hwnd, title, cls in list_windows():
        tl = title.lower()
        if all(k in tl for k in kw) and (class_name is None or cls == class_name):
            return hwnd
    return None


def find_game_window_hwnd():
    """
    自动查找原神游戏窗口（规则与项目 capture.find_game_window 一致）。
    返回 (hwnd, {"x","y","w","h"})（DWM 可见外框），找不到返回 None。
    注意：这里返回的是 hwnd —— 截图直接用 hwnd，不再依赖屏幕坐标。
    """
    best = [None]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            if any(k in title for k in ("挂机收益", "BetterGI", "BetterGenshin", "BetterGenshinImpact")):
                return True
            cls_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls_buf, 64)
            cls = cls_buf.value
            is_game = ("原神" in title and "米哈游启动器" not in title) \
                or "genshin" in title.lower() or "yuanshen" in title.lower() \
                or "云原神" in title or "yunyuanshen" in title.lower() \
                or ("原" in title and cls == "UnityWndClass") \
                or ("Genshin" in title and cls == "UnityWndClass")
            if not is_game:
                return True
            rc = get_visible_rect(hwnd)
            if not rc:
                return True
            w, h = rc[2] - rc[0], rc[3] - rc[1]
            if w < 400 or h < 300:
                return True
            if best[0] is None or w * h > best[0][0]:
                best[0] = (w * h, (hwnd, {"x": rc[0], "y": rc[1], "w": w, "h": h}))
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return best[0][1] if best[0] else None


# ---------------------------------------------------------------- CLI 自测
def _cli(argv):
    if "--list" in argv:
        for hwnd, title, cls in list_windows():
            print(f"0x{hwnd:08X}  {cls:<24}  {title}")
        return 0
    if "--find-game" in argv:
        found = find_game_window_hwnd()
        if found:
            hwnd, rect = found
            print(f"找到游戏窗口 hwnd=0x{hwnd:08X} rect={rect}")
        else:
            print("没有找到游戏窗口（请先启动原神）")
        return 0
    if "--capture" in argv:
        i = argv.index("--capture")
        keyword = argv[i + 1]
        out = None
        if "--out" in argv:
            out = argv[argv.index("--out") + 1]
        method = "auto"
        if "--method" in argv:
            method = argv[argv.index("--method") + 1]
        hwnd = None
        if "--hwnd" in argv:
            hwnd = int(argv[argv.index("--hwnd") + 1], 16)
            print(f"按句柄截图 hwnd=0x{hwnd:08X}")
        else:
            hwnd = find_hwnd([keyword])
            if not hwnd:
                print(f"没有找到标题包含「{keyword}」的窗口")
                return 1
            print(f"目标窗口 hwnd=0x{hwnd:08X} title=「{keyword}」")
        force = None if method == "auto" else method
        img = capture_window_pil(hwnd, force_method=force, verbose=True)
        if img is None:
            print("截图失败（所有方法都黑屏/失败）")
            return 1
        if out:
            import os
            d = os.path.dirname(out)
            if d:
                os.makedirs(d, exist_ok=True)
            img.save(out)
            print(f"已保存: {out}  尺寸 {img.size}")
        else:
            img.show()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
