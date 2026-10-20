# 两个发行版

本项目现在分 **分享版** 和 **商用版**，代码同源，授权和安装默认值不同。

## 分享版（Share）

- 面向个人学习、研究、实验、爱好和非商业组织；
- 许可证：**PolyForm Noncommercial License 1.1.0**；
- 包含完整源码、测试、文档和普通安装器；
- 安装器可以让用户选择安装 ComfyUI、模型、插件和中文翻译；
- 不能直接用于商业经营；商业用途需另购商用授权。

> 严格来说，PolyForm Noncommercial 不是 OSI 定义的开源许可证，而是
> “源码可见、非商业免费”的源代码许可。

构建：

```powershell
.\build_release.ps1 -Version 1.1.0 -Edition share
```

输出：`dist\ComfyUI-Mobile-Studio-v1.1.0-Share.zip`

## 商用版（Commercial）

- 面向购买商业授权的客户；
- 许可证：`LICENSE` 中的 Commercial Software License Agreement（EULA）；
- 只卖安装器和网页集成代码，**不包含 ComfyUI、模型、LoRA、放大模型**；
- 默认商业清洁安装：
  - 不下载画图模型
  - 不安装 GPL 自定义节点
  - 中文翻译使用 MIT 兼容层 + CC-BY 4.0 模型，不安装 AGPL 的 MiniSBD
  - 已有 ComfyUI 直接复用，不自动更新
  - 没有 ComfyUI 时询问是否下载官方版本
- 不包含测试和 CI 文件，减小发行包体积。

构建：

```powershell
.\build_release.ps1 -Version 1.1.0 -Edition commercial
```

输出：`dist\ComfyUI-Mobile-Studio-v1.1.0-Commercial.zip`

## 重要边界

- 两个版本都不在 Setup ZIP 里放模型或 ComfyUI；
- 商用版也不自动集成 GPL/AGPL 组件，但用户自行安装后仍受其原许可证约束；
- `tools\7zr.exe` 随安装器分发，LGPL 文本见 `tools\7zip-LICENSE.txt`；
- 商业版的具体价格、支持、部署数量以正式订单/合同为准；
- 两个版本都使用 `installer/versions.lock.json` 做版本锁定，不自动追最新；
- 商业发行前建议让律师审核 EULA、GPL 条款和模型许可。
