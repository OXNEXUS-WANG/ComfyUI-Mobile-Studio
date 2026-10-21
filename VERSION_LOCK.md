# 版本锁定 / Version lock

目标：**默认不跟随上游更新**，避免 ComfyUI、Python 依赖、自定义节点或模型文件
突然变化导致环境报错。锁文件是：

```text
installer/versions.lock.json
```

## 锁了什么

| 项目 | 锁定方式 |
|---|---|
| ComfyUI | `v0.42.0` 的官方 Windows 便携包 `ComfyUI_windows_portable_nvidia.7z`，并校验大小 |
| ComfyUI 源码 | 使用便携包自带的 0.42.0，不再安装器额外拉取 master |
| Python 基础依赖 | `psutil` / `pillow` / `cryptography` 精确版本 |
| 翻译组件 | `argostranslate` / `ctranslate2` / `sentencepiece` / `stanza` / `sacremoses` / `packaging` 精确版本 |
| 自定义节点 | UltimateSDUpscale、其子模块、AlekPet 固定到 commit SHA |
| 模型文件 | 每个模型文件固定 Hugging Face `revision`（commit SHA）和大小 |
| Argos 模型 | `translate-zh_en-1_9.argosmodel`，固定文件大小 |
| 7-Zip | `tools/7zr.exe` 的 SHA256 |
| MiniSBD | 本项目 MIT 兼容层 `1.0`，不安装上游 AGPL 包 |
| LoRA 训练器 | kohya sd-scripts `0.12.2`，commit `11d8cedd0c67b93a10f8b2d75f43554f6f12c794`，ZIP 大小 + SHA256；依赖版本和哈希见 `training_requirements.txt` |

## 安装器的默认行为

- 新安装：使用锁定的 ComfyUI 便携包和精确依赖；
- 已有 ComfyUI：默认**复用，不自动更新**；
- 版本不一致：只警告，不擅自升级；
- 显式加 `-AllowUpdates` 才会回到“拉取最新 ComfyUI 源码”的旧行为，不推荐；
- `-SkipComfyUI` / `-ComfyUIDir` 用于只用用户已有环境；
- 安装报告 `install_report.txt` 会写 ComfyUI 锁定版本。

## 模型下载

`download_models.py` 会读取每个文件的 `revision`，URL 形如：

```text
https://hf-mirror.com/<repo>/resolve/<commit-sha>/<path>
```

不是 `resolve/main`，所以上游更新默认分支不会改变已锁定的模型文件。

## 如何升级

不要直接改运行目录。正确流程：

1. 在测试机修改 `installer/versions.lock.json`；
2. 更新模型 manifest 的 `revision` 和 `size`；
3. 用 `-DryRun` 检查；
4. 在干净目录跑一次完整安装和出图测试；
5. 提交锁文件，重建两个发布包；
6. 用户升级时显式使用新安装包，而不是让安装器自动追最新。

## 注意

- 上游可能删除某个版本或 yanked 某个 PyPI 版本；遇到这种情况需要换镜像或重新锁定并测试；
- ComfyUI 便携包目前按版本 + 大小锁定，没有内置完整 SHA256（2GB 文件未随仓库分发）；
- 用户手工安装的 ComfyUI、模型和插件不受本项目锁文件控制；
- `-AllowUpdates` 会脱离锁定，只应在测试环境使用。
