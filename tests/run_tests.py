#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""运行测试：默认只跑单元测试；设置 MGS_TEST_PASSWORD 后附带在线冒烟。"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
if (ROOT / "app").is_dir():
    sys.path.insert(0, str(ROOT / "app"))


def main():
    suite = unittest.TestLoader().discover(
        str(HERE), pattern="test_*.py", top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
