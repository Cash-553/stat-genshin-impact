# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 检测更新

为什么不用 GitHub 的 API 了：
    未认证的 GitHub API 每小时只给 60 次，点几次就会被限流，
    表现就是「检测失败（需联网）」—— 明明有网却检测不了。
    （Gitee 那边也没有 releases，只能用 tags，拿不到版本说明。）

现在的做法：
    版本信息放在仓库里的一个**文件**（发布版/公告/version.json），
    直接走 raw 地址读 —— 没有 API、没有限流，两个渠道都能读。

渠道（设置里可选）：
    GitHub / Gitee / 自动（两个都试，谁先通用谁）
    选定渠道后：**从哪个渠道读版本**、**「打开下载页」跳哪个渠道**，
    都由它决定 —— 国内用户选 Gitee 更快。
"""
import json
import time
import urllib.parse
import urllib.request

# 仓库信息（改这里就能换仓库）
GH_REPO = "Cash-553/stat-genshin-impact"
GITEE_REPO = "Cash553/stat-genshin-impact"

# 版本文件在仓库里的位置
VERSION_REL = "发布版/公告/version.json"
_VERSION_PATH = urllib.parse.quote(VERSION_REL)

TIMEOUT = 8
UA = {"User-Agent": "StatGI"}

# 渠道：显示名 -> 内部值
CHANNELS = [("自动", "auto"), ("Gitee（国内快）", "gitee"), ("GitHub", "github")]

CHANNEL_NAMES = {"auto": "自动", "gitee": "Gitee", "github": "GitHub"}


def _gitee_urls():
    """Gitee 写两条：gitee.com/... 会 302 跳到 raw.giteeusercontent.com，
    正常会自动跟跳转，但万一跳转出问题，直连那条还能用。"""
    return [
        f"https://gitee.com/{GITEE_REPO}/raw/main/{_VERSION_PATH}",
        f"https://raw.giteeusercontent.com/{GITEE_REPO}/raw/main/{_VERSION_PATH}",
    ]


def _github_urls():
    return [f"https://raw.githubusercontent.com/{GH_REPO}/main/{_VERSION_PATH}"]


def sources_for(channel):
    """按渠道返回要试的地址列表（顺序就是尝试顺序）"""
    ch = str(channel or "auto").lower()
    if ch == "github":
        return [("github", u) for u in _github_urls()]
    if ch == "gitee":
        return [("gitee", u) for u in _gitee_urls()]
    # 自动：Gitee 优先（国内快），再 GitHub
    return ([("gitee", u) for u in _gitee_urls()]
            + [("github", u) for u in _github_urls()])


def version_tuple(s):
    """'0.10-beta' -> (0, 10)   只取版本号前面的数字段"""
    import re
    head = str(s or "").split("-")[0].split("+")[0]
    nums = re.findall(r"\d+", head)
    return tuple(int(x) for x in nums) if nums else ()


def is_newer_version(latest, current):
    """latest 是不是真的比 current 新

    为什么不能直接用 != 比较：远端最新可能是 0.8，而本地已经跑到 0.9 了 ——
    用 != 的话会把**老版本**当新版本弹出来。
    另外字符串比较下 "0.10" < "0.9"，按数字比才对。
    """
    a, b = version_tuple(latest), version_tuple(current)
    if not a or not b:
        return str(latest) != str(current)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def _fetch_one(url, bust_cache=False):
    u = url
    if bust_cache:
        u += ("&" if "?" in url else "?") + "t=%d" % int(time.time())
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    d = json.loads(raw)
    if not isinstance(d, dict) or not str(d.get("version", "")).strip():
        return None
    return d


def check(channel="auto", bust_cache=True):
    """检测更新

    返回 (结果dict 或 None, 命中的渠道, 失败原因)

    结果dict:
        {"version": "0.9", "notes": "...", "url": "下载页地址",
         "is_newer": True/False, "channel": "gitee"}

    失败原因（人话，直接能显示给用户）：
        ""            成功
        "rate"        被限流（现在用 raw 地址，基本不会出现，留着兜底）
        "network"     网络不通 / 超时
        "notfound"    渠道里没有版本文件（可能还没推上去）
    """
    reason = "network"
    for ch, url in sources_for(channel):
        try:
            d = _fetch_one(url, bust_cache)
            if not d:
                reason = "notfound"
                continue
            ver = str(d.get("version", "")).strip()
            url_key = "url_gitee" if ch == "gitee" else "url_github"
            page = str(d.get(url_key) or d.get("url_github") or "").strip()
            return {
                "version": ver,
                "notes": str(d.get("notes", "") or ""),
                "url": page,
                "is_newer": is_newer_version(ver, current_version()),
                "channel": ch,
            }, ch, ""
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                reason = "rate"
            elif e.code == 404:
                reason = "notfound"
            else:
                reason = "network"
            continue
        except Exception:
            reason = "network"
            continue
    return None, "", reason


def current_version():
    """本地版本（从 qt_pages 读，避免两处写死）"""
    try:
        from qt_pages import VERSION
        return str(VERSION)
    except Exception:
        return "0"


def reason_text(reason):
    return {
        "rate": "被限流了（同一个网络短时间查太多次），过一会儿再试",
        "network": "连不上（检查一下网络 / 代理）",
        "notfound": "渠道里没找到版本文件（可能还没推上去）",
    }.get(reason, "未知原因")
