param(
    [string]$Version = "1.0.0",
    [ValidateSet("share", "commercial")]
    [string]$Edition = "share"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Stage = Join-Path $env:TEMP ("comfy-mobile-studio-" + [guid]::NewGuid().ToString("N"))
$Dist = Join-Path $Root "dist"
$Suffix = if ($Edition -eq "commercial") { "Commercial" } else { "Share" }
$Zip = Join-Path $Dist ("ComfyUI-Mobile-Studio-v" + $Version + "-" + $Suffix + ".zip")

function Remove-Staged($rel) {
    $p = Join-Path $Stage $rel
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

Write-Host ("Staging " + $Edition + " release...")
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
$exclude = @(".git", "dist", "__pycache__", ".venv", "venv", "_installer_test")
Get-ChildItem $Root -Force | Where-Object { $_.Name -notin $exclude } | ForEach-Object {
    if ($_.PSIsContainer) {
        Copy-Item $_.FullName (Join-Path $Stage $_.Name) -Recurse -Force
    } else {
        Copy-Item $_.FullName (Join-Path $Stage $_.Name) -Force
    }
}
# 不把运行时缓存带进发布包（包括子目录里的 __pycache__）
Get-ChildItem $Stage -Recurse -Directory -Filter "__pycache__" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $Stage -Recurse -File -Filter "*.pyc" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# 运行期状态、日志和密钥绝不进发布包（.gitignore 不作用于 Compress-Archive）
$runtimeFiles = @(
    "users.json", "users.json.bak", "sessions.json", "workers.json", "usage.json",
    "jobs_state.json", "jobs_resume.json", "supervisor.json", "instance.lock",
    "supervisor_status.json", "time_state.json", "trusted_time.key",
    "local_llm.json", "monitor.json",
    "monitor_alerts.json", "monitor_trends.json", "cleanup.json",
    "queue_control.json", "teams.json", "team_prompts.json",
    "trainings.json", "trainings.json.bak",
    "training_settings.json", "training_settings.json.bak",
    "loras.json", "loras.json.bak",
    "sensitive_filter.json", "sensitive_filter.json.bak",
    "disclaimer_accepted.json",
    "license.json", "cert.pem", "key.pem", "worker_agent.json", "access.json"
)
Get-ChildItem $Stage -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in $runtimeFiles } |
    Remove-Item -Force -ErrorAction SilentlyContinue
# 安装器续期证书时留下的旧证书/私钥备份也不能进发布包
Get-ChildItem $Stage -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "cert.pem.bak-*" -or
                   $_.Name -like "key.pem.bak-*" } |
    Remove-Item -Force -ErrorAction SilentlyContinue
$runtimeDirs = @("logs", "_restore_points", "generated", "web_uploads",
    "_backups", "_model_trash", "_model_uploads",
    "_node_trash", "_node_uploads", "workflows", "plugins",
    "trainings", "training_uploads", "trainer",
    "_training_trash", "_trainer_trash", "_lora_trash")
foreach ($name in $runtimeDirs) {
    Get-ChildItem $Stage -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $name } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
# 授权签发工具只留在维护者仓库，绝不进入客户发布包
Remove-Staged "license_admin"

if ($Edition -eq "commercial") {
    # The commercial edition ships under the commercial EULA, not PolyForm.
    if (-not (Test-Path (Join-Path $Stage "COMMERCIAL_EULA.md"))) {
        throw "缺少 COMMERCIAL_EULA.md"
    }
    Copy-Item (Join-Path $Stage "COMMERCIAL_EULA.md") (Join-Path $Stage "LICENSE") -Force
    Remove-Staged "COMMERCIAL_EULA.md"
    Remove-Staged "COMMERCIAL_LICENSE.md"
    Remove-Staged "商用授权说明.md"
    Remove-Staged "GITHUB_UPLOAD.md"
    Remove-Staged "README.md"
    Copy-Item (Join-Path $Root "README-COMMERCIAL.md") (Join-Path $Stage "README.md") -Force
    Remove-Staged "README-COMMERCIAL.md"
    Remove-Staged "安装_商业版.bat"
    if (Test-Path (Join-Path $Stage "安装.bat")) {
        Remove-Item (Join-Path $Stage "安装.bat") -Force
    }
    Copy-Item (Join-Path $Root "安装_商业版.bat") (Join-Path $Stage "安装.bat") -Force
    # 英文入口也必须进入商业清洁模式，不能复用分享版的 install.bat。
    Copy-Item (Join-Path $Root "安装_商业版.bat") (Join-Path $Stage "install.bat") -Force
    # Commercial build is installer-only: no test suite or CI files.
    Remove-Staged "tests"
    Remove-Staged "运行测试.bat"
    Remove-Staged ".github"
    Remove-Staged "CHANGELOG.md"
    Remove-Staged "EDITIONS.md"
    Remove-Staged "安装说明.txt"
    Copy-Item (Join-Path $Stage "安装说明_商业版.txt") (Join-Path $Stage "安装说明.txt") -Force
    Remove-Staged "安装说明_商业版.txt"
    Set-Content -Path (Join-Path $Stage "EDITION") -Value "commercial" -Encoding ascii
} else {
    Remove-Staged "README-COMMERCIAL.md"
    Remove-Staged "安装说明_商业版.txt"
    Remove-Staged "COMMERCIAL_EULA.md"
    Remove-Staged "商用版授权协议.md"
    Set-Content -Path (Join-Path $Stage "EDITION") -Value "share" -Encoding ascii
}

Set-Content -Path (Join-Path $Stage "VERSION") -Value $Version -Encoding ascii
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Write-Host ("Creating " + $Zip)
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -CompressionLevel Optimal
Remove-Item $Stage -Recurse -Force
Write-Host ("Done: " + $Zip)
