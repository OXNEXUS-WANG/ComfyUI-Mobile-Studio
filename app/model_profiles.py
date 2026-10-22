# -*- coding: utf-8 -*-
"""模型适配：根据文件名、safetensors 元数据和张量签名识别模型家族。

这里只做“识别 + 推荐参数 + 风险提示”，不加载模型权重。
"""
import copy
import json
import os
import re
import struct
import time

_CACHE = {}

# 模型数据外置：新增模型/改推荐参数只需要编辑 model_catalog.json。
# 这里保留极小兜底，JSON 损坏时服务仍能启动并提示“未识别”。
_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "model_catalog.json")


def _load_catalog():
    try:
        with open(_CATALOG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_CATALOG = _load_catalog()
PROFILES = _CATALOG.get("profiles") or {}
SIZE_PRESETS = _CATALOG.get("size_presets") or {}
EN = _CATALOG.get("en") or {}
NAME_HINTS = tuple(tuple(x) for x in (_CATALOG.get("name_hints") or ()))


def catalog():
    """给 app_core 读取人工模型预设等同一份目录数据。"""
    return _CATALOG


if "unknown" not in PROFILES:
    PROFILES["unknown"] = {
        "family": "unknown", "label": "未识别模型", "kind": "general",
        "steps": 25, "cfg": 6.0, "sampler": "dpmpp_2m",
        "recommended_size": "832x1216", "vpred": False, "pag": True,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": False,
        "badges": ["未识别"], "tip": "没有识别出架构，按通用 SDXL 参数试用。",
        "advice": ["确认模型是 SD1.5、SDXL 还是 Flux。"],
    }
if "unknown" not in SIZE_PRESETS:
    SIZE_PRESETS["unknown"] = {
        "sizes": ["832x1216", "1216x832", "1024x1024", "512x512"],
        "max_side": 1536, "max_pixels": 1500000,
    }
if "unknown" not in EN:
    EN["unknown"] = {
        "label": "Unrecognized model",
        "tip": "Architecture was not detected; generic SDXL settings are used.",
        "advice": ["Check whether this is SD1.5, SDXL or Flux."],
        "badges": ["Unrecognized"],
    }


KIND_ZH = {"anime": "动漫", "photo": "写实", "general": "通用"}
KIND_EN = {"anime": "Anime", "photo": "Photo", "general": "General"}

# 常见模型在英文界面里用可读短名，避免所有 SDXL 都显示成“Photo · SDXL”。


def _short_name(name):
    """从文件名取出适合放在模型 chip 上的短名。"""
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    low = stem.lower()
    for key, label in NAME_HINTS:
        if key in low:
            return label
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem[:48] or "Model"


def _header(path):
    """读取 safetensors 头部的元数据和键名，不加载权重。"""
    if not path or not str(path).lower().endswith(".safetensors"):
        return {}, set()
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), int(st.st_mtime), int(st.st_size))
        hit = _CACHE.get(key)
        if hit:
            return hit
        with open(path, "rb") as fh:
            raw = fh.read(8)
            if len(raw) != 8:
                return {}, set()
            n = struct.unpack("<Q", raw)[0]
            if n <= 0 or n > 64 * 1024 * 1024:
                return {}, set()
            hdr = json.loads(fh.read(n))
        meta = hdr.get("__metadata__") if isinstance(hdr, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        # 只留下有用的元数据，避免把巨大的 tag 频率表缓存起来
        meta = {k: v for k, v in meta.items()
                if (k.startswith("modelspec.") or k.startswith("ss_")
                    or k in ("format", "modelspec.architecture"))}
        keys = set(hdr.keys()) if isinstance(hdr, dict) else set()
        out = (meta, keys)
        _CACHE[key] = out
        return out
    except Exception:
        return {}, set()


def _flags(keys):
    return {
        "flux": (any(k.startswith("model.diffusion_model.double_blocks.") for k in keys)
                 and any(k.startswith("model.diffusion_model.single_blocks.") for k in keys)),
        "anima": (any("adaln_modulation_cross_attn" in k for k in keys)
                  and any(k.startswith("model.diffusion_model.x_embedder") for k in keys)),
        "sdxl": (any(k.startswith("conditioner.embedders.1.") for k in keys)
                 or "model.diffusion_model.label_emb.0.0.weight" in keys),
        "sd15": ("cond_stage_model.transformer.text_model.embeddings.token_embedding.weight" in keys
                 or ("model.diffusion_model.input_blocks.0.0.weight" in keys
                     and not any(k.startswith("conditioner.embedders.1.") for k in keys)
                     and "model.diffusion_model.label_emb.0.0.weight" not in keys)),
        "qwen": (any("transformer_blocks" in k for k in keys)
                 and any("txt_in" in k or "text_projection" in k for k in keys)),
        "embedded_text": any(k.startswith("conditioner.") for k in keys),
        "embedded_vae": any(k.startswith("first_stage_model.") for k in keys),
    }


def detect_family(name, path=None, known=None):
    low = str(name or "").lower()
    meta, keys = _header(path)
    fl = _flags(keys)
    arch = ""
    for k in ("modelspec.architecture", "ss_base_model_version",
              "modelspec.title", "ss_sd_model_name"):
        if meta.get(k):
            arch += " " + str(meta.get(k)).lower()
    arch = arch.strip()
    known = known or {}
    if known.get("family"):
        return known["family"]
    # 注意 animagine / animaPencilXL 也是 SDXL 模型，不能只按 "anima" 子串判断
    if ("animagine" in low or "anima pencil" in low
            or ("anima" in low and ("pencil" in low or "xl" in low))):
        return "sdxl_anime"
    if ("anima" in arch or fl["anima"]
            or re.match(r"^anima[-_]", low)):
        return "anima"
    if "flux" in arch or fl["flux"] or "flux" in low:
        return "flux"
    if "qwen" in arch or "qwen" in low:
        return "qwen_image"
    if "pony" in low or "pony" in arch:
        return "pony"
    if "noob" in low or "vpred" in low:
        return "noob"
    if "illustrious" in low or "animagine" in low or "himitsu" in low:
        return "sdxl_anime"
    if "juggernaut" in low or "realvis" in low or "epicrealism" in low:
        return "sdxl_photo"
    if "counterfeit" in low or "anything" in low or "toonify" in low:
        return "sd15_anime"
    if "stable-diffusion-xl" in arch or "sdxl" in arch or fl["sdxl"] or "xl" in low:
        return "sdxl_anime" if ("anime" in low or "illustrious" in low) else "sdxl_photo"
    if ("stable-diffusion-v1" in arch or "stable-diffusion-v2" in arch
            or "v1-5" in low or "sd15" in low or "1.5" in low or fl["sd15"]):
        return "sd15_anime" if "anime" in low else "sd15"
    if fl["qwen"]:
        return "qwen_image"
    return "unknown"


def detect_lora_family(name, path=None):
    """识别 LoRA 适用的底模家族；识别不出时返回 unknown（不阻止使用）。"""
    low = str(name or "").lower()
    meta, keys = _header(path)
    if keys:
        if any("double_blocks" in k or "single_blocks" in k for k in keys):
            return "flux"
        if any("adaln_modulation" in k for k in keys):
            return "anima"
        if any(("lora_te2_" in k or "lora_unet_down_blocks" in k
                or "lora_unet_middle_block" in k or "label_emb" in k)
               for k in keys):
            return "sdxl"
        if any(("lora_unet_input_blocks" in k or "lora_te1_" in k
                or "cond_stage_model" in k) for k in keys):
            return "sd15"
    if "animapencil" in low or "animagine" in low:
        return "sdxl"
    if "sdxl" in low or "xl" in low:
        return "sdxl"
    if "sd15" in low or "sd1.5" in low:
        return "sd15"
    if "flux" in low:
        return "flux"
    return "unknown"


def lora_compatible(model_family, lora_family):
    """底模家族和 LoRA 家族是否兼容；unknown 一律放行。"""
    lf = str(lora_family or "unknown")
    mf = str(model_family or "unknown")
    if lf == "unknown" or mf == "unknown":
        return True
    if mf in ("sdxl_anime", "sdxl_photo", "pony", "noob"):
        return lf == "sdxl"
    if mf in ("sd15", "sd15_anime"):
        return lf == "sd15"
    if mf == "anima":
        return lf == "anima"
    if mf == "flux":
        return lf == "flux"
    if mf == "qwen_image":
        return lf == "qwen"
    return True


def profile_for(name, path=None, known=None, refresh=False):
    """返回模型档案；known 是 app_core 里已有的人工推荐参数。"""
    known = known or {}
    family = detect_family(name, path, known)
    base = copy.deepcopy(PROFILES.get(family) or PROFILES["unknown"])
    base["name"] = str(name or "")
    base["family"] = family
    # 人工参数优先（例如 Anima / NoobAI 的精确步数和提示）
    for key in ("label", "steps", "cfg", "sampler", "kind", "orientation",
                "tip", "vpred", "pag", "supports_lora", "supports_negative",
                "supports_hires", "beginner", "recommended_size",
                "sizes", "max_side", "max_pixels"):
        if key in known and known[key] is not None:
            base[key] = known[key]
    # 画幅候选跟随模型家族；人工 preset 也可以覆盖。
    size_preset = SIZE_PRESETS.get(family) or SIZE_PRESETS["unknown"]
    if not base.get("sizes"):
        base["sizes"] = list(size_preset["sizes"])
    if not base.get("max_side"):
        base["max_side"] = size_preset["max_side"]
    if not base.get("max_pixels"):
        base["max_pixels"] = size_preset["max_pixels"]
    # 推荐画幅必须出现在候选里，前端默认就能选中它。
    rec = base.get("recommended_size") or "832x1216"
    if rec not in base["sizes"]:
        base["sizes"] = [rec] + list(base["sizes"])
    # 加速模型自动降步数。不同加速方案的推荐值不一样，不能一律 6 步。
    low = str(name or "").lower()
    fast = any(x in low for x in ("turbo", "lightning", "lcm", "hyper"))
    if fast and family not in ("anima", "flux", "qwen_image") and not known.get("steps"):
        if family.startswith("sdxl"):
            if "turbo" in low:
                base["steps"], base["cfg"] = 4, 1.0
                base["supports_negative"] = False
            elif "lightning" in low:
                base["steps"], base["cfg"] = 6, 2.0
            elif "lcm" in low:
                base["steps"], base["cfg"] = 6, 1.5
            else:
                base["steps"], base["cfg"] = 8, 1.5
        else:
            base["steps"], base["cfg"] = 5, 2.0
        base["sampler"] = "euler"
        base["pag"] = False
        base["badges"] = list(dict.fromkeys((base.get("badges") or []) + ["加速模型"]))
        base["advice"] = list(base.get("advice") or []) + [
            "这是 Turbo/Lightning/LCM 加速模型：按推荐的低步数、低 CFG 使用；用普通参数会糊。"]
        base["advice_en"] = list(base.get("advice_en") or []) + [
            "Turbo/Lightning/LCM model: use the recommended low step count and CFG."]

    warnings = []
    warnings_en = []
    if family in ("flux", "qwen_image"):
        # 一体化 checkpoint 才有可能直接走 CheckpointLoaderSimple
        meta, keys = _header(path)
        fl = _flags(keys)
        if not (fl.get("embedded_text") and fl.get("embedded_vae")):
            base["supported"] = False
        else:
            base["supported"] = True
            base["advice"] = list(base.get("advice") or []) + [
                "检测到一体式文本编码器/VAE，允许尝试加载。"]
            base["advice_en"] = list(base.get("advice_en") or []) + [
                "Embedded text encoder and VAE detected; loading may work."]
    if not base.get("supported", True):
        warnings.append("当前版本暂未自动适配这个架构；建议先用 Anima、SDXL 或 SD1.5 模型。")
        warnings_en.append("This architecture is not auto-adapted yet; use Anima, SDXL or SD1.5 for now.")
    if base.get("vpred"):
        warnings.append("v-pred 模型：必须用 Euler，CFG 建议 4~5；其他采样器可能出问题。")
        warnings_en.append("v-pred model: use Euler and CFG 4-5; other samplers may fail.")
    if family in ("sd15", "sd15_anime"):
        warnings.append("SD1.5 原生分辨率是 512；直接开 1024 容易出双头/重复人物。")
        warnings_en.append("SD1.5 is native at 512px; 1024px often causes duplicated subjects.")
    if family == "pony":
        warnings.append("Pony 系需要 score_9 / score_8_up 等质量标签，否则容易出低质量图。")
        warnings_en.append("Pony models need score_9 / score_8_up quality tags.")
    if family == "flux":
        warnings.append("Flux 通常 CFG=1、负面提示词基本无效；多数版本需要单独组件。")
        warnings_en.append("Flux usually uses CFG=1; negative prompts are mostly ignored.")
    if family == "qwen_image":
        warnings.append("Qwen-Image 通常需要单独的文本编码器和 VAE。")
        warnings_en.append("Qwen-Image usually requires a separate text encoder and VAE.")
    if family == "unknown":
        warnings.append("没有识别出架构，按通用 SDXL 参数只是保守估计。")
        warnings_en.append("Architecture not detected; generic SDXL settings are a guess.")
    if fast and family not in ("anima", "flux", "qwen_image"):
        if "turbo" in low and family.startswith("sdxl"):
            warnings.append("SDXL Turbo 类模型：建议 4 步 / CFG 1，负面提示词基本无效。")
            warnings_en.append("SDXL Turbo model: use 4 steps / CFG 1; negative prompts have little effect.")
        else:
            warnings.append("检测到 Turbo/Lightning/LCM：请使用低步数、低 CFG。")
            warnings_en.append("Turbo/Lightning/LCM detected: use low steps and low CFG.")
    if not base.get("supports_negative", True):
        warnings.append("这个模型不建议使用负面提示词。")
        warnings_en.append("This model does not benefit from a negative prompt.")
    base["warnings"] = warnings
    base["warnings_en"] = warnings_en
    en = EN.get(family) or EN["unknown"]
    kind_en = KIND_EN.get(base.get("kind"), "General")
    short = _short_name(name)
    base["label_en"] = kind_en + " · " + short
    # 没有人工标签的新模型也用真实短名，不要所有 SDXL 都显示「动漫 · SDXL」
    if not known.get("label"):
        kind_zh = KIND_ZH.get(base.get("kind"), "通用")
        suffix = "（未识别）" if family == "unknown" else ""
        base["label"] = kind_zh + " · " + short + suffix
    base["tip_en"] = en.get("tip") or ""
    base["advice_en"] = list(base.get("advice_en") or en.get("advice") or [])
    base["badges_en"] = list(en.get("badges") or [])
    base["beginner"] = bool(base.get("beginner")) and base.get("supported", True)
    base["recommended"] = base.get("recommended_size") or "832x1216"
    if family == "unknown" and not known.get("label"):
        base["display"] = os.path.splitext(str(name))[0]
        base["display_en"] = os.path.splitext(str(name))[0]
    else:
        base["display"] = base.get("label") or os.path.splitext(str(name))[0]
        base["display_en"] = base.get("label_en") or base["display"]
    return base
