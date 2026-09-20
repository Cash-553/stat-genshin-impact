# -*- coding: utf-8 -*-
"""
直播数据接口（给 OBS 浏览器源用）

StatGI 内置一个本地网页服务，供 OBS「浏览器源」采集：
- /api      → 今日收益数据（JSON）
- /overlay  → 直播竖屏覆盖层页面（弹幕区 + 收益 2×2 + 备注区）

在 OBS 里添加「浏览器源」，填 http://127.0.0.1:8765/overlay 即可。
"""
import threading

from flask import Flask, jsonify, Response, make_response

# 备注区默认文字（用户可在 StatsGI 设置里改）
DEFAULT_NOTE = "直播间：原神挂机直播    //    统计仅供参考"


def _cors(resp):
    """给响应加跨域头，允许独立网页(直播间美化.html)读取"""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


class ApiServer:
    def __init__(self, port=8765):
        self.port = port
        self._provider = None  # 由主程序设置：返回今日统计数据字典
        self._note = DEFAULT_NOTE  # 备注区文字
        self._app = Flask(__name__)

        @self._app.route("/")
        def index():
            return _cors(make_response(
                "StatGI API\n"
                "收益条（只显示摩拉/材料/狗粮/监测时间）: /bar\n"
                "整块竖屏覆盖层（含弹幕区+备注区）: /overlay\n"
                "数据: /api"))

        @self._app.after_request
        def add_cors(resp):
            return _cors(resp)

        @self._app.route("/api")
        def api():
            if self._provider:
                return jsonify(self._provider())
            return jsonify({"error": "数据未就绪"})

        @self._app.route("/overlay")
        def overlay():
            """整块竖屏覆盖层：弹幕区(上) + 收益2×2(中) + 备注区(下)"""
            return Response(self._overlay_html(), mimetype="text/html")

        @self._app.route("/bar")
        def bar():
            """**只有收益条** —— 摩拉/材料/狗粮/监测时间四个格子，没别的。

            跟 /overlay 的区别：那个是整块竖屏覆盖层（上面一半是弹幕区、
            下面还有备注区），只想显示收益的话用这个 /bar。
            """
            return Response(self._bar_html(), mimetype="text/html")

    def set_provider(self, fn):
        self._provider = fn

    def set_note(self, text):
        """设置备注区文字"""
        if text:
            self._note = text

    def _bar_html(self):
        """**只有收益条**的页面：四个格子，没有弹幕区、没有备注区。

        这就是「直播间美化.html」那个样子的纯净版 —— 只显示
        摩拉 / 材料 / 狗粮 / 监测时间，背景全透明，适合直接叠在画面上。
        """
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>StatGI 收益条</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body {
    font-family: "Microsoft YaHei UI", "微软雅黑", "PingFang SC", sans-serif;
    background: transparent;
    color: #f0f0f0;
    overflow: hidden;
  }
  .stats-2x2 { display:grid; grid-template-columns:1fr 1fr; gap:10px; width:340px; }
  .stat-cell {
    background: rgba(20,20,26,0.62);
    border:1px solid rgba(255,255,255,0.12);
    border-radius:14px;
    padding:14px 12px; text-align:center;
  }
  .stat-cell .label { font-size:13px; color:#c8ccd4; margin-bottom:6px; }
  .stat-cell .value { font-size:30px; font-weight:800; color:#f0f0f0; }
  .stat-cell.mora .value { color:#facc15; }
  .stat-cell.artifact .value { color:#c4b5fd; }
  .stat-cell.time .value { color:#67e8f9; font-size:22px; }
</style>
</head>
<body>
  <div class="stats-2x2">
    <div class="stat-cell mora"><div class="label">摩 拉</div><div class="value" id="vMora">0</div></div>
    <div class="stat-cell"><div class="label">材 料</div><div class="value" id="vMat">0</div></div>
    <div class="stat-cell artifact"><div class="label">狗 粮</div><div class="value" id="vArt">0</div></div>
    <div class="stat-cell time"><div class="label">监测时间</div><div class="value" id="vTime">00:00:00</div></div>
  </div>
<script>
  const $ = id => document.getElementById(id);
  const pad = n => String(n).padStart(2,'0');
  const fmtTime = sec => { sec=Math.max(0,sec|0); return pad(Math.floor(sec/3600))+':'+pad(Math.floor(sec%3600/60))+':'+pad(sec%60); };
  async function refresh() {
    try {
      const r = await fetch('/api', {cache:'no-store'});
      const d = await r.json();
      if (d && !d.error) {
        $('vMora').textContent = Number(d.mora||0).toLocaleString();
        $('vMat').textContent  = '×' + Number(d.material_total||0).toLocaleString();
        $('vArt').textContent  = '×' + Number(d.artifact||0).toLocaleString();
        $('vTime').textContent = fmtTime(d.running_seconds||0);
      }
    } catch(e) {}
  }
  refresh();
  setInterval(refresh, 1000);
</script>
</body>
</html>"""

    def _overlay_html(self):
        """直播竖屏覆盖层页面：弹幕区(上) + 收益2×2(中) + 备注区(下)"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    width: 400px; height: 900px;
    font-family: "Microsoft YaHei UI", "微软雅黑", sans-serif;
    background: transparent; color: #f0f0f0;
    overflow: hidden;
  }}
  .wrap {{
    display:flex; flex-direction:column; height:100%;
    padding: 8px;
  }}
  /* ---- 弹幕区（上半 50%）---- */
  .danmaku-box {{
    flex: 1 1 50%; min-height: 0;
    background: rgba(20,20,24,0.55);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:14px; padding:10px 12px;
    display:flex; flex-direction:column;
  }}
  .danmaku-title {{
    font-size:13px; color:#9aa0a8; font-weight:600;
    padding-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.06);
  }}
  .danmaku-title .dot {{ color:#3b82f6; }}
  .danmaku-list {{
    flex:1; overflow:hidden; margin-top:8px;
    display:flex; flex-direction:column; justify-content:flex-start;
  }}
  .danmaku-msg {{
    font-size:17px; padding:5px 0; color:#e8e8e8;
    white-space:nowrap; text-overflow:ellipsis; overflow:hidden;
    animation: fadeIn .3s ease;
  }}
  .danmaku-msg .name {{ color:#a5b4fc; margin-right:6px; }}
  .danmaku-msg .gift {{ color:#f59e0b; }}
  .danmaku-placeholder {{
    font-size:14px; color:#6b7280; text-align:center; margin:auto;
  }}
  @keyframes fadeIn {{ from{{opacity:0; transform:translateY(6px)}} to{{opacity:1; transform:none}} }}
  /* ---- 收益 2×2 ---- */
  .stats-box {{
    flex: 0 0 auto;
    margin-top:8px;
  }}
  .stats-2x2 {{
    display:grid; grid-template-columns:1fr 1fr; gap:8px;
  }}
  .stat-cell {{
    background: rgba(20,20,24,0.6);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:12px; padding:10px 12px; text-align:center;
  }}
  .stat-cell .label {{
    font-size:12px; color:#9aa0a8; margin-bottom:4px;
  }}
  .stat-cell .value {{
    font-size:26px; font-weight:700; color:#f0f0f0;
  }}
  .stat-cell.mora .value {{ color:#facc15; }}
  .stat-cell.artifact .value {{ color:#a78bfa; }}
  .stat-cell.time .value {{ color:#67e8f9; font-size:20px; }}
  /* ---- 备注区 ---- */
  .note-box {{
    flex: 0 0 auto; margin-top:8px;
    background: rgba(20,20,24,0.55);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:12px; padding:10px 12px;
    text-align:center; font-size:14px; color:#cfd3d8;
  }}
</style>
</head>
<body>
  <div class="wrap">
    <!-- 弹幕区 -->
    <div class="danmaku-box">
      <div class="danmaku-title"><span class="dot">●</span> 直播弹幕</div>
      <div class="danmaku-list" id="danmakuList">
        <div class="danmaku-placeholder">弹幕区 · 待连接 B 站房间号</div>
      </div>
    </div>

    <!-- 收益 2×2 -->
    <div class="stats-box">
      <div class="stats-2x2">
        <div class="stat-cell mora">
          <div class="label">摩 拉</div>
          <div class="value" id="vMora">0</div>
        </div>
        <div class="stat-cell">
          <div class="label">材 料</div>
          <div class="value" id="vMat">0</div>
        </div>
        <div class="stat-cell artifact">
          <div class="label">狗 粮</div>
          <div class="value" id="vArt">0</div>
        </div>
        <div class="stat-cell time">
          <div class="label">监测时间</div>
          <div class="value" id="vTime">00:00:00</div>
        </div>
      </div>
    </div>

    <!-- 备注区 -->
    <div class="note-box" id="noteBox">直播间：原神挂机直播    //    统计仅供参考</div>
  </div>

<script>
  const pad = n => String(n).padStart(2,'0');
  const fmtTime = sec => {{
    sec = Math.max(0, sec|0);
    const h = Math.floor(sec/3600), m = Math.floor(sec%3600/60), s = sec%60;
    return pad(h)+':'+pad(m)+':'+pad(s);
  }};
  async function refresh(){{
    try {{
      const r = await fetch('/api', {{cache:'no-store'}});
      const d = await r.json();
      if (d && !d.error) {{
        document.getElementById('vMora').textContent =
          Number(d.mora||0).toLocaleString();
        document.getElementById('vMat').textContent =
          '×' + (Number(d.material_total||0).toLocaleString());
        document.getElementById('vArt').textContent =
          '×' + (Number(d.artifact||0).toLocaleString());
        document.getElementById('vTime').textContent =
          fmtTime(d.running_seconds||0);
      }}
    }} catch(e) {{}}
  }}
  refresh();
  setInterval(refresh, 1500);
</script>
</body>
</html>
"""

    def start(self):
        """在后台线程里把接口跑起来

        为什么不用 app.run()：那个**没法停**（拿不到服务器对象），
        所以「连接 OBS」开关以前只能存个值、什么也不干。
        用 werkzeug 的 make_server 拿到对象，才能真的 start / stop。
        """
        self._server = None

        def _run():
            try:
                from werkzeug.serving import make_server
                self._server = make_server("127.0.0.1", self.port, self._app,
                                           threaded=True)
                self._server.serve_forever()
            except Exception:
                self._server = None
                # 端口被占用等：不崩溃，跳过接口功能

        threading.Thread(target=_run, daemon=True).start()

    def stop(self):
        """关掉接口（「连接 OBS」开关关掉、或者改端口时用）"""
        srv = getattr(self, "_server", None)
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
        self._server = None
