# -*- coding: utf-8 -*-
"""启动隔离目录里的 sd-scripts，或执行训练器健康检查。

ComfyUI 便携版的 python313._pth 会忽略 PYTHONPATH，所以必须由本文件
手动把 trainer/pysite 和 trainer/sd-scripts 插进 sys.path；不要改
python_embeded/Lib/site-packages，也不要改 _pth。
"""
import json
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("MGS_TRAIN_SITE") or os.path.join(
    ROOT, "trainer", "pysite")
SCRIPTS = os.environ.get("MGS_TRAIN_SCRIPTS") or os.path.join(
    ROOT, "trainer", "sd-scripts")


def _prepare():
    for path in (SITE, SCRIPTS):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
    # sd-scripts 的相对导入（library/、networks/）以脚本目录为准
    if os.path.isdir(SCRIPTS):
        os.chdir(SCRIPTS)


def _health():
    _prepare()
    out = {"ok": False, "root": ROOT, "site": SITE, "scripts": SCRIPTS}
    try:
        import torch
        import diffusers
        import accelerate
        import transformers
        import safetensors
        import library.train_util  # noqa: F401
        import networks.lora_anima  # noqa: F401
        out.update({
            "ok": True,
            "python": sys.version.split()[0],
            "torch": getattr(torch, "__version__", ""),
            "cuda": bool(torch.cuda.is_available()),
            "gpu": (torch.cuda.get_device_name(0)
                    if torch.cuda.is_available() else ""),
            "diffusers": getattr(diffusers, "__version__", ""),
            "accelerate": getattr(accelerate, "__version__", ""),
            "transformers": getattr(transformers, "__version__", ""),
            "safetensors": getattr(safetensors, "__version__", ""),
            "network_module": True,
        })
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 2


def _run(argv):
    if not argv:
        print("missing script", file=sys.stderr)
        return 2
    _prepare()
    mode = argv[0]
    if mode == "--health":
        return _health()
    if mode == "--convert-anima-lora":
        if len(argv) < 3:
            print("missing conversion paths", file=sys.stderr)
            return 2
        script = os.path.join(SCRIPTS, "networks",
                              "convert_anima_lora_to_comfy.py")
    else:
        script = os.path.join(SCRIPTS, mode)
    if not os.path.isfile(script):
        print("training script not found: %s" % script, file=sys.stderr)
        return 2
    sys.argv = [script] + list(argv[1:])
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv[1:]))
