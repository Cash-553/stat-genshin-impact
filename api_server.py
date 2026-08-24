# -*- coding: utf-8 -*-
"""
直播数据接口（给 OBS 浏览器源用，预留功能）

以后可以在 OBS 里添加"浏览器源"：
    http://127.0.0.1:8765/api
就能拿到今日收益数据（JSON 格式），显示到直播画面里。
"""
import threading

from flask import Flask, jsonify


class ApiServer:
    def __init__(self, port=8765):
        self.port = port
        self._provider = None  # 由主程序设置：返回今日统计数据字典
        self._app = Flask(__name__)

        @self._app.route("/")
        def index():
            return "StatGI API —— 浏览器源地址: /api"

        @self._app.route("/api")
        def api():
            if self._provider:
                return jsonify(self._provider())
            return jsonify({"error": "数据未就绪"})

    def set_provider(self, fn):
        self._provider = fn

    def start(self):
        def _run():
            try:
                self._app.run(
                    host="127.0.0.1",
                    port=self.port,
                    threaded=True,
                    use_reloader=False,
                )
            except Exception:
                pass  # 端口被占用等：不崩溃，跳过接口功能

        threading.Thread(target=_run, daemon=True).start()
