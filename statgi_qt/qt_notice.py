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
  · **已读记录**：读过哪些 id 记在设置里，不重复提醒（小红点靠它判断）
  · **多条历史**：一个文件里存着全部公告，程序里能翻往期

数据格式（发布版/公告/notice.json）：
    {
      "notices": [
        {"id": "2026-09-20-1", "title": "...", "body": "...",
         "url": "...", "time": "2026-09-20 23:10"},
        ...
      ]
    }
    最新的放**最前面**（程序直接按顺序显示）。
    也兼容旧的单条格式（{"id":..., "title":...}），会自动当成只有一条。

怎么发一条新公告：
    双击 发布版\\公告\\公告编辑器.bat —— 填完点发布就行。
"""
import json
import sys
import threading
import time
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

import paths

# ---- 公告文件在仓库里的位置（相对仓库根目录）----
# 发布版/ 在 .gitignore 里，但「公告」这个子文件夹专门放行了
# （程序是从 raw 地址拉公告的，不在仓库里就拉不到）
NOTICE_REL = "发布版/公告/notice.json"

_REPO_PATH = urllib.parse.quote(NOTICE_REL)          # 中文路径要转义才能进 URL

# ---- 公告来源（按顺序试，谁通用谁）----
# 改这里就能加源 / 换源。以后哪家不稳了，加一行就行。
#
# 为什么 Gitee 写两条：
#   gitee.com/.../raw/... 会 302 跳到 raw.giteeusercontent.com。
#   正常情况 urllib 会自动跟跳转，但万一跳转出问题，直连那条还能用。
NOTICE_SOURCES = [
    f"https://gitee.com/Cash553/stat-genshin-impact/raw/main/{_REPO_PATH}",
    f"https://raw.giteeusercontent.com/Cash553/stat-genshin-impact/raw/main/{_REPO_PATH}",
    f"https://raw.githubusercontent.com/Cash-553/stat-genshin-impact/main/{_REPO_PATH}",
]

TIMEOUT = 6                       # 单个源最多等几秒
UA = {"User-Agent": "StatGI"}

_lock = threading.Lock()
_fetching = False


# ------------------------------------------------------------
def cache_file():
    return paths.app_dir() / "data" / "notice_cache.json"


def builtin_file():
    """程序内置的那份公告

    · 打包版：在 _MEIPASS 里（spec 的 datas 把 发布版/公告/notice.json
      打成了 _internal/notice.json），所以用 resource_file()
    · 源码模式：直接读仓库里那份（发布版/公告/notice.json）
    """
    if getattr(sys, "frozen", False):
        return paths.resource_file("notice.json")
    return paths.app_dir() / NOTICE_REL


def parse(raw):
    """把文件内容变成「公告列表」，最新的在前

    兼容两种格式：
      {"notices": [ {...}, {...} ]}   多条（现在用的）
      {"id": ..., "title": ...}       单条（旧格式，当成只有一条）
    不合规的条目直接丢掉 —— 宁可不显示，也不能显示一半坏数据。
    """
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    if not isinstance(d, dict):
        return []

    items = d.get("notices")
    if not isinstance(items, list):
        items = [d]                       # 旧格式：整个对象就是一条

    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        nid = str(it.get("id", "")).strip()
        title = str(it.get("title", "")).strip()
        if not nid or not title:
            continue
        out.append({
            "id": nid,
            "title": title,
            "body": str(it.get("body", "") or ""),
            "url": str(it.get("url", "") or "").strip(),
            "time": str(it.get("time", "") or "").strip(),
        })
    return out


def _load_file(p):
    try:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return parse(f.read())
    except Exception:
        pass
    return []


def load_cached():
    """上次成功拉到的（离线时用它）"""
    return _load_file(cache_file())


def load_builtin():
    """程序内置的（最后兜底）"""
    return _load_file(builtin_file())


def load_all(settings=None):
    """给界面用：有缓存就用缓存，没缓存才用内置的

    ⚠ 不能写成 `load_cached() or load_builtin()`：
    空列表是假值，会把「远端已经清空公告」当成「没缓存」，
    然后退回内置的那份（里面可能还留着老公告）—— 公告就删不干净了。
    所以这里按**文件在不在**来判断，不看列表空不空。
    """
    try:
        if cache_file().exists():
            return load_cached()
    except Exception:
        pass
    return load_builtin()


def save_cache(notices):
    try:
        p = cache_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"notices": notices}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _fetch_one(url, bust_cache=False):
    """拉一个源。返回 (拿到没有, 公告列表)

    ⚠ 为什么把「拿到没有」和「列表」分开返回：
    「公告被清空」也是一个**有效状态** —— 远端就是 {"notices": []}。
    如果只看列表真假（if lst:），空列表会被当成"没拉到"，
    结果就是：**用户永远删不掉公告**（本地一直用旧缓存）——
    这个 bug 真出现过。所以要明确区分「拉到了但是空的」和「根本没拉到」。
    """
    u = url
    if bust_cache:
        u += ("&" if "?" in url else "?") + "t=%d" % int(time.time())
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        d = json.loads(raw)
    except Exception:
        return False, []
    if not isinstance(d, dict):
        return False, []
    # 新格式：有 notices 键（哪怕数组是空的）就算合法
    if isinstance(d.get("notices"), list):
        return True, parse(d)
    # 旧格式：整个对象就是一条公告
    if str(d.get("id", "")).strip() and str(d.get("title", "")).strip():
        return True, parse(d)
    return False, []


def fetch(bust_cache=False):
    """按顺序试每个源。返回 (公告列表, 命中的源地址)

    公告列表可以是**空列表** —— 那表示「远端把公告清空了」，
    是个有效结果，调用方要按这个把本地缓存也清掉。

    全部源都拉不到才返回 (None, None)，调用方保持现状即可。
    """
    for url in NOTICE_SOURCES:
        try:
            ok, lst = _fetch_one(url, bust_cache)
            if ok:
                save_cache(lst)               # 空的也要存 —— 那代表"清空了"
                return lst, url
        except Exception:
            continue                          # 这个源不行就试下一个
    return None, None


# ------------------------------------------------------------
class NoticeFetcher(QObject):
    """在后台线程拉公告，结果用信号发回主线程

    用法：
        f = NoticeFetcher()
        f.done.connect(收到公告的函数)     # 参数是 公告列表，或 None
        f.start()

    done 发出来的东西有两种：
        []      拉到了，但远端一条公告都没有（公告被清空了 —— 有效结果）
        None    一个源都没拉到（没网 / 都被墙），调用方保持现状

    ⚠ 为什么用信号而不是直接回调：这个类的活儿在后台线程跑，
    直接调回调就等于在别的线程里碰 Qt 控件 —— 会崩。
    信号跨线程是安全的（emit 之后 Qt 自动排队到主线程）。
    """

    done = Signal(object)

    def start(self, bust_cache=False):
        threading.Thread(target=self._work, args=(bust_cache,), daemon=True).start()

    def _work(self, bust_cache):
        lst = None
        try:
            global _fetching
            with _lock:
                if _fetching:
                    return                    # 已经有一个在拉了，别重复发请求
                _fetching = True
            try:
                lst, _src = fetch(bust_cache=bust_cache)
            except Exception:
                lst = None
            finally:
                with _lock:
                    _fetching = False
        finally:
            try:
                self.done.emit(lst)
            except Exception:
                pass


# ------------------------------------------------------------
def read_ids(settings):
    """已经读过的公告 id 集合"""
    v = (settings or {}).get("read_notices", [])
    if isinstance(v, str):
        v = [v]
    return set(str(x) for x in v) if isinstance(v, list) else set()


def is_unread(notice, settings):
    if not notice:
        return False
    return str(notice.get("id", "")) not in read_ids(settings)


def unread_count(notices, settings):
    rd = read_ids(settings)
    return sum(1 for n in (notices or []) if str(n.get("id", "")) not in rd)


def mark_read(notice, settings, save):
    """标记某条为已读"""
    if not notice:
        return
    nid = str(notice.get("id", ""))
    if not nid:
        return
    ids = read_ids(settings)
    if nid in ids:
        return
    ids.add(nid)
    # 只留最近 200 条，免得设置文件无限长大
    settings["read_notices"] = sorted(ids)[-200:]
    try:
        save(settings)
    except Exception:
        pass


def mark_all_read(notices, settings, save):
    ids = read_ids(settings)
    ids |= set(str(n.get("id", "")) for n in (notices or []))
    settings["read_notices"] = sorted(ids)[-200:]
    try:
        save(settings)
    except Exception:
        pass
