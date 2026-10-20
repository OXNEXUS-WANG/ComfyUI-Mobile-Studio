# -*- coding: utf-8 -*-
"""测试公共路径：兼容“安装目录根”和 GitHub 仓库的 app/ 结构。"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APP = ROOT / "app" if (ROOT / "app" / "app_core.py").is_file() else ROOT
for p in (str(APP), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
