# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 公告

给用户传递消息用（新版发布、已知问题说明、规则变更…），**不用发新版**。

内容从哪来（按顺序试，谁通用谁）：
    1. Gitee          —— 国内快、稳定，主源
    2. GitHub raw     —— 备用
    3. 程序内置的那份 —— 最后兜底（打包时带进程序里）

设计要点：
  · **全程静默**：拉不到就当没有公告，绝不弹错误、不影响任何功能
  · **缓存上次拉到的**：断网时还能看到上次那份（存 data/notice_cache.json）
  · **已读记录**：读过哪个 id 记在设置里，不重复提醒（小红点靠它判断）
  · **手动刷新**：加 ?t=时间戳 绕开 CDN 缓存（自动拉时不加，免得每次都穿透缓存）

怎么发一条新公告：
    把新的 notice.json 传到 Gitee 仓库（覆盖旧的）就行，
    注意 id 要换一个新的（比如 2026-09-21-1），不然用户那边会被当成读过的。
"""
import json
import os
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Signal

import paths

# ---- 公告来源（按顺序试，谁通用谁）----
# 改这里就能加源 / 换源。以后哪家不稳了，加一行就行。
#
# 为什么 Gitee 写两条：
#   gitee.com/.../raw/... 会 302 跳到 raw.giteeusercontent.com。
#   正常情况下 urllib 会自动跟跳转，但万一哪天跳转出问题，
#   直连那条还能用 —— 两条一样的文件，多一条不亏。
GITEE = "https://gitee.com/Cash553/stat-genshin-impact/raw/main/notice.json"
GITEE_DIRECT = "https://raw.giteeusercontent.com/Cash553/stat-genshin-impact/raw/main/notice.json"
GITHUB = "https://raw.githubusercontent.com/Cash-553/stat-genshin-impact/main/notice.json"

NOTICE_SOURCES = [
    GITEE,           # 1) Gitee 主源（国内快）
    GITEE_DIRECT,    # 2) Gitee 直连（跳转失灵时兜底）
    GITHUB,          # 3) GitHub raw（最后）
]

TIMEOUT = 6                       # 单个源最多等几秒
UA = {"User-Agent": "StatGI"}

_lock = threading.Lock()
_fetching = False


# ------------------------------------------------------------
def cache_file():
    return paths.app_dir() / "data" / "notice_cache.json"


def builtin_file():
    """程序内置的那份（打包时带进去的）"""
    return paths.resource_file("notice.json")


def _valid(d):
    """公告格式检查 —— 不合规的直接丢掉，别让界面显示一半坏数据"""
    if not isinstance(d, dict):
        return False
    if not str(d.get("id", "")).strip():
        return False
    if not str(d.get("title", "")).strip():
        return False
    return True


def _load_file(p):
    try:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if _valid(d) else None
    except Exception:
        pass
    return None


def load_cached():
    """上次成功拉到的（离线时用它）"""
    return _load_file(cache_file())


def load_builtin():
    """程序内置的（最后兜底）"""
    return _load_file(builtin_file())


def save_cache(d):
    try:
        p = cache_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _fetch_one(url, bust_cache=False):
    u = url
    if bust_cache:
        u += ("&" if "?" in url else "?") + "t=%d" % int(time.time())
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    d = json.loads(raw)
    return d if _valid(d) else None


def fetch(bust_cache=False):
    """按顺序试每个源，返回 (公告dict 或 None, 命中的源地址)

    全失败返回 (None, None) —— 调用方不用管错误，静默处理就行。
    """
    for url in NOTICE_SOURCES:
        if not url or "changeme" in url:
            continue                       # 还没填用户名，跳过
        try:
            d = _fetch_one(url, bust_cache)
            if d:
                save_cache(d)              # 拉到就缓存一份，断网时还能看
                return d, url
        except Exception:
            continue                       # 这个源不行就试下一个
    return None, None


def fetch_async(callback):
    """后台线程里拉，结果用 Qt 信号发回主线程

    ⚠ 为什么不能直接 callback(notice)：
    这个函数是在后台线程里跑的，直接调回调就等于**在别的线程里碰控件** ——
    Qt 会崩或者行为不定（检测更新那儿我踩过一次）。
    Qt 信号跨线程是安全的：emit 之后会自动排队到主线程执行。
    """
    fetcher = NoticeFetcher()
    fetcher.done.connect(callback)
    fetcher.start()
    return fetcher


def refresh_async(callback):
    """手动刷新：带 ?t= 绕开 CDN 缓存"""
    fetcher = NoticeFetcher()
    fetcher.done.connect(callback)
    fetcher.start(bust_cache=True)
    return fetcher


# ------------------------------------------------------------
class NoticeFetcher(QObject):
    """在后台线程拉公告，结果用信号发回主线程

    用法：
        f = NoticeFetcher()
        f.done.connect(收到公告的函数)     # 参数是 公告dict 或 None
        f.start()
    """

    done = Signal(object)

    def start(self, bust_cache=False):
        threading.Thread(target=self._work, args=(bust_cache,), daemon=True).start()

    def _work(self, bust_cache):
        d = None
        try:
            with _lock:
                global _fetching
                if _fetching:
                    return                    # 已经有一个在拉了，别重复发请求
                _fetching = True
            try:
                d, _src = fetch(bust_cache=bust_cache)
            except Exception:
                d = None
            finally:
                with _lock:
                    _fetching = False
        finally:
            # 不管成没成都要发信号，界面好把按钮恢复
            try:
                self.done.emit(d)
            except Exception:
                pass


# ------------------------------------------------------------
def is_unread(notice, settings):
    """这条公告用户读过没有"""
    if not notice:
        return False
    return str(notice.get("id", "")) != str(settings.get("last_read_notice", ""))


def mark_read(notice, settings, save):
    """标记为已读（存 id）"""
    if not notice:
        return
    settings["last_read_notice"] = str(notice.get("id", ""))
    try:
        save(settings)
    except Exception:
        pass
