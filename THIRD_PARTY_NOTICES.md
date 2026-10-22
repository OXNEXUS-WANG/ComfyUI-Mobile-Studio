# Third-party notices / 第三方组件说明

This repository contains the original integration code for Nexus.
It does **not** bundle ComfyUI, Python, PyTorch, model files, or most custom nodes;
the installer downloads them from their original distribution points.

本仓库只包含“手机出图”的集成代码。ComfyUI、Python、PyTorch、模型文件和大部分
自定义节点都不随仓库分发，由安装器从原发布地址下载。

The project's own code is licensed under the **PolyForm Noncommercial License
1.0.0** (see `LICENSE`). That license does **not** grant any rights to the
third-party components below, and cannot override their licenses.

> 本项目的商业授权只覆盖本项目自己编写的代码，不覆盖下列第三方组件、模型和数据。
> 商用前必须逐项确认其许可证；其中 ComfyUI 是 GPL-3.0，可能对分发产生额外
> 义务。上游 MiniSBD（AGPL-3.0）已由本项目的 MIT 兼容层替代，不再随安装器安装。

## 1. Included in this repository / 仓库内包含

| Component | Version / location | License | Notes |
|---|---|---|---|
| 7-Zip standalone `7zr.exe` | `tools/7zr.exe` | LGPL-2.1-or-later, with unRAR restriction | Only used to extract the official ComfyUI 7z archive. Full text: `tools/7zip-LICENSE.txt`; https://www.7-zip.org/license.txt |
| KERR black-hole shader (adapted) | `宇宙接口图.html` WebGL background | MIT, Copyright (c) 2026 Sumit Sahoo | Adapted from https://github.com/cloakyard/kerr; the MIT notice is also kept in the HTML file. |
| Project code, HTML/CSS/JS, workflows | rest of repository | PolyForm Noncommercial 1.0.0 | Original integration code. |

`comfyui.ico` and the UI styling are project assets unless a file says otherwise.
No third-party icon font or JavaScript framework is bundled.

## 2. Downloaded by the installer / 安装器下载

| Component | Source | License | Notes |
|---|---|---|---|
| ComfyUI | https://github.com/Comfy-Org/ComfyUI | GPL-3.0 | Official Windows portable build + latest source are downloaded; not included in this repo. |
| ComfyUI_UltimateSDUpscale | https://github.com/ssitu/ComfyUI_UltimateSDUpscale | GPL-3.0 | Installer downloads the node. |
| ultimate-upscale-for-automatic1111 | https://github.com/Coyote-A/ultimate-upscale-for-automatic1111 | GPL-3.0 | Submodule used by UltimateSDUpscale. |
| AlekPet ComfyUI Custom Nodes | https://github.com/AlekPet/ComfyUI_Custom_Nodes_AlekPet | MIT | Provides the Argos translation node. |
| ComfyUI-Manager | https://github.com/ltdrdata/ComfyUI-Manager | GPL-3.0 | Optional / often installed manually; not required by core generation. |
| ComfyUI-Custom-Scripts | https://github.com/pythongosssss/ComfyUI-Custom-Scripts | MIT | Optional, installed manually in the current setup. |
| AIGODLIKE-ComfyUI-Translation | https://github.com/AIGODLIKE/AIGODLIKE-ComfyUI-Translation | No standard SPDX license detected in the repository | Optional UI translation pack; check its repository terms before redistribution. |
| kohya-ss/sd-scripts | https://github.com/kohya-ss/sd-scripts, commit `11d8cedd0c67b93a10f8b2d75f43554f6f12c794` (0.12.2) | Apache-2.0 | Optional LoRA trainer, downloaded only when an administrator clicks “安装训练组件”; not bundled. |

Each downloaded project keeps its own license file in its folder. If you
redistribute an installation, keep those files and comply with their terms.

## 3. Python runtime dependencies / Python 运行时依赖

The installer installs these from PyPI (Tsinghua mirror by default):

| Package | License | Purpose |
|---|---|---|
| `psutil` | BSD-3-Clause | CPU / memory / process monitoring |
| `Pillow` | MIT-CMU (HPND-style) | Thumbnails, image validation, preview resizing |
| `cryptography` | Apache-2.0 OR BSD-3-Clause | HTTPS certificate handling |
| `argostranslate` | MIT | Offline Chinese→English translation |
| `ctranslate2` | MIT | Argos inference backend |
| `sentencepiece` | Apache-2.0 | Argos tokenization |
| `stanza` | Apache-2.0 | Argos tokenization/sentence handling |
| `sacremoses` | MIT | Argos tokenization |
| `minisbd`（本项目兼容层） | MIT | 独立的句子切分 shim；**不安装上游 AGPL 包**，见下文 |
| `packaging` | Apache-2.0 OR BSD-2-Clause | Dependency metadata |

ComfyUI's portable Python also contains Python (PSF-2.0), PyTorch
(BSD-3-Clause), torchvision (BSD-3-Clause), and NVIDIA CUDA/cuDNN runtime
libraries under NVIDIA's proprietary license. These are downloaded as part of
the ComfyUI portable package, not relicensed by this project.

### Optional LoRA training dependencies / 可选训练依赖

Only installed into the isolated `trainer/pysite` directory when an
administrator installs the training component. They do **not** replace
ComfyUI's torch/transformers:

| Package | License | Purpose |
|---|---|---|
| `diffusers` | Apache-2.0 | Anima/SDXL training pipelines |
| `accelerate` | Apache-2.0 | Mixed precision / device placement |
| `ftfy` | Apache-2.0 | Text cleanup for captions |
| `voluptuous` | BSD-3-Clause | Schema validation in sd-scripts |
| `imagesize` | MIT | Image metadata |
| `wcwidth` | MIT | Console output width |
| `opencv-python` | MIT (OpenCV: Apache-2.0) | Dataset image processing |

`training_requirements.txt` pins exact versions and SHA256 hashes; versions and
hashes are verified before import. The trainer keeps its own license files under
`trainer/sd-scripts` when installed.

### MiniSBD compatibility shim

Argos Translate imports a module named `minisbd`. Upstream MiniSBD is
**AGPL-3.0**, so this project does not install it. Instead, the installer
places an independent, permissively licensed compatibility shim at
`installer/minisbd_shim/minisbd`; its MIT license is in
`installer/minisbd_shim/LICENSE`. It implements `SBDetect` and
`models.list_models()` with a simple Chinese/English sentence splitter. It is
not copied from MiniSBD and is not the upstream project.

If you replace the shim with the real MiniSBD package, the AGPL-3.0 terms apply
to that component and must be reviewed separately.

### Translation model

The Chinese→English Argos model (`translate-zh_en-1_9`) is derived from an
OPUS-MT model licensed **CC-BY 4.0**. Attribution: Jörg Tiedemann and Santhosh
Thottingal, “OPUS-MT — Building open translation services for the World”,
EAMT 2020. The model package's README also states CC-BY 4.0. Keep this
attribution when redistributing the model.

## 4. Models / 模型

Model files are **not** included in this repository or in the setup ZIP. The
installer downloads them from their Hugging Face repositories:

| Pack | Repository | License / terms |
|---|---|---|
| Anima | `circlestone-labs/Anima` | See model card |
| Anima turbo LoRA | `diffusionmodels1254ani/Anima-Official-LoRAs` | See model card |
| NoobAI-XL Vpred | `Laxhar/noobai-XL-Vpred-1.0` | See model card |
| Juggernaut XI v11 | `RunDiffusion/Juggernaut-XI-v11` | See model card |
| Illustrious-XL v2.0 | `OnomaAIResearch/Illustrious-XL-v2.0` | See model card |
| RealVisXL V5.0 Lightning | `SG161222/RealVisXL_V5.0_Lightning` | See model card |
| Pony Diffusion V6 XL | `LyliaEngine/Pony_Diffusion_V6_XL` | See model card |
| Animagine XL 4.0 | `cagliostrolab/animagine-xl-4.0` | See model card |
| Counterfeit-V2.5 | `gsdf/Counterfeit-V2.5` | See model card |
| Wan 2.1 | `Comfy-Org/Wan_2.1_ComfyUI_repackaged` | See model card |
| 4x-UltraSharp | `lokCX/4x-Ultrasharp` | See model card |
| RealESRGAN x4plus / anime | `amd/realesrgan-x4plus`, `amd/realesrgan-x4plus-anime-6b` | See model cards |

**Important:** several image models have non-commercial or restricted-use
terms. A commercial license for the integration code does not grant rights to
these weights or to images generated with them. Check every model card and the
terms of any LoRA you add.

## 5. Data / 数据

`char_tags.json` contains character/work aliases and tags compiled from public
Danbooru-style tag data. Danbooru content is contributed by its users and is
subject to the source site's terms and any applicable rights in character
names, artwork titles, and tags. This project does not claim ownership of that
data. If you redistribute a large extracted dataset, review the source site's
terms and applicable law.

User-uploaded training images, captions, checkpoints and logs live under
`trainings/<account>/<project>/` and are not included in the repository, setup
ZIP or offline bundle. The operator is responsible for having the right to use
the training images and for the license terms of any resulting LoRA weights.

## 6. GPL and commercial licensing

This project's own code is offered under PolyForm Noncommercial 1.0.0, but:

- ComfyUI and several custom nodes are GPL-3.0. If you distribute them together
  with this project, comply with GPL-3.0 for those components (including source
  availability and notices).
- Upstream MiniSBD is AGPL-3.0, but it is **not installed**; the MIT shim is
  used instead. If a customer replaces the shim with upstream MiniSBD, AGPL
  terms apply to that component.
- Model weights and generated images have their own terms.

The commercial license offered for this project therefore covers the original
integration code, not ComfyUI, third-party nodes, or model weights. A commercial
deployment should still review GPL obligations and model licenses with
qualified counsel.

## 7. Keeping this file current

When adding a new dependency, custom node, model pack, font, icon set, or
copied code snippet, add it here with its source URL and license before
publishing a release.
