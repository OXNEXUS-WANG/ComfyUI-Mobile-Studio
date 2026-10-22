# -*- coding: utf-8 -*-
"""Nexus 入口。

只负责把项目目录加入 sys.path，然后启动 HTTP 服务。
后端逻辑在 app_core.py，HTTP 路由在 web_server.py，
ComfyUI 工作流在 comfy_workflows.py，提示词处理在 prompt_engine.py。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from web_server import main

if __name__ == "__main__":
    sys.exit(main())
