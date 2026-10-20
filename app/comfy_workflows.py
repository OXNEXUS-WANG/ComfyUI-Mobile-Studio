# -*- coding: utf-8 -*-
"""ComfyUI HTTP 调用和工作流构建。

模型常量、采样器、负面词等仍由 app_core.py 提供；
这里只放“怎么拼计算图”，方便单独调整节点。
"""
import json
import os
import urllib.request

from app_core import *


# --------------------------------------------------------------------- ComfyUI

def http_json(path, payload=None, timeout=60):
    if payload is None:
        req = urllib.request.Request(COMFY + path)
    else:
        req = urllib.request.Request(
            COMFY + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def comfy_current_prompt():
    """ComfyUI 当前真正在跑的 prompt_id；读不到返回空字符串。"""
    try:
        q = http_json("/queue", timeout=5)
        running = q.get("queue_running") or []
        if running and isinstance(running[0], (list, tuple)) and len(running[0]) > 1:
            return str(running[0][1])
    except Exception:
        pass
    return ""


def source_megapixels(filename):
    """读 input 目录里参考图的像素数（百万像素）。读不到就返回 None。"""
    if not filename:
        return None
    try:
        from PIL import Image
        path = os.path.join(INPUT_DIR, os.path.basename(filename))
        if not os.path.isfile(path):
            return None
        with Image.open(path) as im:
            return (im.width * im.height) / 1_000_000.0
    except Exception:
        return None


def build_workflow(prompt, negative, width, height, steps, cfg, seed,
                   use_translate, count=1, init_image=None, init_mask=None,
                   denoise=1.0, ckpt=DEFAULT_CHECKPOINT,
                   loras=None, hires=False, hires_scale=1.3,
                   sampler=DEFAULT_SAMPLER, pag=True, vpred=False,
                   char_tags=None, prefix=""):
    """构造计算图：文生图 / 图生图 / 局部重绘，可选 LoRA 和高清修复。

    loras      : [{"name": "xxx.safetensors", "strength": 0.8}, ...] 按顺序串联
    hires      : True 时在出图后放大 latent 再低重绘率采样一遍
    hires_scale: 放大倍数（1.3 ≈ 面积 +69%，显存吃紧别调太高）
    sampler    : SAMPLERS 里的键，决定采样器 + 调度器
    pag        : True 时套一层 PAG，细节更清楚但每张多算一次前向
    vpred      : True 时按 v-prediction 模型处理（NoobAI Vpred）：
                 clip skip 2 + ModelSamplingDiscrete(v_prediction, zsnr) + RescaleCFG
    prefix     : 额外拼在正向提示词最前面的固定英文标签（Pony 质量词）
    """
    sp = SAMPLERS.get(sampler) or SAMPLERS[DEFAULT_SAMPLER]
    if vpred:
        # NoobAI 官方要求：只用 Euler，其他采样器会出问题
        sp = {"sampler": "euler", "sched": "normal"}
    nodes = {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": count}},
        "7": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or DEFAULT_NEGATIVE, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": sp["sampler"], "scheduler": sp["sched"],
                         "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0],
                         "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "phone", "images": ["8", 0]}},
    }

    # 参考图过大就先等比缩到安全像素数，否则 8GB 显存会直接爆掉（表现为一直转圈）。
    src_mp = source_megapixels(init_image)
    msk_mp = source_megapixels(init_mask) if init_mask else None
    need_scale = any(m is not None and m > MAX_SOURCE_MEGAPIXELS
                     for m in (src_mp, msk_mp))

    if init_mask:
        # 局部重绘：蒙版白色区域重画，其余保留
        del nodes["5"]
        nodes["11"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        nodes["12"] = {"class_type": "LoadImage", "inputs": {"image": init_mask}}
        pix, msk = ["11", 0], ["12", 0]
        if need_scale:
            # 原图和蒙版缩到同一像素上限，保证两者仍然对齐；
            # 蒙版用 nearest-exact，避免插值把黑白边界糊成灰边。
            nodes["15"] = {"class_type": "ImageScaleToTotalPixels",
                           "inputs": {"image": ["11", 0],
                                      "upscale_method": "lanczos",
                                      "megapixels": MAX_SOURCE_MEGAPIXELS,
                                      "resolution_steps": 8}}
            nodes["16"] = {"class_type": "ImageScaleToTotalPixels",
                           "inputs": {"image": ["12", 0],
                                      "upscale_method": "nearest-exact",
                                      "megapixels": MAX_SOURCE_MEGAPIXELS,
                                      "resolution_steps": 8}}
            pix, msk = ["15", 0], ["16", 0]
        nodes["13"] = {"class_type": "ImageToMask",
                       "inputs": {"image": msk, "channel": "red"}}
        nodes["14"] = {"class_type": "VAEEncodeForInpaint",
                       "inputs": {"pixels": pix, "vae": ["4", 2],
                                  "mask": ["13", 0], "grow_mask_by": 6}}
        nodes["3"]["inputs"]["latent_image"] = ["14", 0]
        nodes["3"]["inputs"]["denoise"] = denoise
    elif init_image:
        # 图生图：画幅由参考图决定，去掉空白 latent
        del nodes["5"]
        nodes["11"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        pix = ["11", 0]
        if need_scale:
            nodes["15"] = {"class_type": "ImageScaleToTotalPixels",
                           "inputs": {"image": ["11", 0],
                                      "upscale_method": "lanczos",
                                      "megapixels": MAX_SOURCE_MEGAPIXELS,
                                      "resolution_steps": 8}}
            pix = ["15", 0]
        nodes["12"] = {"class_type": "VAEEncode",
                       "inputs": {"pixels": pix, "vae": ["4", 2]}}
        nodes["3"]["inputs"]["latent_image"] = ["12", 0]
        nodes["3"]["inputs"]["denoise"] = denoise

    # ---- LoRA：按选择顺序串成一条链，模型和 CLIP 都要跟着走 ----
    model_src, clip_src = ["4", 0], ["4", 1]
    if loras:
        for i, item in enumerate(loras):
            nid = str(20 + i)
            try:
                st = float(item.get("strength", 1.0))
            except (TypeError, ValueError):
                st = 1.0
            nodes[nid] = {"class_type": "LoraLoader",
                          "inputs": {"lora_name": item["name"],
                                     "strength_model": st, "strength_clip": st,
                                     "model": model_src, "clip": clip_src}}
            model_src, clip_src = [nid, 0], [nid, 1]

    # ---- v-pred（NoobAI）：clip skip 2 + v_prediction + RescaleCFG ----
    # 少了这三步，v-pred 模型会出灰蒙蒙的废图；官方要求 Euler 采样器。
    if vpred:
        nodes["44"] = {"class_type": "CLIPSetLastLayer",
                       "inputs": {"clip": clip_src, "stop_at_clip_layer": -2}}
        clip_src = ["44", 0]
        nodes["45"] = {"class_type": "ModelSamplingDiscrete",
                       "inputs": {"model": model_src,
                                  "sampling": "v_prediction", "zsnr": True}}
        model_src = ["45", 0]
        nodes["46"] = {"class_type": "RescaleCFG",
                       "inputs": {"model": model_src, "multiplier": 0.7}}
        model_src = ["46", 0]

    # ---- PAG：包在 LoRA 之后，主采样和高清修复的第二遍都会经过它 ----
    if pag:
        nodes["40"] = {"class_type": "PerturbedAttentionGuidance",
                       "inputs": {"model": model_src, "scale": PAG_SCALE}}
        model_src = ["40", 0]

    nodes["3"]["inputs"]["model"] = model_src
    nodes["7"]["inputs"]["clip"] = clip_src

    if use_translate:
        nodes["10"] = {"class_type": "ArgosTranslateTextNode",
                       "inputs": {"from_translate": "chinese",
                                  "to_translate": "english", "text": prompt}}
        nodes["6"] = {"class_type": "CLIPTextEncode",
                      "inputs": {"text": ["10", 0], "clip": clip_src}}
    else:
        nodes["6"] = {"class_type": "CLIPTextEncode",
                      "inputs": {"text": prompt, "clip": clip_src}}

    # 中文翻译会丢掉 danbooru 标签，NoobAI 容易画成 2.5D；
    # 在翻译结果前面拼一段固定的英文质量/动漫标签（Argos 不会碰到它）。
    pos_src = ["6", 0]
    if vpred and use_translate:
        nodes["50"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": NOOB_PREFIX, "clip": clip_src}}
        nodes["51"] = {"class_type": "ConditioningConcat",
                       "inputs": {"conditioning_to": ["50", 0],
                                  "conditioning_from": ["6", 0]}}
        pos_src = ["51", 0]
    # 中文角色名换成的英文标签，拼在最前面（Argos 不会碰到）
    if char_tags:
        nodes["52"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": ", ".join(char_tags),
                                  "clip": clip_src}}
        nodes["53"] = {"class_type": "ConditioningConcat",
                       "inputs": {"conditioning_to": ["52", 0],
                                  "conditioning_from": pos_src}}
        pos_src = ["53", 0]
    # Pony 的 score_9... 质量标签，单独编码并拼在最前面
    if prefix:
        nodes["54"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": prefix, "clip": clip_src}}
        nodes["55"] = {"class_type": "ConditioningConcat",
                       "inputs": {"conditioning_to": ["54", 0],
                                  "conditioning_from": pos_src}}
        pos_src = ["55", 0]
    nodes["3"]["inputs"]["positive"] = pos_src

    # ---- 高清修复：先放大 latent，再用较低重绘率重采样一遍 ----
    # 只放大 latent 不重新编码，细节比直接出大图更好；解码改用分块版省显存。
    if hires:
        nodes["30"] = {"class_type": "LatentUpscaleBy",
                       "inputs": {"samples": ["3", 0],
                                  "upscale_method": "bislerp",
                                  "scale_by": float(hires_scale)}}
        nodes["31"] = {"class_type": "KSampler",
                       "inputs": {"seed": seed,
                                  "steps": max(12, int(steps * 0.8)),
                                  "cfg": cfg,
                                  "sampler_name": sp["sampler"],
                                  "scheduler": sp["sched"],
                                  "denoise": 0.55,
                                  "model": model_src,
                                  "positive": pos_src,
                                  "negative": ["7", 0],
                                  "latent_image": ["30", 0]}}
        # 用普通 VAEDecode：VAEDecodeTiled 的分块接缝会在图上留下横向条纹
        nodes["8"] = {"class_type": "VAEDecode",
                      "inputs": {"samples": ["31", 0], "vae": ["4", 2]}}

    return {"prompt": nodes, "client_id": "mobile_web"}


def build_anima_workflow(prompt, negative, width, height, steps, cfg, seed,
                         use_translate, count=1, init_image=None,
                         init_mask=None, denoise=1.0,
                         sampler=DEFAULT_SAMPLER, hires=False,
                         hires_scale=1.3, turbo=False, char_tags=None):
    """Anima 2B（Cosmos 架构）工作流：文生图 / 图生图 / 局部重绘 / 高清修复。

    和 SDXL 不同，模型、文本编码器、VAE 是三个独立文件，分别用
    UNETLoader / CLIPLoader / VAELoader 加载。官方推荐 30 步 / CFG 4。
    turbo=True 时套官方 Turbo LoRA，强制 8 步 / CFG 1（快一倍多）。
    Anima 用不了 SDXL 的 LoRA，也没有验证过 PAG，这两项由调用方关掉。
    """
    if turbo:
        steps, cfg = ANIMA_TURBO_STEPS, ANIMA_TURBO_CFG
    sp = SAMPLERS.get(sampler) or SAMPLERS[DEFAULT_SAMPLER]
    nodes = {
        "4": {"class_type": "UNETLoader",
              "inputs": {"unet_name": ANIMA_MODEL, "weight_dtype": "default"}},
        "41": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": ANIMA_CLIP, "type": "stable_diffusion",
                          "device": "default"}},
        "42": {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA_VAE}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": count}},
        "7": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or ANIMA_NEGATIVE, "clip": ["41", 0]}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         # Anima 是流匹配模型，调度器固定用 simple
                         "sampler_name": sp["sampler"], "scheduler": "simple",
                         "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0],
                         "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["3", 0], "vae": ["42", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "phone", "images": ["8", 0]}},
    }

    # 极速模式：只套官方 Turbo LoRA，模型本体不变
    model_src = ["4", 0]
    if turbo:
        nodes["43"] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"lora_name": ANIMA_TURBO_LORA,
                                  "strength_model": 1.0, "model": model_src}}
        model_src = ["43", 0]
    nodes["3"]["inputs"]["model"] = model_src

    # 参考图过大同样先缩到安全像素数，避免 8GB 爆显存
    src_mp = source_megapixels(init_image)
    msk_mp = source_megapixels(init_mask) if init_mask else None
    need_scale = any(m is not None and m > MAX_SOURCE_MEGAPIXELS
                     for m in (src_mp, msk_mp))

    if init_mask:
        del nodes["5"]
        nodes["11"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        nodes["12"] = {"class_type": "LoadImage", "inputs": {"image": init_mask}}
        pix, msk = ["11", 0], ["12", 0]
        if need_scale:
            nodes["15"] = {"class_type": "ImageScaleToTotalPixels",
                           "inputs": {"image": ["11", 0],
                                      "upscale_method": "lanczos",
                                      "megapixels": MAX_SOURCE_MEGAPIXELS,
                                      "resolution_steps": 8}}
            nodes["16"] = {"class_type": "ImageScaleToTotalPixels",
                           "inputs": {"image": ["12", 0],
                                      "upscale_method": "nearest-exact",
                                      "megapixels": MAX_SOURCE_MEGAPIXELS,
                                      "resolution_steps": 8}}
            pix, msk = ["15", 0], ["16", 0]
        nodes["13"] = {"class_type": "ImageToMask",
                       "inputs": {"image": msk, "channel": "red"}}
        nodes["14"] = {"class_type": "VAEEncodeForInpaint",
                       "inputs": {"pixels": pix, "vae": ["42", 0],
                                  "mask": ["13", 0], "grow_mask_by": 6}}
        nodes["3"]["inputs"]["latent_image"] = ["14", 0]
        nodes["3"]["inputs"]["denoise"] = denoise
    elif init_image:
        del nodes["5"]
        nodes["11"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        pix = ["11", 0]
        if need_scale:
            nodes["15"] = {"class_type": "ImageScaleToTotalPixels",
                           "inputs": {"image": ["11", 0],
                                      "upscale_method": "lanczos",
                                      "megapixels": MAX_SOURCE_MEGAPIXELS,
                                      "resolution_steps": 8}}
            pix = ["15", 0]
        nodes["12"] = {"class_type": "VAEEncode",
                       "inputs": {"pixels": pix, "vae": ["42", 0]}}
        nodes["3"]["inputs"]["latent_image"] = ["12", 0]
        nodes["3"]["inputs"]["denoise"] = denoise

    if use_translate:
        nodes["10"] = {"class_type": "ArgosTranslateTextNode",
                       "inputs": {"from_translate": "chinese",
                                  "to_translate": "english", "text": prompt}}
        nodes["6"] = {"class_type": "CLIPTextEncode",
                      "inputs": {"text": ["10", 0], "clip": ["41", 0]}}
    else:
        nodes["6"] = {"class_type": "CLIPTextEncode",
                      "inputs": {"text": prompt, "clip": ["41", 0]}}

    # 中文角色名换成的英文标签，拼在最前面
    pos_src = ["6", 0]
    if char_tags:
        nodes["52"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": ", ".join(char_tags),
                                  "clip": ["41", 0]}}
        nodes["53"] = {"class_type": "ConditioningConcat",
                       "inputs": {"conditioning_to": ["52", 0],
                                  "conditioning_from": pos_src}}
        pos_src = ["53", 0]
    nodes["3"]["inputs"]["positive"] = pos_src

    if hires:
        nodes["30"] = {"class_type": "LatentUpscaleBy",
                       "inputs": {"samples": ["3", 0],
                                  "upscale_method": "bislerp",
                                  "scale_by": float(hires_scale)}}
        nodes["31"] = {"class_type": "KSampler",
                       "inputs": {"seed": seed,
                                  "steps": max(12, int(steps * 0.8)),
                                  "cfg": cfg,
                                  "sampler_name": sp["sampler"],
                                  "scheduler": "simple",
                                  "denoise": 0.55,
                                  "model": model_src,
                                  "positive": pos_src,
                                  "negative": ["7", 0],
                                  "latent_image": ["30", 0]}}
        nodes["8"] = {"class_type": "VAEDecode",
                      "inputs": {"samples": ["31", 0], "vae": ["42", 0]}}

    return {"prompt": nodes, "client_id": "mobile_web"}


def build_video_workflow(prompt, negative, width, height, frames, seed,
                         use_translate=False, steps=20, cfg=6.0):
    """Wan 2.1 T2V 1.3B 文生视频。

    Wan 是 16fps、且帧数必须是 4n+1；网页那边按 8fps 的「秒数」传帧数，
    所以这里换算：length = frames * 2 + 1（16→33、24→49、32→65）。
    """
    length = max(5, ((frames * 2) // 4) * 4 + 1)

    nodes = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": VIDEO_UNET,
                         "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": VIDEO_CLIP, "type": "wan"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": ["12", 0] if use_translate else prompt,
                         "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or VIDEO_NEGATIVE,
                         "clip": ["2", 0]}},
        "6": {"class_type": "ModelSamplingSD3",
              "inputs": {"model": ["1", 0], "shift": 8.0}},
        "7": {"class_type": "EmptyHunyuanLatentVideo",
              "inputs": {"width": width, "height": height,
                         "length": length, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "uni_pc", "scheduler": "simple",
                         "denoise": 1.0, "model": ["6", 0],
                         "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "CreateVideo",
               "inputs": {"images": ["9", 0], "fps": float(VIDEO_FPS)}},
        "11": {"class_type": "SaveVideo",
               "inputs": {"video": ["10", 0],
                          "filename_prefix": "video/wan",
                          "format": "mp4"}},
    }
    if use_translate:
        nodes["12"] = {"class_type": "ArgosTranslateTextNode",
                       "inputs": {"from_translate": "chinese",
                                  "to_translate": "english",
                                  "text": prompt}}
    return {"prompt": nodes, "client_id": "mobile_web"}


def build_i2v_workflow(prompt, negative, width, height, frames, seed,
                       image_name, use_translate=False, steps=20, cfg=6.0):
    """Wan 2.1 VACE 1.3B 图生视频：拿上传的图当参考主体，生成一段动态视频。

    VACE 的 WanVaceToVideo 节点吃 reference_image，输出三路：
    positive / negative / latent，直接接 KSampler。
    """
    length = max(5, ((frames * 2) // 4) * 4 + 1)

    nodes = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": VIDEO_VACE,
                         "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": VIDEO_CLIP, "type": "wan"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": ["12", 0] if use_translate else prompt,
                         "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or VIDEO_NEGATIVE,
                         "clip": ["2", 0]}},
        "6": {"class_type": "ModelSamplingSD3",
              "inputs": {"model": ["1", 0], "shift": 8.0}},
        "13": {"class_type": "LoadImage",
               "inputs": {"image": image_name}},
        "7": {"class_type": "WanVaceToVideo",
              "inputs": {"positive": ["4", 0], "negative": ["5", 0],
                         "vae": ["3", 0],
                         "width": width, "height": height,
                         "length": length, "batch_size": 1,
                         "strength": 1.0,
                         "reference_image": ["13", 0]}},
        "8": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "uni_pc", "scheduler": "simple",
                         "denoise": 1.0, "model": ["6", 0],
                         "positive": ["7", 0], "negative": ["7", 1],
                         "latent_image": ["7", 2]}},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "CreateVideo",
               "inputs": {"images": ["9", 0], "fps": float(VIDEO_FPS)}},
        "11": {"class_type": "SaveVideo",
               "inputs": {"video": ["10", 0],
                          "filename_prefix": "video/i2v",
                          "format": "mp4"}},
    }
    if use_translate:
        nodes["12"] = {"class_type": "ArgosTranslateTextNode",
                       "inputs": {"from_translate": "chinese",
                                  "to_translate": "english",
                                  "text": prompt}}
    return {"prompt": nodes, "client_id": "mobile_web"}


def build_upscale_workflow(image_name, up_model, factor):
    """放大工作流：ESRGAN 4 倍，如需 2 倍再缩回来。"""
    nodes = {
        "1": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": up_model}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "ImageUpscaleWithModel",
              "inputs": {"upscale_model": ["1", 0], "image": ["2", 0]}},
    }
    last = ["3", 0]
    if factor == 2:
        nodes["4"] = {"class_type": "ImageScaleBy",
                      "inputs": {"image": ["3", 0],
                                 "upscale_method": "lanczos", "scale_by": 0.5}}
        last = ["4", 0]
    nodes["9"] = {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "up", "images": last}}
    return {"prompt": nodes, "client_id": "mobile_web"}


def friendly_error(status):
    """把 ComfyUI 的报错翻成人话。"""
    text = json.dumps(status, ensure_ascii=False)
    low = text.lower()
    if "out of memory" in low or "outofmemory" in low or "alloc" in low:
        return "显存不足。把画幅改小、视频时长改短，或把张数改成 1 张再试。"
    if "ckpt_name" in low or "checkpoint" in low:
        return "底模加载失败。去 ComfyUI 窗口看看模型文件是否完整。"
    for kind, payload in (status.get("messages") or []):
        if kind == "execution_error":
            msg = payload.get("exception_message") or ""
            node = payload.get("node_type") or ""
            return "出图失败\n节点: %s\n%s" % (node, msg[:400])
    return "出图失败\n" + text[:500]
