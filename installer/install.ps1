param(
    [string]$InstallDir = "",
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$SkipModels,
    [string]$ModelPacks = "",
    [switch]$NoTranslate,
    [switch]$NoCustomNodes,
    [switch]$CommercialClean,
    [switch]$SkipComfyUI,
    [string]$ComfyUIDir = "",
    [string]$ComfyZip = "",
    [switch]$AllowUpdates,
    [switch]$NoShortcut,
    [switch]$NoDialog,
    [switch]$AcceptDisclaimer
)

$PkgRoot = Split-Path -Parent $PSScriptRoot
$Edition = "share"
# 商用包即使被直接运行 install.ps1 或英文 install.bat，也强制清洁模式，
# 避免误下模型/装 GPL 节点。
$EditionFile = Join-Path $PkgRoot "EDITION"
if (Test-Path $EditionFile) {
    $Edition = (Get-Content $EditionFile -Raw -Encoding ASCII).Trim()
    if ($Edition -eq "commercial") { $CommercialClean = $true }
}
if ($CommercialClean) {
    $SkipModels = $true
    $NoCustomNodes = $true
}
if ($ComfyUIDir -and -not $InstallDir) { $InstallDir = $ComfyUIDir }
if ($ComfyUIDir) { $SkipComfyUI = $true }
if ($ComfyUIDir -and $InstallDir) {
    $a = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    $b = [IO.Path]::GetFullPath($ComfyUIDir).TrimEnd('\')
    if ($a -ne $b) { throw "-InstallDir 和 -ComfyUIDir 指向不同目录，只能指定一个。" }
}

$ErrorActionPreference = "Stop"
$PkgRoot = Split-Path -Parent $PSScriptRoot
$AppVersion = "1.3.10"
$VersionFile = Join-Path $PkgRoot "VERSION"
if (Test-Path $VersionFile) {
    $v = (Get-Content $VersionFile -Raw -Encoding ASCII).Trim()
    if ($v) { $AppVersion = $v }
}
$DisclaimerVersion = "1.2"
$DisclaimerFile = Join-Path $PkgRoot "DISCLAIMER.md"
$Curl = Join-Path $env:SystemRoot "System32\curl.exe"
$SevenZip = Join-Path $PkgRoot "tools\7zr.exe"
$Manifest = Join-Path $PkgRoot "installer\models_manifest.json"
$LockFile = Join-Path $PkgRoot "installer\versions.lock.json"
$HfMirror = "https://hf-mirror.com"
if (-not (Test-Path $LockFile)) { throw ("安装包缺少版本锁定文件：" + $LockFile) }
$Lock = Get-Content $LockFile -Raw -Encoding UTF8 | ConvertFrom-Json
$ComfyVersion = [string]$Lock.comfyui.version
$ComfyMin = [string]$Lock.comfyui.compatible_min
$ComfyTag = [string]$Lock.comfyui.tag
$ComfyAssetName = [string]$Lock.comfyui.asset
$ComfyAsset = ("https://github.com/Comfy-Org/ComfyUI/releases/download/" +
               $ComfyTag + "/" + $ComfyAssetName)
$ComfyProxy = "https://gh-proxy.com/" + $ComfyAsset
$ComfySize = [int64]$Lock.comfyui.size
$PythonBase = @($Lock.python.base)
$PythonArgos = [string]$Lock.python.argos
$PythonTranslation = @($Lock.python.translation)
$NodeUltimate = [string]$Lock.nodes.ultimate_upscale
$NodeUltimateSub = [string]$Lock.nodes.ultimate_upscale_sub
$NodeAlekPet = [string]$Lock.nodes.alekpet
$ArgosModelFile = [string]$Lock.argos_model.file
$ArgosModelSize = [int64]$Lock.argos_model.size
$LockSevenZipHash = [string]$Lock.sevenzip_sha256
$LogFile = Join-Path $env:TEMP "CometInk-install.log"
$ComfyWasFresh = $false

function Say($msg, $color = "White") {
    Write-Host $msg -ForegroundColor $color
}
function Step($n, $msg) {
    Write-Host ""
    Write-Host ("[{0}] {1}" -f $n, $msg) -ForegroundColor Cyan
}
function Warn($msg) { Say ("  !! " + $msg) "Yellow" }
function Ok($msg) { Say ("  [OK] " + $msg) "Green" }
function Fail($msg) { throw $msg }

# ---------------------------------------------------- 环境冲突辅助
$script:StageName = "启动"
$script:Adaptations = New-Object System.Collections.ArrayList
$script:Conflicts = New-Object System.Collections.ArrayList
$script:DisclaimerAccepted = $false
$script:DisclaimerAcceptedAt = ""
$script:DisclaimerMode = ""
$script:Dialogs = $false
if (-not $NoDialog -and -not $Yes) {
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $script:Dialogs = [Environment]::UserInteractive
    } catch { $script:Dialogs = $false }
}

function Add-Adaptation($msg) {
    [void]$script:Adaptations.Add($msg)
    Warn ("已自动适配：" + $msg)
}

function Add-Conflict($msg) {
    [void]$script:Conflicts.Add($msg)
    Warn ("环境冲突：" + $msg)
}

function Show-Gui($text, $title, $buttons = "OK", $icon = "Warning") {
    if (-not $script:Dialogs) { return "No" }
    try {
        $b = [System.Windows.Forms.MessageBoxButtons]::OK
        if ($buttons -eq "YesNo") { $b = [System.Windows.Forms.MessageBoxButtons]::YesNo }
        elseif ($buttons -eq "YesNoCancel") { $b = [System.Windows.Forms.MessageBoxButtons]::YesNoCancel }
        $i = [System.Windows.Forms.MessageBoxIcon]::Warning
        if ($icon -eq "Error") { $i = [System.Windows.Forms.MessageBoxIcon]::Error }
        elseif ($icon -eq "Question") { $i = [System.Windows.Forms.MessageBoxIcon]::Question }
        elseif ($icon -eq "Information") { $i = [System.Windows.Forms.MessageBoxIcon]::Information }
        return [System.Windows.Forms.MessageBox]::Show($text, $title, $b, $i).ToString()
    } catch { return "No" }
}

function Use-ConsoleChoice($message) {
    if ($Yes -or $NoDialog) { return $false }
    $ans = Read-Host ("  " + $message + " [Y/n]")
    return ($ans -notmatch '^[nN]')
}

# ---------------------------------------------------- 首次安装免责声明
function Show-Disclaimer {
    # 醒目、可滚动、必须勾选同意的免责声明窗口。返回是否同意。
    if (-not $script:Dialogs) { return $false }
    if (-not (Test-Path $DisclaimerFile)) {
        Fail ("安装包缺少免责声明文件：" + $DisclaimerFile)
    }
    $text = (Get-Content $DisclaimerFile -Raw -Encoding UTF8).Trim()
    if (-not $text) { Fail ("免责声明文件为空：" + $DisclaimerFile) }
    # 窗口里显示去掉 Markdown 记号的纯文本，文件本身保留完整格式。
    $displayText = $text -replace '(?m)^#+\s*', '' -replace '\*\*', ''
    $displayText = $displayText -replace '(?m)^---+$', '' -replace "`r`n`r`n`r`n", "`r`n`r`n"
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop
    } catch {
        Fail ("无法创建免责声明窗口：" + $_.Exception.Message)
    }

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "免责声明与使用协议 · 安装前必须阅读"
    $form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::None
    $workArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $cw = [Math]::Min(780, [Math]::Max(480, $workArea.Width - 40))
    $ch = [Math]::Min(700, [Math]::Max(400, $workArea.Height - 40))
    $form.ClientSize = New-Object System.Drawing.Size($cw, $ch)
    $form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ShowInTaskbar = $true
    $form.TopMost = $true
    $form.BackColor = [System.Drawing.Color]::FromArgb(12, 16, 26)
    $form.ForeColor = [System.Drawing.Color]::FromArgb(235, 240, 250)

    $header = New-Object System.Windows.Forms.Panel
    $header.Location = New-Object System.Drawing.Point(0, 0)
    $header.Size = New-Object System.Drawing.Size($cw, 96)
    $header.BackColor = [System.Drawing.Color]::FromArgb(128, 22, 30)
    $form.Controls.Add($header)

    $title = New-Object System.Windows.Forms.Label
    $title.Text = "重要：请先阅读免责声明"
    $title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 17, [System.Drawing.FontStyle]::Bold)
    $title.ForeColor = [System.Drawing.Color]::White
    $title.AutoSize = $false
    $title.Location = New-Object System.Drawing.Point(24, 14)
    $title.Size = New-Object System.Drawing.Size(($cw - 48), 34)
    $header.Controls.Add($title)

    $subtitle = New-Object System.Windows.Forms.Label
    $subtitle.Text = "不同意请退出安装；勾选同意后才能继续。同意前不会修改系统。"
    $subtitle.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9.5)
    $subtitle.ForeColor = [System.Drawing.Color]::FromArgb(255, 220, 220)
    $subtitle.AutoSize = $false
    $subtitle.Location = New-Object System.Drawing.Point(26, 54)
    $subtitle.Size = New-Object System.Drawing.Size(($cw - 50), 26)
    $header.Controls.Add($subtitle)

    $box = New-Object System.Windows.Forms.RichTextBox
    $box.Location = New-Object System.Drawing.Point(24, 112)
    $box.Size = New-Object System.Drawing.Size(($cw - 48), ($ch - 270))
    $box.ReadOnly = $true
    $box.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
    $box.BackColor = [System.Drawing.Color]::FromArgb(8, 11, 18)
    $box.ForeColor = [System.Drawing.Color]::FromArgb(220, 228, 240)
    $box.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9.5)
    $box.ScrollBars = [System.Windows.Forms.RichTextBoxScrollBars]::Vertical
    $box.DetectUrls = $false
    $box.Text = $displayText
    $box.Select(0, 0)
    $form.Controls.Add($box)

    $agree = New-Object System.Windows.Forms.CheckBox
    $agree.Text = "我已阅读并理解上述免责声明，并同意遵守全部条款"
    $agree.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10.5, [System.Drawing.FontStyle]::Bold)
    $agree.ForeColor = [System.Drawing.Color]::FromArgb(255, 226, 150)
    $agree.AutoSize = $false
    $agree.Location = New-Object System.Drawing.Point(24, ($ch - 146))
    $agree.Size = New-Object System.Drawing.Size(($cw - 48), 30)
    $form.Controls.Add($agree)

    $hint = New-Object System.Windows.Forms.Label
    $hint.Text = "提示：必须先勾选同意框，「同意并继续」按钮才会变为可点击。"
    $hint.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
    $hint.ForeColor = [System.Drawing.Color]::FromArgb(150, 166, 190)
    $hint.AutoSize = $false
    $hint.Location = New-Object System.Drawing.Point(24, ($ch - 112))
    $hint.Size = New-Object System.Drawing.Size(($cw - 48), 24)
    $form.Controls.Add($hint)

    $decline = New-Object System.Windows.Forms.Button
    $decline.Text = "退出安装"
    $decline.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
    $decline.Location = New-Object System.Drawing.Point(
        ($cw - 24 - 146 - 12 - 132), ($ch - 64))
    $decline.Size = New-Object System.Drawing.Size(132, 44)
    $decline.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 68)
    $decline.ForeColor = [System.Drawing.Color]::FromArgb(235, 240, 250)
    $decline.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $decline.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(110, 120, 140)
    $form.Controls.Add($decline)

    $accept = New-Object System.Windows.Forms.Button
    $accept.Text = "同意并继续"
    $accept.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10, [System.Drawing.FontStyle]::Bold)
    $accept.Location = New-Object System.Drawing.Point(
        ($cw - 24 - 146), ($ch - 64))
    $accept.Size = New-Object System.Drawing.Size(146, 44)
    $accept.BackColor = [System.Drawing.Color]::FromArgb(46, 160, 110)
    $accept.ForeColor = [System.Drawing.Color]::White
    $accept.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $accept.FlatAppearance.BorderSize = 0
    $accept.Enabled = $false
    $form.Controls.Add($accept)

    $form.AcceptButton = $accept
    $form.CancelButton = $decline
    $script:DlgForm = $form
    $script:DlgAgree = $agree
    $script:DlgAccept = $accept
    $script:DlgAccepted = $false
    $agree.Add_CheckedChanged({
        $script:DlgAccept.Enabled = [bool]$script:DlgAgree.Checked
    })
    $accept.Add_Click({
        if ($script:DlgAgree.Checked) {
            $script:DlgAccepted = $true
            $script:DlgForm.Close()
        }
    })
    $decline.Add_Click({
        $script:DlgAccepted = $false
        $script:DlgForm.Close()
    })

    try {
        $form.ShowDialog() | Out-Null
    } finally {
        try { $form.Dispose() } catch { }
    }
    return [bool]$script:DlgAccepted
}

function Write-DisclaimerMarker([string]$Dir, [string]$Mode) {
    # 把接受记录写到安装目录；只用于本机首次安装判断，不放进发布包。
    $marker = Join-Path $Dir "disclaimer_accepted.json"
    $payload = [ordered]@{
        accepted = $true
        version = $DisclaimerVersion
        accepted_at = $script:DisclaimerAcceptedAt
        app_version = $AppVersion
        edition = $Edition
        method = $Mode
        user = [string]$env:USERNAME
        machine = [string]$env:COMPUTERNAME
    }
    try {
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        $json = $payload | ConvertTo-Json
        [IO.File]::WriteAllText(
            $marker, $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Warn ("无法写入免责声明接受记录：" + $_.Exception.Message)
    }
}

function Confirm-Disclaimer([string]$Dir) {
    if ($DryRun) {
        Say "  DryRun：不修改任何文件，跳过免责声明接受记录。" "Cyan"
        return
    }
    if (-not (Test-Path $DisclaimerFile)) {
        Fail ("安装包缺少免责声明文件：" + $DisclaimerFile)
    }
    $marker = Join-Path $Dir "disclaimer_accepted.json"
    if (Test-Path $marker) {
        try {
            $old = Get-Content $marker -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($old.accepted -eq $true -and
                [string]$old.version -eq $DisclaimerVersion) {
                $script:DisclaimerAccepted = $true
                $script:DisclaimerAcceptedAt = [string]$old.accepted_at
                $script:DisclaimerMode = "此前已接受"
                Ok ("免责声明已接受（" + $script:DisclaimerAcceptedAt + "）")
                return
            }
        } catch {
            Warn "免责声明接受记录损坏，将重新显示协议。"
        }
    }

    $script:StageName = "免责声明"
    if ($AcceptDisclaimer) {
        $script:DisclaimerAccepted = $true
        $script:DisclaimerAcceptedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        $script:DisclaimerMode = "无人值守参数 -AcceptDisclaimer"
        Write-DisclaimerMarker $Dir "command_line"
        Ok "已通过 -AcceptDisclaimer 接受免责声明。"
        return
    }
    if (-not $script:Dialogs) {
        Fail ("首次安装需要阅读并同意免责声明。" +
              "`n无人值守安装请显式添加 -AcceptDisclaimer 参数。")
    }

    Say ""
    Say "  首次安装：必须阅读并同意免责声明后才能继续。" "Red"
    if (-not (Show-Disclaimer)) {
        Fail "用户取消安装：未同意免责声明。"
    }
    $script:DisclaimerAccepted = $true
    if (-not $script:DisclaimerAcceptedAt) {
        $script:DisclaimerAcceptedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    }
    $script:DisclaimerMode = "安装界面勾选同意"
    Write-DisclaimerMarker $Dir "interactive"
    Ok "免责声明已接受，继续安装。"
}

function Clear-PythonEnv {
    $keys = @("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE",
              "PIP_TARGET", "PIP_USER")
    $found = @()
    foreach ($k in $keys) {
        $item = Get-Item ("Env:" + $k) -ErrorAction SilentlyContinue
        if ($item -and $item.Value) {
            $found += ($k + "=" + $item.Value)
            Remove-Item ("Env:" + $k) -ErrorAction SilentlyContinue
        }
    }
    $env:PYTHONNOUSERSITE = "1"
    $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
    if ($found.Count -gt 0) {
        Add-Adaptation ("已临时清理外部 Python 环境变量：" + ($found -join "; "))
    }
}

function Get-PortOwner($port) {
    $ownerPid = 0
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($conn) { $ownerPid = [int]$conn.OwningProcess }
    } catch { }
    if (-not $ownerPid) {
        try {
            $lines = & netstat -ano 2>$null |
                Select-String (":" + $port + "\s") |
                Select-String "LISTENING"
            if ($lines) {
                $parts = ($lines[0].ToString().Trim() -split "\s+")
                $ownerPid = [int]$parts[$parts.Length - 1]
            }
        } catch { }
    }
    if (-not $ownerPid) { return $null }
    $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    $cmd = ""
    $path = ""
    try {
        $ci = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $ownerPid) -ErrorAction Stop
        $cmd = [string]$ci.CommandLine
        $path = [string]$ci.ExecutablePath
    } catch { }
    if (-not $path -and $proc) { try { $path = $proc.Path } catch { } }
    $name = "unknown"
    if ($proc) { $name = $proc.ProcessName }
    return [pscustomobject]@{
        Port = [int]$port
        Pid = [int]$ownerPid
        Name = $name
        Path = $path
        CommandLine = $cmd
    }
}

function Test-OwnProcess($owner) {
    if (-not $owner) { return $false }
    if (-not $InstallDir) { return $false }
    $root = $InstallDir.ToLower().TrimEnd('\')
    $path = ([string]$owner.Path).ToLower()
    $cmd = ([string]$owner.CommandLine).ToLower()
    if ($path -and $path.StartsWith($root + "\")) { return $true }
    if ($cmd -and $cmd.Contains($root + "\")) { return $true }
    return $false
}

function Stop-OwnProcess($owner, $label) {
    if (-not $owner) { return $true }
    $detail = "  程序: " + $owner.Name + " (PID " + $owner.Pid + ")"
    if ($owner.Path) { $detail += "`n  " + $owner.Path }
    $msg = "检测到 $label 正在运行：`n$detail`n`n安装需要先停止它，否则文件会被占用。"
    $stop = $false
    if ($script:Dialogs) {
        $stop = (Show-Gui ($msg + "`n`n是否自动停止？") "运行中的程序" "YesNo" "Question") -eq "Yes"
    } elseif ($Yes) {
        $stop = $true
    } else {
        $stop = Use-ConsoleChoice ($msg + "`n  是否自动停止？")
    }
    if (-not $stop) { return $false }
    try {
        Stop-Process -Id $owner.Pid -Force -ErrorAction Stop
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 250
            if (-not (Get-Process -Id $owner.Pid -ErrorAction SilentlyContinue)) { break }
        }
        Add-Adaptation ("已停止 " + $label + "（PID " + $owner.Pid + "）")
        return $true
    } catch {
        Warn ("停止 " + $label + " 失败：" + $_.Exception.Message)
        return $false
    }
}

function New-AltInstallDir {
    $base = $InstallDir.TrimEnd('\')
    $alt = $base + "-Mobile-Studio"
    $n = 2
    while (Test-Path $alt) {
        $alt = $base + "-Mobile-Studio" + $n
        $n++
    }
    return $alt
}

function Resolve-DirectoryConflict($reason) {
    if ($Yes -or $NoDialog) {
        throw ($reason + "`n请换一个空目录后重新运行安装器。")
    }
    $alt = New-AltInstallDir
    $msg = $reason + "`n`n建议改用新目录：`n" + $alt +
           "`n`n是否使用这个新目录继续安装？"
    $ok = $false
    if ($script:Dialogs) {
        $ok = (Show-Gui $msg "安装目录冲突" "YesNo" "Warning") -eq "Yes"
    } else {
        $ok = Use-ConsoleChoice $msg
    }
    if (-not $ok) { throw ("用户取消安装：目录冲突（" + $InstallDir + "）。") }
    Add-Adaptation ("安装目录改为 " + $alt)
    return $alt
}

function Test-WritableDir($dir) {
    try {
        New-Item -ItemType Directory -Force -Path $dir -ErrorAction Stop | Out-Null
        $probe = Join-Path $dir (".mgs_write_" + [guid]::NewGuid().ToString("N") + ".tmp")
        try {
            [IO.File]::WriteAllText($probe, "ok")
            Remove-Item $probe -Force -ErrorAction Stop
            return $true
        } catch { return $false }
    } catch { return $false }
}

function Get-InstallDirUserItems($dir) {
    # 安装器自己会写这些文件；判断“目录是否为空”时必须忽略，
    # 否则一次失败/中断后的重跑会把它们当成外部文件，误报目录非空。
    $ignored = @(
        "_downloads", "_bootstrap",
        "disclaimer_accepted.json", "install_report.txt"
    )
    return @(Get-ChildItem $dir -Force | Where-Object {
        $_.Name -notin $ignored -and $_.Name -notlike ".mgs_write_*.tmp"
    })
}

function Resolve-PortConflicts {
    foreach ($port in @(8188, 8800)) {
        $owner = Get-PortOwner $port
        if (-not $owner) { continue }
        $label = "ComfyUI（8188）"
        if ($port -eq 8800) { $label = "手机网页服务（8800）" }
        if (Test-OwnProcess $owner) {
            if (Stop-OwnProcess $owner $label) { continue }
            throw ("安装需要先停止 " + $label + "（PID " + $owner.Pid + "）。" +
                   "`n请关闭后重新运行安装器。")
        }
        Add-Conflict ("端口 " + $port + " 被 " + $owner.Name +
                      "（PID " + $owner.Pid + "）占用")
        $detail = "  程序: " + $owner.Name + " (PID " + $owner.Pid + ")"
        if ($owner.Path) { $detail += "`n  " + $owner.Path }
        $msg = "端口 $port 被其他程序占用：`n$detail`n`n" +
               "安装可以继续，但启动后 $label 无法使用。`n" +
               "建议先关闭该程序，或在它的设置里改端口。`n`n" +
               "是否继续安装（稍后自行处理端口）？"
        $cont = $false
        if ($script:Dialogs) {
            $cont = (Show-Gui $msg "端口冲突" "YesNo" "Warning") -eq "Yes"
        } elseif ($Yes -or $NoDialog) {
            $cont = $true
            Warn $msg
        } else {
            $cont = Use-ConsoleChoice $msg
        }
        if (-not $cont) {
            throw ("用户取消安装：端口 " + $port + " 被 " + $owner.Name + " 占用。")
        }
        Add-Adaptation ("端口 " + $port + " 被外部程序占用，安装继续；启动前需要关闭它")
    }
}

function Resolve-TargetProcesses {
    if (-not (Test-Path $InstallDir)) { return }
    $root = $InstallDir.ToLower().TrimEnd('\')
    $seen = @{}
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $exe = ([string]$_.ExecutablePath).ToLower()
            $cmd = ([string]$_.CommandLine).ToLower()
            ($exe -and $exe.StartsWith($root + "\python_embeded\")) -or
            ($cmd -and ($cmd.Contains("mobile_web.py") -or
                       $cmd.Contains("comfyui\main.py") -or
                       $cmd.Contains("comfyui/main.py") -or
                       $cmd.Contains("start_service.py")))
        })
    # 守护进程必须先停，否则它会在安装过程中把网页/ComfyUI 又拉起来
    $ordered = @()
    $ordered += @($procs | Where-Object {
        ([string]$_.CommandLine).ToLower().Contains("start_service.py") })
    $ordered += @($procs | Where-Object {
        -not ([string]$_.CommandLine).ToLower().Contains("start_service.py") })
    foreach ($p in $ordered) {
        if ([int]$p.ProcessId -eq $PID) { continue }
        if ($seen.ContainsKey([int]$p.ProcessId)) { continue }
        $seen[[int]$p.ProcessId] = $true
        $owner = [pscustomobject]@{
            Port = 0
            Pid = [int]$p.ProcessId
            Name = $p.Name
            Path = [string]$p.ExecutablePath
            CommandLine = [string]$p.CommandLine
        }
        if (-not (Test-OwnProcess $owner)) { continue }
        if (-not (Stop-OwnProcess $owner "安装目录里的程序")) {
            throw ("安装目录里的程序正在运行（" + $p.Name + "，PID " +
                   $p.ProcessId + "），无法继续。")
        }
    }
}

function Backup-ExistingNode($path, $label) {
    if (-not (Test-Path $path)) { return $true }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Join-Path $InstallDir ("_node_trash\installer-" + $stamp + "\" + $label)
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Move-Item $path $backup -Force -ErrorAction Stop
        Add-Adaptation ("已备份旧的 " + $label + " 到 " + $backup)
        return $true
    } catch {
        Warn ("无法备份旧的 " + $label + "：" + $_.Exception.Message)
        return $false
    }
}

function Get-ProblemAdvice($err) {
    $m = [string]$err
    if ($m -match "目录不是空|不像本程序|目录冲突") {
        return "1. 换一个空目录，或安装器建议的 -Mobile-Studio 子目录。`n2. 如果这是旧安装，请选择包含 ComfyUI\main.py 和 python_embeded\python.exe 的目录。`n3. 不要把安装目录指向桌面、下载或项目源码目录。"
    }
    if ($m -match "便携 Python|python_embeded") {
        return "1. 把 python_embeded 改名备份，再重新运行安装器。`n2. 关闭杀毒软件，检查它是否隔离了 python.exe。`n3. 仍不行就换目录重装，现有模型/账号可以手动复制回去。"
    }
    if ($m -match "端口|占用|PID") {
        return "1. 关闭占用 8188/8800 的程序，或在它的设置里改端口。`n2. 重新运行安装器。`n3. 点『是』打开日志和诊断报告，里面有 PID 和路径。"
    }
    if ($m -match "下载失败|网络|curl|超时|SSL|证书") {
        return "1. 检查网络/代理，确认能访问 gh-proxy.com、hf-mirror.com。`n2. 重新运行安装器，已下载的部分会断点续传。`n3. 模型可以稍后双击『模型下载.bat』补装。"
    }
    if ($m -match "拒绝访问|Access|权限|只读|写入") {
        return "1. 换一个普通目录（如 D:\AI\...），不要装到 Program Files/Windows。`n2. 关闭杀毒软件的文件夹保护，或以管理员身份运行。`n3. 检查目录是否被另一个程序占用。"
    }
    if ($m -match "空间") {
        return "1. 清理安装盘，或换到剩余空间至少 20GB 的盘。`n2. 或重新运行并选择不下载模型。"
    }
    if ($m -match "解压|压缩包|7z|损坏") {
        return "1. 删除安装目录里的 _downloads 后重试。`n2. 检查磁盘空间和杀毒软件隔离。`n3. 核对安装包 SHA256。"
    }
    if ($m -match "依赖|pip|Python|python") {
        return "1. 检查网络，安装器会先走清华 PyPI 再走官方源。`n2. 确认没有设置 PYTHONHOME/PYTHONPATH（安装器会尝试清理）。`n3. 若 python_embeded 损坏，把安装目录改名后重装。"
    }
    return "1. 点『是』打开安装日志和诊断报告，查看最后的红色报错。`n2. 换一个空目录重新安装。`n3. 关闭杀毒软件后重试。"
}

function Write-ProblemReport($err) {
    $dir = $env:TEMP
    if ($InstallDir) {
        try {
            if (Test-Path (Split-Path -Qualifier $InstallDir)) { $dir = $InstallDir }
        } catch { }
    }
    try { New-Item -ItemType Directory -Force -Path $dir | Out-Null } catch { $dir = $env:TEMP }
    $path = Join-Path $dir "install_problem.txt"
    $lines = @()
    $lines += "CometInk 安装诊断"
    $lines += ("时间: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    $lines += ("阶段: " + $script:StageName)
    $lines += ("错误: " + [string]$err)
    $lines += ("安装目录: " + $InstallDir)
    $lines += ("系统: " + [Environment]::OSVersion.VersionString)
    $lines += ("PowerShell: " + $PSVersionTable.PSVersion.ToString())
    $lines += ("64 位系统: " + [Environment]::Is64BitOperatingSystem)
    $lines += ("管理员: " + (Test-Admin))
    $gpuVar = Get-Variable -Name GpuText -Scope Script -ErrorAction SilentlyContinue
    if ($gpuVar) { $lines += ("显卡: " + $gpuVar.Value) }
    $freeVar = Get-Variable -Name freeGB -Scope Script -ErrorAction SilentlyContinue
    if ($freeVar) { $lines += ("可用空间: " + $freeVar.Value + " GB") }
    $lines += ("日志: " + $LogFile)
    $lines += ""
    $lines += "自动适配:"
    if ($script:Adaptations.Count -eq 0) {
        $lines += "  （无）"
    } else {
        foreach ($x in $script:Adaptations) { $lines += ("  - " + $x) }
    }
    $lines += "环境冲突:"
    if ($script:Conflicts.Count -eq 0) {
        $lines += "  （无）"
    } else {
        foreach ($x in $script:Conflicts) { $lines += ("  - " + $x) }
    }
    $lines += ""
    $lines += "端口占用:"
    foreach ($p in @(8188, 8800)) {
        $o = Get-PortOwner $p
        if ($o) {
            $lines += ("  " + $p + " <- " + $o.Name + " (PID " + $o.Pid + ") " + $o.Path)
        } else {
            $lines += ("  " + $p + " 空闲")
        }
    }
    $lines += ""
    $lines += "建议排查:"
    $lines += (Get-ProblemAdvice $err)
    Set-Content -Path $path -Value $lines -Encoding UTF8
    return $path
}

function Show-ProblemDialog($err) {
    $report = Write-ProblemReport $err
    $advice = Get-ProblemAdvice $err
    $text = "安装没有完成：`n" + [string]$err + "`n`n建议这样排查：`n" + $advice +
            "`n`n诊断报告：`n" + $report + "`n安装日志：`n" + $LogFile
    if ($script:Dialogs) {
        $r = Show-Gui $text "CometInk · 安装遇到问题" "YesNo" "Error"
        if ($r -eq "Yes") {
            if (Test-Path $LogFile) {
                Start-Process notepad.exe -ArgumentList ('"' + $LogFile + '"')
            }
            if (Test-Path $report) {
                Start-Process explorer.exe -ArgumentList ('/select,"' + $report + '"')
            }
        }
    } else {
        Say ""
        Say $text "Yellow"
    }
}

function Test-Admin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $p = New-Object Security.Principal.WindowsPrincipal($id)
        return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function Test-Url($url) {
    try {
        & $Curl -s -I -L --max-time 25 $url | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Download-File($urls, $dest, $minBytes, $label) {
    $parent = Split-Path -Parent $dest
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -ge $minBytes)) {
        Ok ("已有 " + $label + "，跳过下载")
        return
    }
    foreach ($url in $urls) {
        Say ("  下载 " + $label)
        Say ("    " + $url) "DarkGray"
        & $Curl -L --fail --retry 3 --retry-delay 2 --connect-timeout 25 -C - -o $dest $url
        if (($LASTEXITCODE -eq 0) -and (Test-Path $dest) -and ((Get-Item $dest).Length -ge $minBytes)) {
            Ok ("下载完成 " + $label)
            return
        }
        Warn ("这个下载源失败，尝试下一个：" + $url)
    }
    Fail ("下载失败：" + $label)
}

function Expand-7z($archive, $dest) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    & $SevenZip x $archive ("-o" + $dest) -y | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail ("解压失败：" + $archive) }
}

function Expand-Zip($archive, $dest) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Expand-Archive -Path $archive -DestinationPath $dest -Force
}

function Get-ZipTop($dir) {
    $top = Get-ChildItem $dir -Directory -Force | Select-Object -First 1
    if (-not $top) { Fail ("ZIP 内容为空：" + $dir) }
    return $top.FullName
}

function Copy-Tree($src, $dst) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Get-ChildItem $src -Force | ForEach-Object {
        $target = Join-Path $dst $_.Name
        if ($_.PSIsContainer) {
            Copy-Tree $_.FullName $target
        } else {
            Copy-Item $_.FullName $target -Force
        }
    }
}

function Copy-AppFiles {
    Say "  复制网页、星图和 worker 程序..."
    Get-ChildItem (Join-Path $PkgRoot "app") -Force | ForEach-Object {
        if ($_.PSIsContainer) {
            Copy-Tree $_.FullName (Join-Path $InstallDir $_.Name)
        } else {
            Copy-Item $_.FullName (Join-Path $InstallDir $_.Name) -Force
        }
    }
    # 品牌从 Nexus 迁移到 CometInk 后，清理安装目录里的旧品牌图标。
    Remove-Item (Join-Path $InstallDir "nexus.ico") -Force -ErrorAction SilentlyContinue
    Get-ChildItem $InstallDir -Force -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer -and
                       $_.Name -like "nexus-icon-*.png" } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    $editionFile = Join-Path $PkgRoot "EDITION"
    if (Test-Path $editionFile) {
        Copy-Item $editionFile (Join-Path $InstallDir "EDITION") -Force
    }
    Copy-Tree (Join-Path $PkgRoot "worker") (Join-Path $InstallDir "worker")
    Copy-Tree (Join-Path $PkgRoot "docs") (Join-Path $InstallDir "docs")
    Copy-Item (Join-Path $PkgRoot "docs\使用说明.md") (Join-Path $InstallDir "使用说明.md") -Force
    $instDest = Join-Path $InstallDir "installer"
    New-Item -ItemType Directory -Force -Path $instDest | Out-Null
    foreach ($f in @("download_models.py", "bootstrap.py", "models_manifest.json")) {
        Copy-Item (Join-Path $PkgRoot ("installer\" + $f)) (Join-Path $instDest $f) -Force
    }
    $toolsDest = Join-Path $InstallDir "tools"
    New-Item -ItemType Directory -Force -Path $toolsDest | Out-Null
    Copy-Item (Join-Path $PkgRoot "installer\download_models.py") (Join-Path $toolsDest "download_models.py") -Force
    Copy-Item (Join-Path $PkgRoot "installer\models_manifest.json") (Join-Path $toolsDest "models_manifest.json") -Force
    # 备份/恢复/U 盘打包脚本和 7zr 也要装进目标目录，否则根目录的 .bat 会找不到工具。
    $toolsSrc = Join-Path $PkgRoot "tools"
    if (Test-Path $toolsSrc) {
        Get-ChildItem $toolsSrc -Force | ForEach-Object {
            $target = Join-Path $toolsDest $_.Name
            if ($_.PSIsContainer) { Copy-Tree $_.FullName $target }
            else { Copy-Item $_.FullName $target -Force }
        }
    }
    # 版本号、许可证、更新日志和根目录小工具（商业包没有的文件自动跳过）。
    $rootFiles = @(
        "VERSION", "VERSION_LOCK.md", "DISCLAIMER.md", "LICENSE",
        "THIRD_PARTY_NOTICES.md", "README.md", "MANUAL.md", "CHANGELOG.md",
        "EDITIONS.md", "COMMERCIAL_LICENSE.md", "安装说明.txt", "备份数据.bat",
        "恢复数据.bat", "打包到U盘.bat", "运行测试.bat"
    )
    foreach ($name in $rootFiles) {
        $src = Join-Path $PkgRoot $name
        if (Test-Path $src) {
            Copy-Item $src (Join-Path $InstallDir $name) -Force
        }
    }
    $testsSrc = Join-Path $PkgRoot "tests"
    if (Test-Path $testsSrc) {
        Copy-Tree $testsSrc (Join-Path $InstallDir "tests")
    }
}

function Write-ModelBat {
    $text = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
.\python_embeded\python.exe -s tools\download_models.py --root "%~dp0" --manifest tools\models_manifest.json
pause
"@
    Set-Content -Path (Join-Path $InstallDir "模型下载.bat") -Value $text -Encoding ascii
}

function Write-FirewallBat {
    $text = @"
@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  echo Please right-click and Run as administrator.
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="CometInk 8800" >nul 2>&1
netsh advfirewall firewall delete rule name="Nexus 8800" >nul 2>&1
netsh advfirewall firewall delete rule name="ComfyUI Mobile Studio 8800" >nul 2>&1
netsh advfirewall firewall add rule name="CometInk 8800" dir=in action=allow protocol=TCP localport=8800 profile=any
echo Allowed TCP 8800 for LAN access.
pause
"@
    Set-Content -Path (Join-Path $InstallDir "修复手机访问.bat") -Value $text -Encoding ascii
}

function Invoke-Pip($py, $pkgs, $extra = @()) {
    $index = "https://pypi.tuna.tsinghua.edu.cn/simple"
    $common = @("-m", "pip", "install", "--disable-pip-version-check",
                "--no-input", "--prefer-binary", "--timeout", "60",
                "--upgrade-strategy", "only-if-needed")
    & $py @common -i $index @extra @pkgs | Out-Host
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Warn "清华 PyPI 镜像失败，改用官方源重试..."
        & $py @common @extra @pkgs | Out-Host
        $code = $LASTEXITCODE
    }
    return $code
}

function Install-PythonDeps {
    $py = Join-Path $InstallDir "python_embeded\python.exe"
    Say "  检查 Python / pip..."
    & $py -m pip --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $py -m ensurepip --upgrade | Out-Null
    }
    Say "  安装运行依赖（版本锁定）..."
    $rc = Invoke-Pip $py $PythonBase
    if ($rc -ne 0) {
        Fail "基础 Python 依赖安装失败，请检查网络后重试。"
    }
    if ($NoTranslate) {
        Warn "已跳过中文翻译组件；中文提示词需要用户自行翻译成英文。"
        return
    }
    Say "  安装中文翻译组件（版本锁定，argostranslate / MIT 兼容层）..."
    $rc = Invoke-Pip $py @($PythonArgos) @("--no-deps")
    if ($rc -ne 0) {
        Warn "argostranslate 安装失败；网页仍可出图，但中文提示词翻译可能不可用。"
        return
    }
    $rc = Invoke-Pip $py $PythonTranslation
    if ($rc -ne 0) {
        Warn "翻译运行依赖安装失败；中文提示词翻译可能不可用。"
    }
    Install-MiniSBDShim
}

function Install-MiniSBDShim {
    # Argos imports the `minisbd` module. Upstream MiniSBD is AGPL-3.0; this
    # independent MIT shim keeps the import working without that dependency.
    $site = Join-Path $InstallDir "python_embeded\Lib\site-packages"
    $dest = Join-Path $site "minisbd"
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Get-ChildItem $site -Directory -Filter "minisbd-*.dist-info" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Tree (Join-Path $PkgRoot "installer\minisbd_shim\minisbd") $dest
    Copy-Item (Join-Path $PkgRoot "installer\minisbd_shim\LICENSE") `
        (Join-Path $site "minisbd-LICENSE.txt") -Force
    Ok "MiniSBD 兼容层已安装（MIT，非 AGPL）"
}

function Install-ArgosModel {
    $py = Join-Path $InstallDir "python_embeded\python.exe"
    $dest = Join-Path $InstallDir ("_downloads\" + $ArgosModelFile)
    Download-File @(
        ("https://argos-net.com/v1/" + $ArgosModelFile),
        ("https://data.argosopentech.com/argospm/v1/" + $ArgosModelFile)
    ) $dest $ArgosModelSize "中文→英文翻译模型"
    $env:MGS_ARGOS_MODEL = $dest
    try {
        & $py -c "import os; from argostranslate import package; package.install_from_path(os.environ['MGS_ARGOS_MODEL'])"
        if ($LASTEXITCODE -ne 0) { Warn "翻译模型安装失败，可稍后重新运行安装器。" }
        else { Ok "中文翻译模型已安装" }
    } finally {
        Remove-Item Env:MGS_ARGOS_MODEL -ErrorAction SilentlyContinue
    }
}

function Install-NodeZip($name, $urls) {
    $zip = Join-Path $InstallDir ("_downloads\" + $name + ".zip")
    Download-File $urls $zip 1000 ($name + " 插件")
    $tmp = Join-Path $InstallDir ("_bootstrap\node_" + $name)
    Expand-Zip $zip $tmp
    $root = Get-ZipTop $tmp
    $dest = Join-Path $InstallDir ("ComfyUI\custom_nodes\" + $name)
    if (Test-Path $dest) {
        if (-not (Backup-ExistingNode $dest $name)) {
            Warn ("保留现有节点，跳过覆盖：" + $name)
            Add-Conflict ("自定义节点 " + $name + " 正在使用，未覆盖")
            return
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    Move-Item $root $dest
    Ok ($name + " 已安装")
}

function Install-CustomNodes {
    if ($NoCustomNodes) { Warn "已跳过自定义节点安装"; return }
    Say "  安装 UltimateSDUpscale..."
    $u1 = "https://github.com/ssitu/ComfyUI_UltimateSDUpscale/archive/" + $NodeUltimate + ".zip"
    Install-NodeZip "ComfyUI_UltimateSDUpscale" @(
        ("https://gh-proxy.com/" + $u1), $u1
    )
    $subZip = Join-Path $InstallDir "_downloads\ultimate_submodule.zip"
    $u2 = "https://github.com/Coyote-A/ultimate-upscale-for-automatic1111/archive/" + $NodeUltimateSub + ".zip"
    Download-File @(
        ("https://gh-proxy.com/" + $u2), $u2
    ) $subZip 1000 "UltimateSDUpscale 子模块"
    $tmp = Join-Path $InstallDir "_bootstrap\node_ultimate_submodule"
    Expand-Zip $subZip $tmp
    $subRoot = Get-ZipTop $tmp
    $subDest = Join-Path $InstallDir "ComfyUI\custom_nodes\ComfyUI_UltimateSDUpscale\repositories\ultimate_sd_upscale"
    if (Test-Path $subDest) {
        if (-not (Backup-ExistingNode $subDest "ultimate_sd_upscale")) {
            Warn "保留现有 UltimateSDUpscale 子模块，跳过覆盖"
            return
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $subDest) | Out-Null
    Move-Item $subRoot $subDest
    Ok "UltimateSDUpscale 子模块已安装"

    Say "  安装 AlekPet（包含 Argos 翻译节点）..."
    $u3 = "https://github.com/AlekPet/ComfyUI_Custom_Nodes_AlekPet/archive/" + $NodeAlekPet + ".zip"
    Install-NodeZip "ComfyUI_Custom_Nodes_AlekPet" @(
        ("https://gh-proxy.com/" + $u3), $u3
    )
}

function Ensure-ComfyUI {
    $py = Join-Path $InstallDir "python_embeded\python.exe"
    $main = Join-Path $InstallDir "ComfyUI\main.py"
    if ((Test-Path $py) -and (Test-Path $main)) {
        Ok "检测到已有 ComfyUI，保留现有安装"
        if ($CommercialClean) {
            $script:SkipComfyUI = $true
            Warn "商业清洁模式：不自动更新用户现有的 ComfyUI"
        }
        return
    }
    if ($SkipComfyUI) {
        Fail ("未检测到 ComfyUI：" + $InstallDir + "。`n" +
              "商业安装器不会自动下载 ComfyUI；请先安装 ComfyUI，或去掉 -SkipComfyUI，`n" +
              "或用 -ComfyUIDir 指向已有安装目录。")
    }
    if ($CommercialClean -and -not $Yes) {
        $ans = Read-Host "  未检测到 ComfyUI。是否下载官方 ComfyUI 便携版？[Y/n]"
        if ($ans -match '^[nN]') {
            Fail ("已按你的选择不安装 ComfyUI。请先自行安装 ComfyUI，或重新运行并选择下载。")
        }
    }
    if (Test-Path $InstallDir) {
        $items = @(Get-InstallDirUserItems $InstallDir)
        if ($items.Count -gt 0) {
            Fail ("安装目录不是空的，而且不像 ComfyUI 安装：" + $InstallDir)
        }
    }
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $archive = Join-Path $InstallDir "_downloads\ComfyUI_portable.7z"
    if ($ComfyZip) {
        if (-not (Test-Path $ComfyZip)) {
            Fail ("-ComfyZip 指定的文件不存在：" + $ComfyZip)
        }
        Say ("  使用本地 ComfyUI 便携版：" + $ComfyZip)
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $archive) | Out-Null
        Copy-Item -LiteralPath $ComfyZip -Destination $archive -Force
    } else {
        Say "  官方下载源在部分网络下可能较慢；"
        Say "  可以先用浏览器/下载工具下好 7z，再用 -ComfyZip 指定，或放到："
        Say ("    " + $archive) "DarkGray"
        Download-File @($ComfyProxy, $ComfyAsset) $archive 1500000000 "ComfyUI 便携版（约 2GB）"
    }
    if ((Get-Item $archive).Length -ne $ComfySize) {
        Warn ("ComfyUI 包大小和预期不同：" + (Get-Item $archive).Length + " / " + $ComfySize)
    }
    Say "  校验 7z 压缩包..."
    & $SevenZip t $archive | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $archive -Force
        Fail "ComfyUI 压缩包损坏，已删除；请重新运行安装器。"
    }
    $stage = Join-Path $InstallDir "_bootstrap\comfy_extract"
    Expand-7z $archive $stage
    $pyItem = Get-ChildItem $stage -Recurse -Filter python.exe |
        Where-Object { $_.FullName -match 'python_embeded\\python\.exe$' } |
        Select-Object -First 1
    if (-not $pyItem) { Fail "解压后找不到 python_embeded\python.exe" }
    $portableRoot = Split-Path (Split-Path $pyItem.FullName -Parent) -Parent
    if (-not (Test-Path (Join-Path $portableRoot "ComfyUI\main.py"))) {
        Fail "解压后的目录结构不认识：找不到 ComfyUI\main.py"
    }
    Say "  移动到安装目录..."
    Get-ChildItem $portableRoot -Force | ForEach-Object {
        $dest = Join-Path $InstallDir $_.Name
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Move-Item $_.FullName $dest
    }
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    $script:ComfyWasFresh = $true
    Ok "ComfyUI 便携版已解压"
}

function Verify-ComfyUI {
    $py = Join-Path $InstallDir "python_embeded\python.exe"
    $comfy = Join-Path $InstallDir "ComfyUI"
    try {
        $ver = (& $py -c "import sys; sys.path.insert(0, r'$comfy'); import comfyui_version; print(comfyui_version.__version__)" 2>$null | Select-Object -First 1)
        if ($ver) { $ver = $ver.Trim() }
        if ($ver -eq $ComfyVersion) {
            Ok ("ComfyUI 版本锁定: " + $ComfyVersion)
        } else {
            Warn ("ComfyUI 版本不是锁定值：当前 " + $ver + " / 锁定 " + $ComfyVersion)
            Add-Conflict ("现有 ComfyUI 版本 " + $ver + "，锁定版本 " + $ComfyVersion)
            if ($script:Dialogs) {
                $cont = Show-Gui (
                    "检测到现有 ComfyUI 版本与安装包锁定版本不同：`n`n" +
                    "现有：" + $ver + "`n锁定：" + $ComfyVersion + "`n`n" +
                    "安装器不会自动升级。继续使用现有版本，部分新节点或工作流" +
                    "可能不兼容。`n`n是否继续安装？") "ComfyUI 版本不一致" "YesNo" "Warning"
                if ($cont -ne "Yes") {
                    throw "用户取消安装：ComfyUI 版本与锁定版本不一致。"
                }
            } else {
                Warn "安装器不会自动升级；如需升级请显式加 -AllowUpdates"
            }
        }
    } catch {
        Warn "无法读取 ComfyUI 版本；保持现有安装"
    }
}

function Update-ComfyUI($fresh) {
    $py = Join-Path $InstallDir "python_embeded\python.exe"
    $comfy = Join-Path $InstallDir "ComfyUI"
    $zip = Join-Path $InstallDir "_downloads\ComfyUI_master.zip"
    Say "  下载最新 ComfyUI 源码（便携包自带版本较旧，Anima 需要新节点）..."
    Download-File @(
        "https://gh-proxy.com/https://github.com/Comfy-Org/ComfyUI/archive/refs/heads/master.zip",
        "https://github.com/Comfy-Org/ComfyUI/archive/refs/heads/master.zip"
    ) $zip 1000000 "最新 ComfyUI 源码"
    $tmp = Join-Path $InstallDir "_bootstrap\comfy_master"
    Expand-Zip $zip $tmp
    $src = Get-ZipTop $tmp
    if ($fresh) {
        if (Test-Path $comfy) { Remove-Item $comfy -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $comfy | Out-Null
    }
    Say "  合并最新 ComfyUI 代码（保留已有模型和插件）..."
    Copy-Tree $src $comfy
    foreach ($d in @("checkpoints", "diffusion_models", "text_encoders", "vae",
                     "loras", "upscale_models", "clip", "unet", "clip_vision",
                     "embeddings", "controlnet", "animatediff_models",
                     "animatediff_motion_lora")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $comfy ("models\" + $d)) | Out-Null
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $comfy "custom_nodes") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $comfy "input") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $comfy "output") | Out-Null
    $req = Join-Path $comfy "requirements.txt"
    if (Test-Path $req) {
        Say "  安装 ComfyUI 最新依赖（可能需要几分钟）..."
        $rc = Invoke-Pip $py @("-r", $req)
        if ($rc -ne 0) {
            Warn "ComfyUI 依赖安装没有完全成功；启动时可能还会自动补装。"
        }
    }
    try {
        $ver = & $py -c "import sys; sys.path.insert(0, r'$comfy'); import comfyui_version; print(comfyui_version.__version__)"
        if ($LASTEXITCODE -eq 0) { Ok ("ComfyUI 版本: " + $ver) }
    } catch { }
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

function Install-Models {
    if ($SkipModels) { Warn "已按参数跳过模型下载"; return }
    $py = Join-Path $InstallDir "python_embeded\python.exe"
    $script = Join-Path $InstallDir "installer\download_models.py"
    $manifest = Join-Path $InstallDir "installer\models_manifest.json"
    Say "  默认会下载 Anima 2B + 放大模型（约 6GB）。"
    Say "  也可以稍后双击「模型下载.bat」补装。"
    $pargs = @($script, "--root", $InstallDir, "--manifest", $manifest)
    if ($ModelPacks) {
        $pargs += @("--packs", $ModelPacks)
    } elseif ($Yes) {
        $m = Get-Content $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
        $pargs += @("--packs", (($m.default_packs) -join ","))
    }
    & $py @pargs
    if ($LASTEXITCODE -ne 0) {
        Warn "模型下载没有全部完成；可以双击「模型下载.bat」断点续传。"
    }
}

function Set-AdminPassword {
    $py = Join-Path $InstallDir "python_embeded\python.exe"
    $existing = Join-Path $InstallDir "users.json"
    $pw = $env:MGS_ADMIN_PASSWORD
    $preserve = $false
    if ($pw) {
        $preserve = $false
    } elseif ((Test-Path $existing) -and $Upgrade) {
        Say "  检测到已有账号，保留原管理员密码。"
        $preserve = $true
    } elseif ($Yes) {
        $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
        $rnd = New-Object System.Random
        $pw = -join (1..16 | ForEach-Object { $chars[$rnd.Next(0, $chars.Length)] })
        Say ("  未提供密码，已生成随机管理员密码：" + $pw) "Yellow"
        Say "  请现在记下来，登录后可以在「安全设置」里修改。" "Yellow"
    } else {
        while ($true) {
            $s1 = Read-Host "  设置管理员密码（至少 8 位）" -AsSecureString
            $b1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1)
            try { $pw = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b1) }
            finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b1) }
            if ($pw.Length -lt 8) { Warn "密码太短，至少 8 位"; continue }
            $s2 = Read-Host "  再输一次" -AsSecureString
            $b2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2)
            try { $pw2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b2) }
            finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b2) }
            if ($pw -ne $pw2) { Warn "两次输入不一致"; continue }
            break
        }
    }
    if ($preserve) {
        & $py (Join-Path $InstallDir "installer\bootstrap.py") --root $InstallDir
        if ($LASTEXITCODE -ne 0) { Fail "检查/续期 HTTPS 证书失败" }
        return
    }
    $env:MGS_ADMIN_PASSWORD = $pw
    try {
        & $py (Join-Path $InstallDir "installer\bootstrap.py") --root $InstallDir
        if ($LASTEXITCODE -ne 0) { Fail "初始化管理员/证书失败" }
    } finally {
        Remove-Item Env:MGS_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    }
}

function Add-FirewallRule {
    if (Test-Admin) {
        & netsh advfirewall firewall delete rule name="CometInk 8800" | Out-Null
        & netsh advfirewall firewall delete rule name="Nexus 8800" | Out-Null
        & netsh advfirewall firewall delete rule name="ComfyUI Mobile Studio 8800" | Out-Null
        & netsh advfirewall firewall add rule name="CometInk 8800" dir=in action=allow protocol=TCP localport=8800 profile=any | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok "已放行 TCP 8800（手机访问）" }
        else { Warn "防火墙规则添加失败，可运行「修复手机访问.bat」" }
    } else {
        Warn "当前不是管理员，未自动添加防火墙规则。若手机打不开，右键「修复手机访问.bat」以管理员运行。"
    }
}

function Create-Shortcut {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $ws = New-Object -ComObject WScript.Shell
        $targetPath = Join-Path $InstallDir "一键启动.bat"
        # 桌面上可能已有 Winstep Nexus 等第三方快捷方式，
        # 只更新指向当前安装的快捷方式，绝不覆盖别人的程序。
        $shortcutName = ""
        for ($i = 1; $i -le 9; $i++) {
            $name = "CometInk Studio.lnk"
            if ($i -gt 1) { $name = "CometInk Studio ($i).lnk" }
            $candidate = Join-Path $desktop $name
            if (-not (Test-Path $candidate)) {
                $shortcutName = $name
                break
            }
            $same = $false
            try {
                $old = $ws.CreateShortcut($candidate)
                if ($old.TargetPath) {
                    $same = ([IO.Path]::GetFullPath($old.TargetPath) -ieq
                             [IO.Path]::GetFullPath($targetPath))
                }
            } catch { }
            if ($same) {
                $shortcutName = $name
                break
            }
            if ($i -eq 9) {
                $shortcutName = "CometInk Studio " + (Get-Date -Format "HHmmss") + ".lnk"
            }
        }
        if (-not $shortcutName) {
            $shortcutName = "CometInk Studio " + (Get-Date -Format "HHmmss") + ".lnk"
        }
        $lnk = $ws.CreateShortcut((Join-Path $desktop $shortcutName))
        $lnk.TargetPath = $targetPath
        $lnk.WorkingDirectory = $InstallDir
        $icon = Join-Path $InstallDir "cometink.ico"
        if (-not (Test-Path $icon)) { $icon = Join-Path $InstallDir "comfyui.ico" }
        if (Test-Path $icon) { $lnk.IconLocation = $icon }
        $lnk.Save()
        # 迁移旧品牌快捷方式：只删除指向当前安装的那个，
        # Winstep Nexus 等第三方快捷方式原样保留。
        $legacy = Join-Path $desktop "Nexus Studio.lnk"
        if (Test-Path $legacy) {
            try {
                $old = $ws.CreateShortcut($legacy)
                if ($old.TargetPath -and ([IO.Path]::GetFullPath($old.TargetPath) -ieq [IO.Path]::GetFullPath($targetPath))) {
                    Remove-Item $legacy -Force
                }
            } catch { }
        }
        Ok ("桌面快捷方式：" + $shortcutName.Replace(".lnk", ""))
    } catch { Warn ("创建桌面快捷方式失败：" + $_.Exception.Message) }
}

function Write-Report {
    $lines = @()
    $lines += "CometInk 安装报告"
    $lines += ("时间: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    $lines += ("安装目录: " + $InstallDir)
    $lines += ("GPU: " + $GpuText)
    $lines += ("版本锁: ComfyUI " + $ComfyVersion)
    $lines += ("模型包: " + $(if ($SkipModels) { "跳过" } elseif ($ModelPacks) { $ModelPacks } else { "交互选择/默认" }))
    $lines += ("中文翻译组件: " + $(if ($NoTranslate) { "跳过（用户自行准备英文提示词）" } else { "已安装" }))
    $lines += ("自定义节点: " + $(if ($NoCustomNodes) { "跳过" } else { "已安装" }))
    $lines += ("ComfyUI 来源: " + $(if ($SkipComfyUI) { "用户现有安装，未自动更新" } else { "安装器下载/更新" }))
    $lines += ("商业清洁模式: " + $(if ($CommercialClean) { "是" } else { "否" }))
    $lines += ("免责声明: 已接受（版本 " + $DisclaimerVersion + "；" +
               $script:DisclaimerAcceptedAt + "；" + $script:DisclaimerMode + "）")
    $lines += ("管理员账号: admin")
    $lines += ("本机地址: https://127.0.0.1:8800")
    $lines += ("手机地址: https://192.168.137.1:8800（连接电脑热点后）")
    $lines += ""
    $lines += "自动适配:"
    if ($script:Adaptations.Count -eq 0) {
        $lines += "  （无）"
    } else {
        foreach ($x in $script:Adaptations) { $lines += ("  - " + $x) }
    }
    $lines += "环境冲突:"
    if ($script:Conflicts.Count -eq 0) {
        $lines += "  （无）"
    } else {
        foreach ($x in $script:Conflicts) { $lines += ("  - " + $x) }
    }
    $lines += "注意：本报告不包含密码。"
    Set-Content -Path (Join-Path $InstallDir "install_report.txt") -Value $lines -Encoding utf8
}

# ------------------------------------------------------------------ main
try {
    Start-Transcript -Path $LogFile -Force | Out-Null
} catch { }

try {
    Clear-PythonEnv
    Step "1" "环境检测"
    $script:StageName = "环境检测"
    if (-not [Environment]::Is64BitOperatingSystem) { Fail "只支持 64 位 Windows。" }
    $osv = [Environment]::OSVersion.Version
    if ($osv.Major -lt 10) { Fail "需要 Windows 10 或 Windows 11。" }
    if (-not (Test-Path $Curl)) { Fail "找不到 Windows 自带的 curl.exe。" }
    if (-not (Test-Path $SevenZip)) { Fail ("安装包缺少 7zr.exe：" + $SevenZip) }
    $sevenHash = (Get-FileHash $SevenZip -Algorithm SHA256).Hash
    if ($LockSevenZipHash -and $sevenHash -ne $LockSevenZipHash.ToUpper()) {
        Fail "7zr.exe 校验失败，安装包可能被篡改或不完整。"
    }
    $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
    $gpu = $gpus | Where-Object { $_.Name -match "NVIDIA" } | Select-Object -First 1
    if (-not $gpu) { $gpu = $gpus | Select-Object -First 1 }
    $GpuText = if ($gpu) { $gpu.Name } else { "未检测到显卡" }
    Say ("  系统: Windows " + $osv.Major + "." + $osv.Minor + " 64-bit")
    Say ("  显卡: " + $GpuText)
    if (-not ($gpu -and $gpu.Name -match "NVIDIA")) {
        Warn "没有检测到 NVIDIA 显卡；可以安装，但 CPU 出图会非常慢。"
    }
    if (-not $InstallDir) {
        if (Test-Path "D:\") { $InstallDir = "D:\AI\ComfyUI_windows_portable" }
        else { $InstallDir = Join-Path $env:LOCALAPPDATA "ComfyUI_windows_portable" }
        if (-not $Yes) {
            $typed = Read-Host ("  安装目录 [" + $InstallDir + "]")
            if ($typed) { $InstallDir = $typed }
        }
    }
    $InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    if ($InstallDir -match '^[A-Za-z]:$') {
        Fail ("不能直接安装到盘符根目录：" + $InstallDir +
              "`n请使用子目录，例如 D:\AI\ComfyUI_windows_portable。")
    }

    # 路径本身也可能和便携 Python / 自定义节点冲突
    if ($InstallDir -match '^\\\\') {
        Fail ("不支持 UNC 网络路径：" + $InstallDir +
              "`n请安装到本机磁盘（例如 D:\AI\ComfyUI_windows_portable）。")
    }
    if ($InstallDir -match '[^\x00-\x7F]') {
        Warn "安装目录包含中文或其他非 ASCII 字符；少数自定义节点可能无法读取。"
        Add-Conflict "安装目录包含非 ASCII 字符：$InstallDir"
    }
    if ($InstallDir.Length -gt 180) {
        Warn "安装路径较长，Windows 可能无法处理部分深层文件。"
        Add-Conflict "安装路径较长（$($InstallDir.Length) 字符）"
    }
    if ($InstallDir -match '(?i)^[A-Z]:\\(Windows|Program Files)') {
        Warn "不建议安装到 Windows 或 Program Files；权限和杀毒软件容易拦截。"
        Add-Conflict "安装目录位于系统目录：$InstallDir"
    }

    $Upgrade = $false
    $hasComfy = Test-Path (Join-Path $InstallDir "ComfyUI\main.py")
    $hasPy = Test-Path (Join-Path $InstallDir "python_embeded\python.exe")
    if ($hasComfy -and $hasPy) {
        $Upgrade = $true
        Say ("  检测到已有安装：" + $InstallDir) "Yellow"
        if (-not $Yes) {
            $ans = Read-Host "  继续升级并保留模型/账号？[Y/n]"
            if ($ans -match "^[nN]") { Say "已取消"; exit 0 }
        }
        $pyPath = Join-Path $InstallDir "python_embeded\python.exe"
        $pyCheck = ""
        try {
            $pyCheck = (& $pyPath -c "import sys; print('PYOK', sys.version_info[0], sys.version_info[1])" | Out-String)
        } catch {
            Fail ("安装目录里的便携 Python 无法运行：" + $_.Exception.Message +
                  "`n可能被杀毒软件隔离或文件损坏。" +
                  "`n请先把 python_embeded 改名备份，再重新运行安装器；" +
                  "或换一个目录安装。")
        }
        if ($LASTEXITCODE -ne 0 -or $pyCheck -notmatch 'PYOK') {
            Fail ("安装目录里的便携 Python 无法运行。可能被杀毒软件隔离或文件损坏。" +
                  "`n请先把 python_embeded 改名备份，再重新运行安装器；" +
                  "或换一个目录安装。")
        }
    } elseif ($hasComfy -and -not $hasPy) {
        $InstallDir = Resolve-DirectoryConflict (
            "检测到已有 ComfyUI，但没有便携 Python（python_embeded）。`n" +
            "直接合并可能破坏现有环境。")
        $hasComfy = Test-Path (Join-Path $InstallDir "ComfyUI\main.py")
        $hasPy = Test-Path (Join-Path $InstallDir "python_embeded\python.exe")
        if ($hasComfy -and $hasPy) { $Upgrade = $true }
    } elseif (Test-Path $InstallDir) {
        $items = @(Get-InstallDirUserItems $InstallDir)
        if ($items.Count -gt 0) {
            $InstallDir = Resolve-DirectoryConflict (
                "安装目录不是空的，而且不像本程序的完整安装：`n" + $InstallDir)
        }
    }

    if (-not (Test-WritableDir $InstallDir)) {
        if ($Upgrade) {
            Fail ("无法写入现有安装目录：`n" + $InstallDir +
                  "`n请以管理员身份运行，或关闭杀毒软件的文件夹保护后重试。")
        }
        $InstallDir = Resolve-DirectoryConflict (
            "无法写入安装目录：`n" + $InstallDir +
            "`n常见原因：权限不足、杀毒软件/受控文件夹访问、目录只读。")
        if (-not (Test-WritableDir $InstallDir)) {
            Fail ("新目录仍然无法写入：" + $InstallDir)
        }
    }

    $drive = Split-Path -Qualifier $InstallDir
    $freeGB = 0
    try { $freeGB = [math]::Round((Get-PSDrive $drive.TrimEnd(":")).Free / 1GB, 1) } catch { }
    if ($freeGB -gt 0 -and $freeGB -lt 8) {
        Fail ("安装盘剩余空间不足（" + $freeGB + "GB），至少需要 8GB 安装 ComfyUI 和运行依赖。")
    }
    if ($freeGB -gt 0 -and $freeGB -lt 20 -and -not $SkipModels) {
        $msg = "安装盘剩余 $freeGB GB。完整安装（含默认模型）建议至少 20GB。`n`n是否继续安装但不下载模型？"
        $skip = $false
        if ($script:Dialogs) {
            $skip = (Show-Gui $msg "磁盘空间不足" "YesNo" "Warning") -eq "Yes"
        } elseif ($Yes -or $NoDialog) {
            $skip = $true
            Warn $msg
        } else {
            $skip = Use-ConsoleChoice $msg
        }
        if (-not $skip) { Fail "磁盘空间不足，已取消安装。" }
        $SkipModels = $true
        Add-Adaptation "磁盘空间不足，本次安装跳过模型下载"
    }
    Say ("  安装目录: " + $InstallDir)
    Say ("  可用空间: " + $freeGB + " GB")
    $admin = Test-Admin
    Say ("  管理员权限: " + $(if ($admin) { "是" } else { "否（防火墙规则需手动修复）" }))

    # 在停止任何旧服务、写文件或下载之前完成首次安装免责协议确认。
    # DryRun 不修改系统，Confirm-Disclaimer 会直接跳过。
    Confirm-Disclaimer $InstallDir

    # 端口/进程冲突：本项目的旧服务会询问后停止；外部程序占用则说明后果。
    # DryRun 只报告，绝不停止任何正在运行的服务。
    if ($DryRun) {
        foreach ($port in @(8188, 8800)) {
            $o = Get-PortOwner $port
            if ($o) {
                Add-Conflict ("端口 " + $port + " 被 " + $o.Name +
                              "（PID " + $o.Pid + "）占用")
            }
        }
    } else {
        # 先停守护进程和它拉起的服务，再检查端口，避免守护进程又把它拉起来
        Resolve-TargetProcesses
        Resolve-PortConflicts
    }

    Step "2" "网络与下载源检测"
    $script:StageName = "网络与下载源检测"
    $netComfy = Test-Url $ComfyProxy
    $netHf = Test-Url ($HfMirror + "/circlestone-labs/Anima")
    if ($netComfy) { Ok "ComfyUI 下载源可用（gh-proxy）" } else { Warn "gh-proxy 不可用，将尝试 GitHub 直连" }
    if ($netHf) { Ok "模型镜像可用（hf-mirror）" } else { Warn "hf-mirror 不可用，将尝试 Hugging Face 直连" }
    if ($DryRun) {
        Say ""
        Say ("  版本锁定: ComfyUI " + $ComfyTag + "；依赖/节点/模型 revision 已锁定") "Cyan"
        if ($SkipModels) {
            if ($CommercialClean) {
                Say "  已跳过模型包检查（商业清洁模式）" "Cyan"
            } else {
                Say "  已跳过模型包检查（-SkipModels）" "Cyan"
            }
        } else {
            Say "  模型包 URL 检查：" "Cyan"
            $m = Get-Content $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($key in $m.packs.PSObject.Properties.Name) {
                $pack = $m.packs.$key
                $f = $pack.files | Select-Object -First 1
                $rev = if ($f.revision) { $f.revision } else { "main" }
                $u = $HfMirror + "/" + $f.repo + "/resolve/" + $rev + "/" + $f.path + "?download=true"
                $ok = Test-Url $u
                Say ("    " + $(if ($ok) { "OK  " } else { "FAIL" }) + " " + $key + "  " + $pack.label) $(if ($ok) { "Green" } else { "Red" })
            }
        }
        if ($NoCustomNodes) {
            Say "  已跳过自定义节点检查（商业清洁模式）" "Cyan"
        } else {
            $nodeOk = Test-Url "https://gh-proxy.com/https://github.com/AlekPet/ComfyUI_Custom_Nodes_AlekPet/archive/refs/heads/master.zip"
            Say ("    " + $(if ($nodeOk) { "OK  " } else { "FAIL" }) + " 自定义节点 ZIP")
        }
        Say ""
        Ok "DryRun 环境检测完成；没有下载或修改任何文件。"
        try { Stop-Transcript | Out-Null } catch { }
        exit 0
    }

    Step "3" "准备目录"
    $script:StageName = "准备目录"
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Ok "目录已准备"

    Step "4" "获取 ComfyUI 便携版"
    $script:StageName = "获取 ComfyUI 便携版"
    Ensure-ComfyUI
    if ($SkipComfyUI) {
        Warn "已跳过 ComfyUI 更新（使用用户现有安装）"
    } elseif ($AllowUpdates) {
        Warn "已启用 -AllowUpdates：可能脱离版本锁定"
        Update-ComfyUI $ComfyWasFresh
    } else {
        # 自己解压出来、但版本低于最低兼容线的便携包（例如国内镜像里的旧版）
        # 直接自动更新源码，避免装完才发现节点缺失。
        $ver = ""
        try {
            $py = Join-Path $InstallDir "python_embeded\python.exe"
            $comfy = Join-Path $InstallDir "ComfyUI"
            $ver = (& $py -c "import sys; sys.path.insert(0, r'$comfy'); import comfyui_version; print(comfyui_version.__version__)" 2>$null | Select-Object -First 1)
            if ($ver) { $ver = $ver.Trim() }
        } catch { }
        $tooOld = $false
        if ($ComfyWasFresh -and $ver) {
            try { $tooOld = ([version]$ver -lt [version]$ComfyMin) } catch { }
        }
        if ($tooOld) {
            Warn ("便携版 ComfyUI 较旧（" + $ver + " < " + $ComfyMin + "），自动更新源码...")
            Update-ComfyUI $true
        } else {
            Verify-ComfyUI
        }
    }

    Step "5" "安装网页程序与 Python 依赖"
    $script:StageName = "安装网页程序与 Python 依赖"
    Copy-AppFiles
    Install-PythonDeps
    if (-not $NoTranslate) { Install-ArgosModel }

    Step "6" "安装必要自定义节点"
    $script:StageName = "安装必要自定义节点"
    Install-CustomNodes

    Step "7" "下载模型（不随安装包分发）"
    $script:StageName = "下载模型"
    Install-Models

    Step "8" "初始化账号、HTTPS 证书和自启动入口"
    $script:StageName = "初始化账号、HTTPS 证书和自启动入口"
    Set-AdminPassword
    Add-FirewallRule
    if (-not $NoShortcut) { Create-Shortcut }
    Write-ModelBat
    Write-FirewallBat
    Write-Report

    # 清理临时下载：模型已经放到 ComfyUI/models，保留 installer 供以后补模型
    Remove-Item (Join-Path $InstallDir "_bootstrap") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $InstallDir "_downloads") -Recurse -Force -ErrorAction SilentlyContinue

    Step "完成" "安装成功"
    Say ""
    Say ("  安装目录：" + $InstallDir)
    if ($NoShortcut) {
        Say ("  启动方式：安装目录里的 一键启动.bat")
    } else {
        Say ("  桌面快捷方式：CometInk Studio")
    }
    Say ("  本机打开：https://127.0.0.1:8800")
    Say ("  手机打开：https://192.168.137.1:8800（先连电脑热点）")
    Say "  管理员账号：admin（密码是你刚才设置的）"
    Say ("  免责声明：已阅读并同意（" + $script:DisclaimerMode + "）") "Green"
    Say ""
    if ($NoShortcut) {
        Say "  下一步：双击安装目录里的「一键启动.bat」，等待启动完成后用浏览器打开。" "Green"
    } else {
        Say "  下一步：双击桌面的「CometInk Studio」，等待启动完成后用浏览器打开。" "Green"
    }
    Say ""
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
} catch {
    $err = $_.Exception.Message
    Warn ("安装失败：" + $err)
    Say ("  日志：" + $LogFile) "Yellow"
    try { Stop-Transcript | Out-Null } catch { }
    if ($err -match "用户取消安装") {
        Say "已取消安装，没有修改 ComfyUI 或模型。" "Yellow"
    } else {
        try { Show-ProblemDialog $err } catch { Warn ("无法显示问题框：" + $_.Exception.Message) }
    }
    exit 1
}
