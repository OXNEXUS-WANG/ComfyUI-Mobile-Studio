# -*- coding: utf-8 -*-
"""LoRA 训练档案：Anima / SDXL 参数、命令行、数据集 TOML 和日志解析。

这个模块只做纯计算，不读写项目状态，也不启动进程；方便单元测试。
"""
import json
import math
import os
import re
import struct

ANIMA_MODEL = "anima-aesthetic-v1.1.safetensors"
ANIMA_CLIP = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"
SDXL_VAE = "sdxl-vae-fp16-fix.safetensors"

PROFILES = {
    "anima": {
        "key": "anima",
        "label": "Anima 2B（推荐）",
        "label_en": "Anima 2B (recommended)",
        "family": "anima",
        "script": "anima_train_network.py",
        "network_module": "networks.lora_anima",
        "kind": "anime",
        "default_resolution": 768,
        "max_resolution": 1024,
        "default_steps": 1000,
        "max_steps": 3000,
        "sec_per_step": {512: 2.0, 640: 2.6, 768: 3.3, 896: 4.4, 1024: 5.8},
        "min_free_vram_mb": 4200,
        "note": "8GB 显存建议 768、block swap 22；512 更快但细节少。",
        "note_en": "On 8GB VRAM use 768 with block swap 22; 512 is faster but simpler.",
    },
    "sdxl": {
        "key": "sdxl",
        "label": "SDXL（实验性）",
        "label_en": "SDXL (experimental)",
        "family": "sdxl",
        "script": "sdxl_train_network.py",
        "network_module": "networks.lora",
        "kind": "anime",
        "default_resolution": 768,
        "max_resolution": 1024,
        "default_steps": 800,
        "max_steps": 2000,
        "sec_per_step": {512: 2.8, 640: 3.6, 768: 4.8, 896: 6.2, 1024: 8.5},
        "min_free_vram_mb": 6000,
        "min_total_vram_mb": 11000,
        "min_total_ram_mb": 22000,
        "note": "8GB 显存/16GB 内存会在加载模型时 OOM；建议 12GB+ 显存、24GB+ 内存。",
        "note_en": "8GB VRAM / 16GB RAM runs out of memory while loading; 12GB+ VRAM and 24GB+ RAM are recommended.",
    },
}

PRESETS = {
    "character": {
        "label": "角色 LoRA",
        "dim": 16, "alpha": 8, "lr": 1e-4,
        "repeats": 10, "epochs": 10, "resolution": 768,
    },
    "style": {
        "label": "画风 LoRA",
        "dim": 32, "alpha": 16, "lr": 5e-5,
        "repeats": 10, "epochs": 12, "resolution": 768,
    },
    "quick": {
        "label": "快速测试",
        "dim": 8, "alpha": 4, "lr": 1e-4,
        "repeats": 5, "epochs": 4, "resolution": 512,
    },
}

STEPS_RE = re.compile(r"steps:.*?(\d+)/(\d+)\s*\[")
LOSS_RE = re.compile(r"(?:avr_loss|loss)=([0-9.]+)")
SEC_RE = re.compile(r"([0-9.]+)s/it")
EPOCH_RE = re.compile(r"epoch\s+(\d+)/(\d+)")
SAVE_RE = re.compile(r"saving checkpoint:\s*(.+?)\s*$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _as_int(value, lo, hi, default):
    try:
        n = int(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _as_float(value, lo, hi, default):
    try:
        n = float(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def profile_for(key):
    return dict(PROFILES.get(str(key or ""), PROFILES["anima"]))


def public_profiles():
    out = []
    for key, p in PROFILES.items():
        out.append({
            "key": key, "label": p["label"], "label_en": p["label_en"],
            "family": p["family"], "default_resolution": p["default_resolution"],
            "max_resolution": p["max_resolution"],
            "default_steps": p["default_steps"], "max_steps": p["max_steps"],
            "min_free_vram_mb": p["min_free_vram_mb"],
            "min_total_vram_mb": p.get("min_total_vram_mb") or 0,
            "min_total_ram_mb": p.get("min_total_ram_mb") or 0,
            "note": p["note"], "note_en": p.get("note_en") or p["note"],
        })
    return out


def normalize_params(profile_key, raw, settings=None):
    """把前端参数收成固定字段；所有值都有上下限。"""
    p = profile_for(profile_key)
    src = raw if isinstance(raw, dict) else {}
    settings = settings or {}
    preset_key = str(src.get("preset") or "character")
    preset = PRESETS.get(preset_key, PRESETS["character"])
    max_res = min(int(settings.get("max_resolution") or p["max_resolution"]),
                  p["max_resolution"])
    resolution = _as_int(src.get("resolution"), 256, max_res,
                         preset["resolution"])
    # 训练分辨率按 64 对齐
    resolution = max(256, min(max_res, int(round(resolution / 64.0)) * 64))
    dim = _as_int(src.get("network_dim"), 1, 128, preset["dim"])
    alpha = _as_float(src.get("network_alpha"), 0.1, 128.0,
                      float(preset["alpha"]))
    lr = _as_float(src.get("learning_rate"), 1e-6, 1e-2, preset["lr"])
    repeats = _as_int(src.get("num_repeats"), 1, 100, preset["repeats"])
    epochs = _as_int(src.get("epochs"), 1, 100, preset["epochs"])
    max_steps = _as_int(src.get("max_steps"), 1,
                        int(settings.get("max_steps") or p["max_steps"]),
                        preset["epochs"] * repeats * 10)
    if max_steps <= 0:
        max_steps = p["default_steps"]
    save_every = _as_int(src.get("save_every"), 0, 5000, 0)
    if save_every <= 0:
        save_every = max(50, min(500, max_steps // 5 or 100))
    total_blocks = _as_int(src.get("total_blocks"), 1, 64, 28)
    default_swap = 0
    if p["key"] == "anima":
        if total_blocks >= 28:
            default_swap = 22
        elif total_blocks >= 20:
            default_swap = 16
        else:
            default_swap = max(0, total_blocks - 6)
    blocks = _as_int(src.get("blocks_to_swap"), 0,
                     max(0, total_blocks - 2), default_swap)
    if p["key"] != "anima":
        blocks = 0
    ring = _as_int(src.get("block_swap_ring_size"), 1, 4, 1)
    keep = _as_int(src.get("keep_checkpoints"), 0, 10, 2)
    return {
        "preset": preset_key,
        "resolution": resolution,
        "network_dim": dim,
        "network_alpha": alpha,
        "learning_rate": lr,
        "num_repeats": repeats,
        "epochs": epochs,
        "max_steps": max_steps,
        "save_every": save_every,
        "keep_checkpoints": keep,
        "seed": _as_int(src.get("seed"), 0, 2 ** 31 - 1, 0),
        "blocks_to_swap": blocks,
        "block_swap_ring_size": ring,
        "vae_chunk_size": _as_int(src.get("vae_chunk_size"), 0, 256, 64),
        "shuffle_caption": bool(src.get("shuffle_caption", True)),
        "keep_tokens": _as_int(src.get("keep_tokens"), 0, 20, 1),
        "caption_dropout": _as_float(src.get("caption_dropout"), 0.0, 1.0, 0.05),
        "total_blocks": total_blocks,
    }


def compute_max_steps(image_count, repeats, epochs, hard_cap):
    try:
        n = int(image_count) * int(repeats) * int(epochs)
    except Exception:
        n = 0
    return max(1, min(int(hard_cap or 3000), n))


def dataset_toml(project, dataset_dir):
    """生成 sd-scripts 用的 TOML；路径统一用 /，不依赖 toml 写入器。"""
    params = project.get("params") or {}
    res = int(params.get("resolution") or 768)
    max_res = max(512, min(1536, res * 2))
    min_res = max(256, min(512, res // 2))
    path = str(dataset_dir).replace("\\", "/").replace('"', '\\"')
    lines = [
        "[general]",
        "enable_bucket = true",
        "min_bucket_reso = %d" % min_res,
        "max_bucket_reso = %d" % max_res,
        "bucket_no_upscale = false",
        # 启用 cache_text_encoder_outputs 时，sd-scripts 不允许
        # shuffle_caption / caption_dropout / token_warmup；这里保持默认关闭。
        "",
        "[[datasets]]",
        "resolution = %d" % res,
        "batch_size = 1",
        "",
        "[[datasets.subsets]]",
        'image_dir = "%s"' % path,
        'caption_extension = ".txt"',
        "num_repeats = %d" % int(params.get("num_repeats") or 1),
        "",
    ]
    return "\n".join(lines)


def model_paths(root, project):
    """返回训练需要的服务器侧模型路径；调用方已经校验过存在性。"""
    models = os.path.join(root, "ComfyUI", "models")
    profile = profile_for(project.get("profile"))
    if profile["key"] == "anima":
        return {
            "base": os.path.join(models, "diffusion_models", ANIMA_MODEL),
            "qwen3": os.path.join(models, "text_encoders", ANIMA_CLIP),
            "vae": os.path.join(models, "vae", ANIMA_VAE),
        }
    base = os.path.join(models, "checkpoints",
                        os.path.basename(str(project.get("base_model") or "")))
    return {
        "base": base,
        "vae": os.path.join(models, "vae", SDXL_VAE),
        "qwen3": "",
    }


def build_train_command(root, launcher, project, dataset_cfg, output_dir,
                        trainer_ready=True):
    """构建 argv 列表；绝不用 shell，所有值来自服务端档案。"""
    profile = profile_for(project.get("profile"))
    params = project.get("params") or {}
    paths = model_paths(root, project)
    cmd = [os.sys.executable, "-s", launcher, profile["script"]]
    cmd += [
        "--pretrained_model_name_or_path=" + paths["base"],
        "--dataset_config=" + dataset_cfg,
        "--output_dir=" + output_dir,
        "--output_name=" + str(project.get("output_name") or
                                ("lora_%s_%s" % (profile["key"],
                                                 project.get("id") or "x"))),
        "--save_model_as=safetensors",
        "--save_precision=fp16",
        "--network_module=" + profile["network_module"],
        "--network_dim=%d" % int(params.get("network_dim") or 16),
        "--network_alpha=%s" % _fmt_num(params.get("network_alpha") or 8),
        "--network_train_unet_only",
        "--learning_rate=%s" % _fmt_num(params.get("learning_rate") or 1e-4),
        "--optimizer_type=Adafactor",
        "--optimizer_args", "scale_parameter=False", "relative_step=False",
        "warmup_init=False",
        "--lr_scheduler=constant",
        "--lr_warmup_steps=0",
        "--max_grad_norm=0",
        "--gradient_accumulation_steps=1",
        "--max_train_steps=%d" % int(params.get("max_steps") or 1000),
        "--save_every_n_steps=%d" % int(params.get("save_every") or 200),
        "--save_last_n_steps=%d" % max(
            int(params.get("save_every") or 200),
            int(params.get("save_every") or 200)
            * max(1, int(params.get("keep_checkpoints") or 1))),
        "--seed=%d" % int(params.get("seed") or 0),
        "--max_data_loader_n_workers=0",
        "--console_log_simple",
    ]
    if profile["key"] == "anima":
        cmd += [
            "--qwen3=" + paths["qwen3"],
            "--vae=" + paths["vae"],
            "--mixed_precision=bf16",
            "--gradient_checkpointing",
            "--cache_latents",
            "--cache_latents_to_disk",
            "--cache_text_encoder_outputs",
            "--cache_text_encoder_outputs_to_disk",
            "--qwen_image_vae_2d",
            "--vae_chunk_size=%d" % int(params.get("vae_chunk_size") or 64),
            "--blocks_to_swap=%d" % int(params.get("blocks_to_swap") or 0),
            "--block_swap_h2d_only",
            "--block_swap_ring_size=%d" % int(
                params.get("block_swap_ring_size") or 1),
        ]
    else:
        cmd += [
            "--vae=" + paths["vae"],
            "--mixed_precision=fp16",
            "--gradient_checkpointing",
            "--cache_latents",
            "--cache_latents_to_disk",
            "--cache_text_encoder_outputs",
            "--sdpa",
        ]
        if project.get("vpred"):
            cmd.append("--v_parameterization")
    return cmd


def _fmt_num(value):
    try:
        f = float(value)
    except Exception:
        return str(value)
    if f == int(f):
        return str(int(f))
    return ("%.8f" % f).rstrip("0").rstrip(".")


def convert_command(root, launcher, src, dst):
    """sd-scripts Anima LoRA → ComfyUI `diffusion_model.*` 格式。"""
    return [os.sys.executable, "-s", launcher, "--convert-anima-lora",
            src, dst]


def estimate_seconds(profile_key, steps, resolution, image_count=0):
    p = profile_for(profile_key)
    table = p.get("sec_per_step") or {768: 4.0}
    keys = sorted(table)
    res = int(resolution or 768)
    sec = table[keys[-1]]
    for k in keys:
        if res <= k:
            sec = table[k]
            break
    overhead = 45 + max(0, int(image_count or 0)) * 1.5
    return int(overhead + max(0, int(steps or 0)) * float(sec))


def clean_text(value, limit=2000):
    text = str(value or "")
    text = "".join(ch for ch in text
                   if ch in ("\n", "\t") or ord(ch) >= 32)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_log_tail(text, state=None):
    """解析 sd-scripts 日志；返回更新后的状态字典。

    日志里有大量 `\r` 进度条，先拆成行再取最后一条完整进度。
    """
    state = dict(state or {})
    if not text:
        return state
    text = ANSI_RE.sub("", text)
    lines = [x.strip() for x in re.split(r"[\r\n]+", text) if x.strip()]
    for line in lines[-400:]:
        m = EPOCH_RE.search(line)
        if m and "steps:" not in line:
            state["epoch"] = int(m.group(1))
            state["total_epochs"] = int(m.group(2))
        m = STEPS_RE.search(line)
        if m:
            state["step"] = int(m.group(1))
            state["total_steps"] = int(m.group(2))
        m = LOSS_RE.search(line)
        if m:
            try:
                state["loss"] = round(float(m.group(1)), 5)
            except ValueError:
                pass
        m = SEC_RE.search(line)
        if m:
            try:
                state["sec_per_step"] = round(float(m.group(1)), 3)
            except ValueError:
                pass
        m = SAVE_RE.search(line)
        if m:
            name = os.path.basename(m.group(1).strip())
            if name and name not in state.setdefault("checkpoints", []):
                state["checkpoints"].append(name)
                state["checkpoints"] = state["checkpoints"][-10:]
    step = int(state.get("step") or 0)
    total = int(state.get("total_steps") or 0)
    if total:
        state["percent"] = round(min(100.0, step * 100.0 / total), 1)
        sec = float(state.get("sec_per_step") or 0)
        if sec:
            state["eta_seconds"] = int(max(0, total - step) * sec)
    return state


def classify_error(text):
    low = str(text or "").lower()
    if "cuda out of memory" in low or "out of memory" in low:
        return ("显存或内存不足，训练已停止。",
                "把分辨率降到 512/640，或把 block swap 调高到 24/26；"
                "关闭浏览器/其他占显存的程序后重试。")
    if "openblas" in low or "defaultcpuallocator" in low:
        return ("系统内存不足，训练已停止。",
                "关闭浏览器、ComfyUI 或其他大程序；block swap 会占用较多内存，"
                "可先降到 512 分辨率再试。")
    if "no such file or directory" in low or "not found" in low:
        return ("训练需要的模型/数据文件不存在。",
                "检查底模、Qwen3、VAE 和数据集是否仍在；在模型管理里确认文件完整。")
    if "network module" in low or "modulenotfounderror" in low:
        return ("训练组件不完整或版本不匹配。",
                "在训练管理里点“修复训练组件”，然后查看安装日志。")
    if "assertionerror" in low:
        return ("训练参数与当前 sd-scripts 不兼容，训练已停止。",
                "检查 caption 的 shuffle/dropout 设置；或在训练管理里点“修复训练组件”后重试。")
    if "permission denied" in low:
        return ("文件被占用或没有写入权限。",
                "关闭杀毒软件/资源管理器预览，确认训练目录可写后重试。")
    tail = ""
    for line in reversed(str(text or "").splitlines()):
        if line.strip():
            tail = line.strip()[:240]
            break
    return ("训练进程异常退出。", tail or "查看训练日志了解详情。")


def safe_open_check(path):
    """只读 header，确认是合法 safetensors；不加载 tensor。"""
    try:
        from safetensors import safe_open
        with safe_open(path, framework="numpy") as f:
            keys = list(f.keys())
        return bool(keys), len(keys), ""
    except Exception as exc:
        return False, 0, "%s: %s" % (type(exc).__name__, exc)


def strip_metadata(src, dst):
    """删除 safetensors 的 __metadata__，保留 data 区。

    这样不会把 caption / 数据集路径等训练元数据带进共享 LoRA。
    """
    with open(src, "rb") as fh:
        head = fh.read(8)
        if len(head) != 8:
            raise ValueError("不是有效的 safetensors 文件")
        n = struct.unpack("<Q", head)[0]
        if n <= 0 or n > 128 * 1024 * 1024:
            raise ValueError("safetensors header 异常")
        header = json.loads(fh.read(n).decode("utf-8"))
        data_start = 8 + n
        if not isinstance(header, dict):
            raise ValueError("safetensors header 不是对象")
        header.pop("__metadata__", None)
        raw = json.dumps(header, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        pad = (-len(raw)) % 8
        raw += b" " * pad
        with open(dst, "wb") as out:
            out.write(struct.pack("<Q", len(raw)))
            out.write(raw)
            fh.seek(data_start)
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    ok, count, err = safe_open_check(dst)
    if not ok:
        try:
            os.remove(dst)
        except OSError:
            pass
        raise ValueError("写入 LoRA 后校验失败：%s" % err)
    return count


def lora_filename(project):
    p = profile_for(project.get("profile"))
    return "lora_%s_%s.safetensors" % (p["key"], project.get("id") or "x")
