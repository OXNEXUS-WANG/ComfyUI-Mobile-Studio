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

# 已知家族的推荐参数。UI 和后端都从这里取，避免两边各写一套。
PROFILES = {
    "anima": {
        "family": "anima", "label": "动漫 · Anima 2B", "kind": "anime",
        "steps": 30, "cfg": 4.0, "sampler": "euler",
        "recommended_size": "832x1216", "vpred": False, "pag": False,
        "supports_lora": False, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": True,
        "badges": ["新手推荐", "动漫"],
        "tip": "原生支持中文描述，动漫首选。不能使用 SDXL LoRA 和 PAG；可用极速 LoRA。",
        "advice": ["初次使用建议直接按推荐参数出图。", "想更快可打开「Anima 极速」（8 步）。"],
    },
    "noob": {
        "family": "noob", "label": "动漫 · NoobAI Vpred", "kind": "anime",
        "steps": 30, "cfg": 4.5, "sampler": "euler",
        "recommended_size": "832x1216", "vpred": True, "pag": True,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": False,
        "badges": ["v-pred", "动漫"],
        "tip": "角色和画师标签最全。v-pred 模型必须用 Euler，CFG 4~5。",
        "advice": ["不要换成 DPM++ 等其他采样器。", "冷门角色可以用英文 tag 补全。"],
    },
    "sdxl_anime": {
        "family": "sdxl_anime", "label": "动漫 · SDXL", "kind": "anime",
        "steps": 25, "cfg": 6.5, "sampler": "dpmpp_2m",
        "recommended_size": "832x1216", "vpred": False, "pag": True,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": True,
        "badges": ["SDXL", "动漫"],
        "tip": "通用 SDXL 动漫模型，LoRA 生态好，适合大多数二次元需求。",
        "advice": ["SDXL 原生分辨率约 1024，竖图 832×1216 比较稳。"],
    },
    "sdxl_photo": {
        "family": "sdxl_photo", "label": "写实 · SDXL", "kind": "photo",
        "steps": 30, "cfg": 5.0, "sampler": "dpmpp_2m",
        "recommended_size": "1216x832", "vpred": False, "pag": True,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": True,
        "badges": ["SDXL", "写实"],
        "tip": "写实/风景 SDXL 模型。建议横图 1216×832，DPM++ 2M。",
        "advice": ["写实模型不需要动漫质量词，描述主体、光线、镜头即可。"],
    },
    "pony": {
        "family": "pony", "label": "动漫 · Pony / SDXL", "kind": "anime",
        "steps": 25, "cfg": 6.0, "sampler": "euler_ancestral",
        "recommended_size": "1024x1024", "vpred": False, "pag": True,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": False,
        "badges": ["Pony", "标签系"],
        "tip": "Pony 系模型依赖 score_9、score_8_up 等质量标签；网页会自动补。",
        "advice": ["网页会自动补 score_9, score_8_up, score_7_up；自己写了就不会重复加。",
                   "负面词可用 score_4, score_5, score_6。"],
    },
    "sd15_anime": {
        "family": "sd15_anime", "label": "动漫 · SD1.5", "kind": "anime",
        "steps": 28, "cfg": 7.0, "sampler": "euler_ancestral",
        "recommended_size": "512x768", "vpred": False, "pag": False,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": True,
        "badges": ["SD1.5", "动漫"],
        "tip": "老一代 SD1.5 动漫模型，速度快、LoRA 多，但原生分辨率只有 512。",
        "advice": ["先用 512×768 出图；要更大再开高清修复。"],
    },
    "sd15": {
        "family": "sd15", "label": "通用 · SD1.5", "kind": "general",
        "steps": 28, "cfg": 7.0, "sampler": "euler_ancestral",
        "recommended_size": "512x768", "vpred": False, "pag": False,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": True,
        "badges": ["SD1.5"],
        "tip": "老一代 SD1.5 模型，速度快，适合低显存和快速草图。",
        "advice": ["直接开 1024 容易画出重复人物；先 512×768。"],
    },
    "flux": {
        "family": "flux", "label": "通用 · Flux", "kind": "general",
        "steps": 20, "cfg": 1.0, "sampler": "euler",
        "recommended_size": "1024x1024", "vpred": False, "pag": False,
        "supports_lora": True, "supports_negative": False,
        "supports_hires": False, "supported": False, "beginner": False,
        "badges": ["Flux", "实验性"],
        "tip": "Flux 通常需要单独的 UNET、CLIP 和 VAE，CFG 固定约 1。",
        "advice": ["当前网页对 Flux 只做识别；请确认你使用的是一体式 checkpoint。",
                   "多数 Flux 模型需要单独的组件加载流程，不建议新手先用。"],
    },
    "qwen_image": {
        "family": "qwen_image", "label": "通用 · Qwen-Image", "kind": "general",
        "steps": 20, "cfg": 2.5, "sampler": "euler",
        "recommended_size": "1024x1024", "vpred": False, "pag": False,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": False, "supported": False, "beginner": False,
        "badges": ["Qwen", "实验性"],
        "tip": "Qwen-Image 通常需要单独的 UNET、文本编码器和 VAE。",
        "advice": ["当前网页对 Qwen-Image 只做识别；建议使用 Anima 或 SDXL。"],
    },
    "unknown": {
        "family": "unknown", "label": "未识别模型", "kind": "general",
        "steps": 25, "cfg": 6.0, "sampler": "dpmpp_2m",
        "recommended_size": "832x1216", "vpred": False, "pag": True,
        "supports_lora": True, "supports_negative": True,
        "supports_hires": True, "supported": True, "beginner": False,
        "badges": ["未识别"],
        "tip": "没有从文件名或权重里认出架构，先按通用 SDXL 参数试用。",
        "advice": ["如果画面异常，请确认模型是 SD1.5、SDXL 还是 Flux。",
                   "可以在模型文件名里带上 sd15 / sdxl / pony / flux 方便识别。"],
    },
}

KIND_ZH = {"anime": "动漫", "photo": "写实", "general": "通用"}
KIND_EN = {"anime": "Anime", "photo": "Photo", "general": "General"}

# 常见模型在英文界面里用可读短名，避免所有 SDXL 都显示成“Photo · SDXL”。
NAME_HINTS = (
    ("animagine", "Animagine XL"),
    ("animapencil", "AnimaPencil XL"),
    ("anima", "Anima 2B"),
    ("noob", "NoobAI Vpred"),
    ("juggernaut", "Juggernaut XI"),
    ("illustrious", "Illustrious XL"),
    ("realvis", "RealVisXL"),
    ("counterfeit", "Counterfeit"),
    ("pony", "Pony Diffusion"),
    ("flux", "Flux"),
    ("qwen", "Qwen-Image"),
)


def _short_name(name):
    """从文件名取出适合放在模型 chip 上的短名。"""
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    low = stem.lower()
    for key, label in NAME_HINTS:
        if key in low:
            return label
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem[:48] or "Model"


EN = {
    "anima": {
        "label": "Anime · Anima 2B",
        "tip": "Great at natural descriptions and anime. No SDXL LoRA or PAG; use the Anima turbo LoRA for speed.",
        "advice": ["Start with the recommended settings.",
                   "Open Anima Turbo for 8-step generation."],
        "badges": ["Beginner pick", "Anime"],
    },
    "noob": {
        "label": "Anime · NoobAI Vpred",
        "tip": "Excellent character/artist tags. v-pred model: use Euler, CFG 4-5.",
        "advice": ["Do not switch to DPM++ or other samplers.",
                   "Add English tags for obscure characters."],
        "badges": ["v-pred", "Anime"],
    },
    "sdxl_anime": {
        "label": "Anime · SDXL",
        "tip": "General SDXL anime model with a large LoRA ecosystem.",
        "advice": ["832x1216 is a safe portrait size for SDXL."],
        "badges": ["SDXL", "Anime"],
    },
    "sdxl_photo": {
        "label": "Photo · SDXL",
        "tip": "SDXL photo/landscape model. Try 1216x832 with DPM++ 2M.",
        "advice": ["Describe subject, light and lens; skip anime quality tags."],
        "badges": ["SDXL", "Photo"],
    },
    "pony": {
        "label": "Anime · Pony / SDXL",
        "tip": "Pony models rely on score_9 / score_8_up tags; the UI adds them automatically.",
        "advice": ["score_9, score_8_up and score_7_up are added automatically unless you already included them.",
                   "Use score_4, score_5, score_6 as negative tags."],
        "badges": ["Pony", "Tag-based"],
    },
    "sd15_anime": {
        "label": "Anime · SD1.5",
        "tip": "Older SD1.5 anime model: fast and LoRA-rich, but native 512px.",
        "advice": ["Start at 512x768; use hires fix for larger images."],
        "badges": ["SD1.5", "Anime"],
    },
    "sd15": {
        "label": "General · SD1.5",
        "tip": "Older SD1.5 model: fast and light, good for drafts.",
        "advice": ["Do not go straight to 1024; start at 512x768."],
        "badges": ["SD1.5"],
    },
    "flux": {
        "label": "General · Flux",
        "tip": "Flux usually needs a separate UNET, CLIP and VAE; CFG is about 1.",
        "advice": ["The web UI only detects Flux; use an all-in-one checkpoint.",
                   "Split Flux pipelines are not beginner-friendly."],
        "badges": ["Flux", "Experimental"],
    },
    "qwen_image": {
        "label": "General · Qwen-Image",
        "tip": "Qwen-Image usually needs a separate UNET, text encoder and VAE.",
        "advice": ["The web UI only detects Qwen-Image; Anima or SDXL is recommended."],
        "badges": ["Qwen", "Experimental"],
    },
    "unknown": {
        "label": "Unrecognized model",
        "tip": "Architecture was not detected; generic SDXL settings are used.",
        "advice": ["If results look wrong, check whether this is SD1.5, SDXL or Flux.",
                   "Put sd15 / sdxl / pony / flux in the filename to help detection."],
        "badges": ["Unrecognized"],
    },
}


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
                "supports_hires", "beginner", "recommended_size"):
        if key in known and known[key] is not None:
            base[key] = known[key]
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
