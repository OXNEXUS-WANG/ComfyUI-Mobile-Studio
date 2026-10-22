# 上传到 GitHub

这个目录已经初始化好 Git，并完成第一次公开提交；**没有配置 remote，也没有上传任何东西**。
公开提交已排除 `license_admin/` 授权签发工具，发布包也不包含账号、证书、日志和模型。

## 1. 创建空仓库

在 GitHub 新建一个空仓库，例如：

```text
ComfyUI-Mobile-Studio
```

- 可见性选 **Public**
- 不要勾选自动创建 README / .gitignore / License，因为本地已经有了

## 2. 推送源码

在本目录打开 PowerShell：

```powershell
git remote add origin https://github.com/你的用户名/ComfyUI-Mobile-Studio.git
git branch -M main
git push -u origin main
```

第一次推送会弹出 GitHub 登录窗口（Windows 自带的 Git Credential Manager）。
登录后会自动保存凭据，以后 `git push` 不再询问。

如果本机没有 git，可以使用：

```text
D:\AI\ComfyUI_windows_portable\git\cmd\git.exe
```

或者直接安装 GitHub Desktop / Git for Windows。

> 只有确认要公开时才推送。`backup-before-public` 分支是本地旧历史备份，
> **不要**执行 `git push --all` 或推送该分支。

## 3. 运行测试

推送前先在本地跑一遍：

```powershell
python tests\run_tests.py
```

GitHub Actions 会在 push / pull request 时自动运行 `.github/workflows/tests.yml`。
在线冒烟和 worker 近似验收需要服务和管理员密码，不会在 CI 里运行。

## 4. 发布安装包

1. 分别构建两个版本：

```powershell
.\build_release.ps1 -Version 1.2.7 -Edition share
.\build_release.ps1 -Version 1.2.7 -Edition commercial
```

2. 打开 GitHub 仓库 → **Releases** → **Draft a new release**。
3. Tag 填 `v1.2.7`，标题填 `v1.2.7`。
4. 上传：

```text
dist\Nexus-v1.2.7-Share.zip
dist\Nexus-v1.2.7-Commercial.zip
```

商用版也可以只私下交付给购买客户，不公开上传到 GitHub Release。

构建完成后运行 `Get-FileHash` 生成 `dist/SHA256SUMS.txt`，随 Release 一起上传；
校验和不要写死在本文件里，否则会改变包内容本身。

5. 发布。

`dist/` 已被 `.gitignore` 忽略，安装包只作为 Release 附件，不需要提交进仓库。

## 5. 检查

推送前确认没有这些文件被提交：

- `ComfyUI/`
- `python_embeded/`
- `models/`、`*.safetensors`、`*.ckpt`、`*.pth`
- `users.json`、`workers.json`、`sessions.json`、`jobs_state.json`
- 确认 `LICENSE`、`COMMERCIAL_LICENSE.md`、`商用授权说明.md`、
  `THIRD_PARTY_NOTICES.md` 已随仓库提交
- `cert.pem`、`key.pem`
- `generated/`、`logs/`、`web_uploads/`
- `worker/worker_agent.json`

本仓库的 `.gitignore` 已经覆盖这些路径。

## 6. 当前提交

以本目录的 `git log -1 --oneline` 为准。最近一次稳定版提交包含模型自动适配、
自动化测试、任务持久化、备份恢复和 worker 近似验收。

如果之后修改了文件：

```powershell
git add .
git commit -m "Update installer"
git push
```

