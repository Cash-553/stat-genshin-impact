# -*- coding: utf-8 -*-
"""精确模式（外部数据源模块）服务层 —— 接收侧 + 安装 + 进程控制。

设计见 `_morph\\外部数据源模块_设计.md`。三条铁律：

1. **主程序绝不碰游戏进程。** 这里只做两件事：读模块写出来的文件、拉起/停掉
   模块自己的进程。注入/hook 全在模块里，模块由用户自己下载、自己承担风险。
2. **模块在线时识别循环整条停掉**（在 `svc_capture.run_detector` 里做），
   掉线 30 秒自动回退 OCR。
3. **规则只有一份。** 模块事件**不自己写一套校验**，而是交给
   `detector.apply_external()` → 走和 OCR 完全相同的
   名单判定 / 错字纠正 / 黑白名单 / enable_* 开关 / 未登记日志。

模块 ↔ 主程序 的数据契约（契约版本 `CONTRACT_V`）：

    data/import/pickups.jsonl      每行一个事件（模块追加写，主程序尾随读）
    data/import/module_status.json 心跳（模块每 10 秒写一次）

事件格式见 `parse_event()` 的说明；心跳格式见 `status()`。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import paths

# ---------------------------------------------------------------- 契约常量
CONTRACT_V = 1                 # 数据契约版本；模块不认/主程序不认都按"忽略"处理
HEARTBEAT_TIMEOUT = 30.0       # 心跳超过这么久没更新 → 视为掉线
GRACE_SECONDS = 30.0           # 掉线后不立刻切回 OCR，给模块重启留的宽限（防抖）
POLL_SECONDS = 0.5             # 精确模式下识别循环的轮询间隔（秒）
MAX_COUNT = 9999               # 单笔数量上限（明显不合理的直接丢，防止脏数据灌进统计）
MAX_LINE = 4096                # 单行超长直接跳过（防手滑写坏文件把内存撑爆）
MODULE_NAME = "精确模式"
MANIFEST_REL = "发布版/公告/module.json"       # 模块清单（放仓库里，跟公告同一套 raw 机制）
UA = {"User-Agent": "StatGI"}

_GITEE_REPO = "Cash553/stat-genshin-impact"
_GH_REPO = "Cash-553/stat-genshin-impact"
_MANIFEST_Q = urllib.parse.quote(MANIFEST_REL)

# 清单的 raw 地址（跟 qt_update / qt_notice 一样的顺序：Gitee 优先、GitHub 兜底）
MANIFEST_URLS = [
    ("gitee", f"https://gitee.com/{_GITEE_REPO}/raw/main/{_MANIFEST_Q}"),
    ("gitee-raw", f"https://raw.giteeusercontent.com/{_GITEE_REPO}/raw/main/{_MANIFEST_Q}"),
    ("github", f"https://raw.githubusercontent.com/{_GH_REPO}/main/{_MANIFEST_Q}"),
]


# ---------------------------------------------------------------- 路径
def base_dir():
    """程序根目录（打包后 = exe 旁边）"""
    return paths.app_dir()


def import_dir(base=None):
    return Path(base or base_dir()) / "data" / "import"


def events_path(base=None):
    return import_dir(base) / "pickups.jsonl"


def status_path(base=None):
    return import_dir(base) / "module_status.json"


def modules_dir(base=None):
    return Path(base or base_dir()) / "modules"


def module_dir(base=None):
    return modules_dir(base) / MODULE_NAME


def install_record_path(base=None):
    """安装记录（主程序写的，不是模块写的）"""
    return module_dir(base) / ".statgi_module.json"


def ensure_import_dir(base=None):
    d = import_dir(base)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


# ---------------------------------------------------------------- 心跳 / 状态
def read_status_file(base=None):
    """读模块心跳文件；读不到/坏了返回 None（**不抛异常**）"""
    p = status_path(base)
    try:
        if not p.is_file():
            return None
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def status(base=None, now=None):
    """当前精确模式状态（给界面显示 + 给识别循环判断）。

    返回 dict：
        state   : "off"（没装/没开）| "installed"（装了但没运行）
                  | "online"（心跳新鲜）| "stale"（有心跳但过期）
        ack     : 用户有没有确认过风险（由调用方传 settings，这里只报文件层面）
        mod/version/contract : 模块自报的信息
        age     : 心跳距今多少秒（None = 没有心跳）
        unread  : 还没被读走的事件行数（估算，用于界面提示）
    """
    now = time.time() if now is None else now
    inst = installed(base)
    hb = read_status_file(base)
    out = {
        "state": "installed" if inst else "off",
        "mod": "", "version": (inst or {}).get("version", ""),
        "contract": (inst or {}).get("contract", CONTRACT_V),
        "note": "", "age": None,
        "dir": str(module_dir(base)) if inst else "",
    }
    if hb:
        alive = hb.get("alive_at")
        try:
            age = max(0.0, now - float(alive) / 1000.0)
        except Exception:
            age = None
        out["mod"] = str(hb.get("mod", "") or "")
        out["note"] = str(hb.get("note", "") or "")
        out["age"] = age
        if age is not None and age <= HEARTBEAT_TIMEOUT:
            out["state"] = "online"
        else:
            out["state"] = "stale"
    return out


def online(base=None, now=None):
    """模块是否在线（心跳新鲜）"""
    return status(base, now)["state"] == "online"


# ---------------------------------------------------------------- 事件解析
def parse_event(obj):
    """契约 JSON 对象 → 规范化事件 dict；不合法返回 (None, 原因)。

    契约（字段名固定，多余的忽略）：

        {"v":1, "t":毫秒时间戳, "name":"霓裳花", "count":1,
         "kind":"material|artifact|mora|other", "src":"pickup|chest|...",
         "conf":1.0, "mod":"harvest-0.1"}

    `v` 不认识 / `name` 空 / `count` 不是 1~MAX_COUNT 的整数 → 丢掉并计数。
    `t` 缺失时用"读到它的时间"兜底（不能让整条丢，宁可时间不准）。
    """
    if not isinstance(obj, dict):
        return None, "不是对象"
    try:
        v = int(obj.get("v", CONTRACT_V))
    except Exception:
        return None, "v 不是整数"
    if v != CONTRACT_V:
        return None, f"契约版本不认识（{v}，本程序认 {CONTRACT_V}）"
    name = str(obj.get("name", "") or "").strip()
    kind = str(obj.get("kind", "") or "").strip().lower()
    if not name and kind != "mora":
        return None, "name 为空"
    try:
        count = int(obj.get("count", 1))
    except Exception:
        return None, "count 不是整数"
    if count < 1 or count > MAX_COUNT:
        return None, f"count 不合理（{count}）"
    if len(name) > 32:
        return None, "name 太长"
    t = obj.get("t")
    try:
        t = float(t)
        t = t / 1000.0 if t > 1e11 else t      # 毫秒 → 秒（>1e11 才当毫秒）
    except Exception:
        t = None
    try:
        conf = float(obj.get("conf", 1.0))
    except Exception:
        conf = 1.0
    if kind == "mora":
        name = name or "摩拉"
    elif kind in ("", "material", "other"):
        kind = "material"
    elif kind != "artifact":
        kind = "material"
    return {
        "v": v, "t": t, "name": name, "count": count, "kind": kind,
        "src": str(obj.get("src", "") or ""), "conf": max(0.0, min(1.0, conf)),
        "mod": str(obj.get("mod", "") or ""),
    }, ""


class EventSource:
    """尾随读取 `data/import/pickups.jsonl`。

    为什么要"尾随 + 偏移"而不是每次重读整个文件：模块可能挂机几小时、
    文件会涨到几万行，每次重读既慢又会重复记账。

    三个必须处理的坏情况：
        · 文件被**截断/轮转**（模块重启时可能重建）→ 长度变小就从头读
        · 最后一行只写了一半（模块正在写）→ 留到下次，不能当半条事件用
        · 行内容坏了 / 超长 → 跳过并计数，不能把整条链路带崩
    """

    def __init__(self, base=None, start_at_end=True, enabled=True):
        self.base = base
        self.enabled = bool(enabled)
        self._pos = 0
        self._partial = ""
        self._inode = None
        self.last_event_at = 0.0      # 最近一次真收到事件的时刻
        self.stats = {"ok": 0, "bad": 0, "skip": 0, "conn": 0}
        self.last_reason = ""
        if start_at_end:
            # 启动时**从文件末尾开始**：之前那些是上次运行的旧事件，
            # 不能开机就补记一遍（用户没在监测）
            try:
                p = events_path(base)
                if p.is_file():
                    self._pos = p.stat().st_size
                    self._inode = p.stat().st_ino
            except Exception:
                self._pos = 0

    # ---------- 状态 ----------
    def state(self, now=None):
        st = status(self.base, now)
        if not self.enabled:
            st["state"] = "off"
        return st

    def online(self, now=None):
        """模块是不是"正在供数"。

        两个判据取或：
            ① 心跳新鲜（模块规规矩矩写了 module_status.json）
            ② **最近 30 秒真收到过事件** —— 万一模块忘了写心跳，
               也不能让 OCR 同时跑着，否则同一笔会被记两遍。
        """
        if not self.enabled:
            return False
        now = time.time() if now is None else now
        if self.state(now)["state"] == "online":
            return True
        return (now - self.last_event_at) <= HEARTBEAT_TIMEOUT

    # ---------- 读 ----------
    def read_new(self):
        """返回 (事件列表, 说明)。事件是 `parse_event` 规范化后的 dict。"""
        p = events_path(self.base)
        try:
            if not p.is_file():
                return [], ""
            st = p.stat()
            if self._inode is not None and st.st_ino != self._inode:
                self._pos, self._partial = 0, ""      # 换了文件（重建/轮转）
            if st.st_size < self._pos:
                self._pos, self._partial = 0, ""      # 被截断了
            self._inode = st.st_ino
            if st.st_size == self._pos:
                return [], ""
            with open(p, "rb") as f:
                f.seek(self._pos)
                raw = f.read()
                self._pos = f.tell()
        except FileNotFoundError:
            return [], ""
        except Exception as e:
            return [], f"读事件文件失败：{type(e).__name__}: {e}"

        text = self._partial + raw.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._partial = lines.pop() if lines else ""      # 最后一段可能没写完
        if len(self._partial) > MAX_LINE:
            self._partial = ""
            self.stats["skip"] += 1

        out, reasons = [], []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            if len(ln) > MAX_LINE:
                self.stats["skip"] += 1
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                self.stats["bad"] += 1
                continue
            ev, why = parse_event(obj)
            if ev is None:
                self.stats["bad"] += 1
                if why and why not in reasons:
                    reasons.append(why)
                continue
            ev["raw"] = ln[:200]          # 识别日志里存一行原文，方便事后查
            out.append(ev)
        self.stats["ok"] += len(out)
        if out:
            self.stats["conn"] += 1
            self.last_event_at = time.time()
        self.last_reason = "；".join(reasons[:2])
        return out, self.last_reason

    def note(self):
        """给界面用的一句话（把坏行原因也算进去）"""
        s = self.stats
        bits = [f"已收 {s['ok']} 笔"]
        if s["bad"]:
            bits.append(f"格式不对 {s['bad']} 行")
        if s["skip"]:
            bits.append(f"过长跳过 {s['skip']} 行")
        if self.last_reason:
            bits.append(self.last_reason)
        return "　".join(bits)


# ---------------------------------------------------------------- 清单
def parse_manifest(text):
    """解析模块清单 `module.json`；不合法返回 (None, 原因)"""
    try:
        d = json.loads(text) if isinstance(text, str) else text
    except Exception as e:
        return None, f"清单不是 JSON：{e}"
    if not isinstance(d, dict):
        return None, "清单不是对象"
    try:
        v = int(d.get("v", CONTRACT_V))
    except Exception:
        return None, "v 不是整数"
    if v != CONTRACT_V:
        return None, f"清单契约版本不认识（{v}）"
    ver = str(d.get("version", "") or "").strip()
    if not ver:
        return None, "清单缺 version"
    srcs = []
    for s in (d.get("sources") or []):
        if not isinstance(s, dict):
            continue
        parts = [str(u) for u in (s.get("parts") or []) if str(u).strip()]
        if parts:
            srcs.append({"label": str(s.get("label", "") or "下载"),
                         "parts": parts})
    if not srcs:
        return None, "清单里没有任何下载地址"
    try:
        size = int(d.get("size", 0) or 0)
    except Exception:
        size = 0
    return {
        "version": ver,
        "name": str(d.get("name", "") or "StatGI 精确模式模块"),
        "notes": str(d.get("notes", "") or ""),
        "size": size,
        "sha256": str(d.get("sha256", "") or "").lower(),
        "sources": srcs,
    }, ""


def fetch_manifest(timeout=20):
    """按渠道顺序拉清单；返回 (清单, 渠道名, 错误说明)"""
    last = ""
    for ch, url in MANIFEST_URLS:
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", errors="replace")
            man, why = parse_manifest(raw)
            if man:
                return man, ch, ""
            last = f"{ch}: {why}"
        except Exception as e:
            last = f"{ch}: {type(e).__name__}: {e}"
    return None, "", last or "拉不到模块清单"


# ---------------------------------------------------------------- 下载 / 安装
def human_size(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return "?"


def sha256_file(path, on_progress=None):
    h = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
            done += len(b)
            if on_progress:
                on_progress(done, total)
    return h.hexdigest()


def download(url, dest, on_progress=None, timeout=60):
    """下载一个文件（模块 zip 很小，不做分卷；要分卷再说）"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            b = r.read(256 * 1024)
            if not b:
                break
            f.write(b)
            done += len(b)
            if on_progress:
                on_progress(done, total)
    return dest


def _safe_extract(zf, dest):
    """解压到 dest，**挡住路径穿越**（`..\\` / 绝对路径 / 符号链接）

    模块 zip 是外部下载来的，不能无脑 extractall —— 一个 `..\\..\\x` 条目
    就能往系统目录写文件。这里逐个条目检查，越界的一个都不写。
    """
    dest = Path(dest).resolve()
    n = 0
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            continue
        target = (dest / name).resolve()
        try:
            target.relative_to(dest)
        except Exception:
            continue
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        n += 1
    return n


def installed(base=None):
    """已安装的模块信息；没装返回 None"""
    rec = install_record_path(base)
    try:
        if not rec.is_file():
            return None
        d = json.loads(rec.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(d, dict) or not d.get("version"):
            return None
        return d
    except Exception:
        return None


def install_zip(data, base=None, sha256="", version="", source=""):
    """把模块 zip 装到 `modules/精确模式/`；返回 (安装记录, 错误说明)

    刻意做成"先解到临时目录、校验通过再搬过去"：
    半途失败时不会留下一个装了一半的模块目录。
    """
    base = base or base_dir()
    final = module_dir(base)
    tmp = module_dir(base).with_name(MODULE_NAME + "_tmp")
    try:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if zf.testzip() is not None:
                return None, "压缩包损坏"
            n = _safe_extract(zf, tmp)
        if n == 0:
            return None, "压缩包里没有文件"
        # 模块自己也要带一份 module.json（里面写 contract / version / launch）
        mj = None
        for cand in tmp.rglob("module.json"):
            try:
                mj = json.loads(cand.read_text(encoding="utf-8", errors="replace"))
                break
            except Exception:
                continue
        if not isinstance(mj, dict):
            return None, "模块包里没有可用的 module.json"
        try:
            cv = int(mj.get("contract", CONTRACT_V))
        except Exception:
            cv = CONTRACT_V
        if cv != CONTRACT_V:
            return None, f"模块契约版本 {cv} 与本程序（{CONTRACT_V}）不一致"
        ver = str(mj.get("version", "") or version or "").strip() or "未知"
        rec = {
            "version": ver,
            "contract": cv,
            "name": str(mj.get("name", "") or MODULE_NAME),
            "launch": str(mj.get("launch", "") or ""),
            "sha256": sha256,
            "source": source,
            "installed_at": time.time(),
        }
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
        install_record_path(base).write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec, ""
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, f"{type(e).__name__}: {e}"


def uninstall(base=None, stop_first=True):
    """卸载模块（先停进程，再删目录）"""
    base = base or base_dir()
    if stop_first:
        stop_module(base)
    ok = True
    for d in (module_dir(base), module_dir(base).with_name(MODULE_NAME + "_tmp")):
        try:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            ok = False
    try:
        p = Path(base) / "modules"
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    except Exception:
        pass
    return ok


# ---------------------------------------------------------------- 进程控制
def launcher(base=None):
    """模块的启动目标（module.json 里的 `launch`；没有就找目录里唯一的 exe）"""
    base = base or base_dir()
    d = module_dir(base)
    rec = installed(base) or {}
    rel = str(rec.get("launch", "") or "").strip()
    if rel:
        p = (d / rel).resolve()
        try:
            p.relative_to(d.resolve())
        except Exception:
            return None
        if p.is_file():
            return p
    try:
        exes = [p for p in d.rglob("*.exe")]
    except Exception:
        exes = []
    if len(exes) == 1:
        return exes[0]
    for p in exes:
        if p.stem.lower() in ("start", "launch", "run", "statgi"):
            return p
    return exes[0] if exes else None


def _pid_file(base=None):
    return module_dir(base) / ".statgi_pid"


def module_pid(base=None):
    """我们启动的模块进程 pid（模块自己起的进程不算）"""
    try:
        d = json.loads(_pid_file(base).read_text(encoding="utf-8"))
        pid = int(d.get("pid", 0))
        return pid or None
    except Exception:
        return None


def _alive(pid):
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=8)
            return str(pid) in (out.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def module_running(base=None):
    pid = module_pid(base)
    return bool(pid and _alive(pid))


def start_module(base=None):
    """拉起模块进程（独立进程；主程序不注入、不读内存）。

    需要管理员权限的话由**模块自己的 manifest** 申请（Windows 会自动弹 UAC），
    主程序不主动提权、也不做任何注入动作。
    返回 (pid, 错误说明)。
    """
    base = base or base_dir()
    if module_running(base):
        return module_pid(base), ""
    exe = launcher(base)
    if exe is None:
        return None, "模块目录里找不到可执行文件（module.json 的 launch 或唯一的 exe）"
    try:
        d = module_dir(base)
        # 让模块知道往哪写事件（它也可以自己按 exe 旁边推算，给了更保险）
        env = dict(os.environ)
        env["STATGI_IMPORT_DIR"] = str(import_dir(base))
        env["STATGI_CONTRACT"] = str(CONTRACT_V)
        p = subprocess.Popen([str(exe)], cwd=str(d), env=env,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        _pid_file(base).write_text(json.dumps({"pid": p.pid}), encoding="utf-8")
        return p.pid, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def stop_module(base=None):
    """停掉我们启动的模块进程"""
    base = base or base_dir()
    pid = module_pid(base)
    if not pid:
        return True
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, 15)
    except Exception:
        pass
    try:
        _pid_file(base).unlink()
    except Exception:
        pass
    return True
