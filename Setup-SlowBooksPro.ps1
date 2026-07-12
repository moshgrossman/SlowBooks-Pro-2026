# ============================================================================
# Slowbooks Pro 2026 -- Windows Setup
#
# Installs everything Slowbooks Pro needs on a bare Windows machine and
# launches it. Fetched and re-run each time by "Setup SlowBooks Pro.bat" --
# keep this file as the one place that changes; the .bat stays stable.
#
# Every step below checks "is this already done?" before doing anything, so
# this script is always safe to run again (after a required restart, after
# fixing something manually, or just to relaunch).
#
# Docker choice: Docker Engine is installed *inside* a WSL2 Linux distro,
# not Docker Desktop. This avoids Docker Desktop's background GUI/tray
# process, its Windows<->WSL2 networking shim, and its slow first-launch
# time -- container performance itself is identical either way since both
# ultimately run on the same WSL2 Linux kernel.
#
# All WSL-side commands run as root (-u root). This is deliberate: a fresh
# WSL distro normally prompts interactively for a default Unix username on
# first launch, which would stall unattended setup. Root always exists
# without that prompt, and nothing here needs a non-root user.
# ============================================================================

$ErrorActionPreference = 'Stop'

$RepoOwner    = 'moshgrossman'
$RepoName     = 'SlowBooks-Pro-2026'
$RepoBranch   = 'main'
$InstallRoot  = Join-Path $env:LOCALAPPDATA 'SlowBooksPro'
$AppDir       = Join-Path $InstallRoot 'app'
$WslDistro    = 'Ubuntu'
$WslAppDirPosix = '/root/slowbooks-pro'
$WslAppDirUnc   = "\\wsl.localhost\$WslDistro\root\slowbooks-pro"

function Write-Step { param([string]$Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Info { param([string]$Message) Write-Host "    $Message" }

function Write-ErrExit {
    param([string]$Message)
    Write-Host "`n$Message" -ForegroundColor Red
    Write-Host "`nPress Enter to close this window..."
    Read-Host | Out-Null
    exit 1
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-WslRoot {
    # Runs a command as root inside the target WSL distro. Returns the
    # process exit code via $LASTEXITCODE (standard for external commands).
    param([string]$Command)
    wsl.exe -d $WslDistro -u root -- bash -lc $Command
}

# ---------------------------------------------------------------------------
# Step 0: fetch the app source itself (plain HTTPS ZIP -- no git required)
# ---------------------------------------------------------------------------
function Get-AppSource {
    Write-Step 'Checking Slowbooks Pro application files...'
    $marker = Join-Path $AppDir 'desktop_launcher.py'
    if (Test-Path $marker) {
        Write-Info "Already present at $AppDir"
        return
    }

    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $zipUrl  = "https://github.com/$RepoOwner/$RepoName/archive/refs/heads/$RepoBranch.zip"
    $zipPath = Join-Path $InstallRoot 'source.zip'

    Write-Info 'Downloading application files...'
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    } catch {
        Write-ErrExit "Could not download Slowbooks Pro from:`n  $zipUrl`n`nCheck your internet connection and run 'Setup SlowBooks Pro.bat' again.`nIf this keeps happening, download it manually from:`n  https://github.com/$RepoOwner/$RepoName"
    }

    Write-Info 'Extracting...'
    $extractTmp = Join-Path $InstallRoot 'source-extract'
    if (Test-Path $extractTmp) { Remove-Item -Recurse -Force $extractTmp }
    Expand-Archive -Path $zipPath -DestinationPath $extractTmp -Force

    $extractedFolder = Get-ChildItem -Path $extractTmp -Directory | Select-Object -First 1
    if (-not $extractedFolder) {
        Write-ErrExit "The downloaded application archive looked empty. Please run 'Setup SlowBooks Pro.bat' again."
    }
    Move-Item -Path $extractedFolder.FullName -Destination $AppDir -Force

    Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $extractTmp -ErrorAction SilentlyContinue
    Write-Info 'Done.'
}

# ---------------------------------------------------------------------------
# Step 1: Python (runs desktop_launcher.py and its native window on Windows)
# ---------------------------------------------------------------------------
function Get-Python {
    Write-Step 'Checking Python...'
    if (Test-CommandExists 'python') {
        Write-Info "Found: $(& python --version 2>&1)"
        return
    }

    Write-Info 'Python not found. Installing...'
    $installed = $false

    if (Test-CommandExists 'winget') {
        Write-Info 'Trying winget (Option 1 of 2)...'
        try {
            winget install --id Python.Python.3.13 -e --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) { $installed = $true }
        } catch {
            Write-Info "winget install failed: $($_.Exception.Message)"
        }
    }

    if (-not $installed) {
        Write-Info 'Trying a direct download from python.org (Option 2 of 2)...'
        try {
            $pyUrl = 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe'
            $pyInstaller = Join-Path $env:TEMP 'slowbooks-python-installer.exe'
            Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
            Start-Process -FilePath $pyInstaller -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1' -Wait
            Remove-Item -Force $pyInstaller -ErrorAction SilentlyContinue
            $installed = $true
        } catch {
            Write-Info "Direct download failed: $($_.Exception.Message)"
        }
    }

    # Refresh PATH in this session so a just-installed python.exe is found
    # without needing to close and reopen the window.
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')

    if (-not (Test-CommandExists 'python')) {
        Write-ErrExit "Python could not be installed automatically.`n`nPlease download and install it yourself from:`n  https://www.python.org/downloads/`n(Be sure to check 'Add python.exe to PATH' during install.)`n`nThen run 'Setup SlowBooks Pro.bat' again."
    }
    Write-Info 'Python installed.'
}

# ---------------------------------------------------------------------------
# Step 2: WSL2 + a Linux distro
# ---------------------------------------------------------------------------
function Test-RebootPending {
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { return $true }
    }
    return $false
}

function Get-Wsl2 {
    Write-Step 'Checking WSL2...'

    $build = [System.Environment]::OSVersion.Version.Build
    if ($build -lt 19041) {
        Write-ErrExit "Your Windows version (build $build) is too old for automatic WSL2 setup (build 19041+ needed).`n`nPlease follow Microsoft's manual WSL install guide:`n  https://learn.microsoft.com/windows/wsl/install-manual`n`nThen run 'Setup SlowBooks Pro.bat' again."
    }

    $wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
    $vmFeature  = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform

    if ($wslFeature.State -ne 'Enabled' -or $vmFeature.State -ne 'Enabled') {
        Write-Info 'Enabling required Windows features (this can take a minute)...'
        if ($wslFeature.State -ne 'Enabled') {
            Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All -NoRestart | Out-Null
        }
        if ($vmFeature.State -ne 'Enabled') {
            Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart | Out-Null
        }

        # Never restart automatically -- always ask first.
        if (Test-RebootPending) {
            Write-ErrExit "A restart is required to finish enabling WSL2.`n`nPlease restart your computer, then double-click 'Setup SlowBooks Pro.bat' again -- it will continue automatically from here."
        }
    }

    wsl.exe --set-default-version 2 | Out-Null

    $existingDistros = (wsl.exe -l -q 2>$null) -replace "`0", '' -split "`r?`n" | ForEach-Object { $_.Trim() }
    if ($existingDistros -notcontains $WslDistro) {
        Write-Info "Installing the $WslDistro Linux environment (this can take a few minutes)..."
        try {
            wsl.exe --install -d $WslDistro --no-launch
        } catch {
            Write-ErrExit "Could not install the Linux environment automatically.`n`nPlease follow Microsoft's manual WSL install guide:`n  https://learn.microsoft.com/windows/wsl/install-manual`n`nThen run 'Setup SlowBooks Pro.bat' again."
        }
        if (Test-RebootPending) {
            Write-ErrExit "A restart is required to finish setting up WSL2.`n`nPlease restart your computer, then double-click 'Setup SlowBooks Pro.bat' again."
        }
    }

    # Give a freshly-installed distro a moment to finish initializing.
    $ready = $false
    for ($i = 0; $i -lt 10; $i++) {
        Invoke-WslRoot 'echo ready' | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 3
    }
    if (-not $ready) {
        Write-ErrExit "The $WslDistro Linux environment did not come up in time.`n`nPlease run 'Setup SlowBooks Pro.bat' again. If this keeps happening, restart your computer first."
    }

    Write-Info "WSL2 with $WslDistro is ready."
}

# ---------------------------------------------------------------------------
# Step 3: Docker Engine inside WSL2 (no Docker Desktop)
# ---------------------------------------------------------------------------
function Get-DockerEngine {
    Write-Step "Checking Docker Engine inside $WslDistro..."

    Invoke-WslRoot 'docker --version' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Info 'Docker not found. Installing (this can take a few minutes)...'

        Write-Info "Trying Docker's official install script (Option 1 of 2)..."
        Invoke-WslRoot 'curl -fsSL https://get.docker.com | sh' | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Info 'Retrying once...'
            Start-Sleep -Seconds 5
            Invoke-WslRoot 'curl -fsSL https://get.docker.com | sh' | Out-Null
        }

        if ($LASTEXITCODE -ne 0) {
            Write-Info 'Trying the distro package instead (Option 2 of 2)...'
            Invoke-WslRoot 'apt-get update && apt-get install -y docker.io' | Out-Null
        }

        Invoke-WslRoot 'docker --version' | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-ErrExit "Docker Engine could not be installed automatically inside WSL2.`n`nPlease follow the manual install guide:`n  https://docs.docker.com/engine/install/ubuntu/`n`nThen run 'Setup SlowBooks Pro.bat' again."
        }
    }

    Write-Info 'Making Docker start automatically...'
    Invoke-WslRoot "grep -q '^\[boot\]' /etc/wsl.conf 2>/dev/null || printf '\n[boot]\nsystemd=true\n' >> /etc/wsl.conf" | Out-Null

    Invoke-WslRoot 'test -d /run/systemd/system' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # systemd isn't active in the current session yet -- restarting the
        # WSL *distro* (not Windows) applies the wsl.conf change. This is
        # fast and harmless, unlike a Windows reboot, so no confirmation
        # prompt is needed here the way Step 2's Windows-feature changes get.
        Write-Info 'Restarting the Linux environment to apply settings...'
        wsl.exe --terminate $WslDistro | Out-Null
        Start-Sleep -Seconds 3
        Invoke-WslRoot 'true' | Out-Null
        Start-Sleep -Seconds 3
    }

    Invoke-WslRoot 'systemctl enable --now docker' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Invoke-WslRoot 'service docker start' | Out-Null
    }

    Start-Sleep -Seconds 2
    Invoke-WslRoot 'docker info' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-ErrExit "Docker Engine installed but the background service isn't responding.`n`nPlease run 'Setup SlowBooks Pro.bat' again. If this keeps happening, see:`n  https://docs.docker.com/engine/install/ubuntu/#post-installation-steps"
    }

    Write-Info 'Docker Engine is running.'
}

# ---------------------------------------------------------------------------
# Step 4: copy the app into the WSL filesystem
#
# Docker builds/bind-mounts are slow across the Windows<->WSL2 boundary
# (the /mnt/c passthrough uses a network filesystem protocol under the
# hood). Keeping the app's own copy inside the Linux distro's native
# filesystem avoids that penalty entirely.
# ---------------------------------------------------------------------------
function Sync-AppToWsl {
    Write-Step 'Copying application files into the Linux environment...'

    $drive = $AppDir.Substring(0, 1).ToLower()
    $rest  = $AppDir.Substring(2) -replace '\\', '/'
    $wslSourcePosix = "/mnt/$drive$rest"

    Invoke-WslRoot 'command -v rsync >/dev/null || (apt-get update && apt-get install -y rsync)' | Out-Null

    $syncCmd = "mkdir -p $WslAppDirPosix && rsync -a --delete '$wslSourcePosix/' '$WslAppDirPosix/' 2>/dev/null || (rm -rf '$WslAppDirPosix' && mkdir -p '$WslAppDirPosix' && cp -r '$wslSourcePosix'/. '$WslAppDirPosix/')"
    Invoke-WslRoot $syncCmd | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-ErrExit "Could not copy application files into the Linux environment.`n`nPlease run 'Setup SlowBooks Pro.bat' again."
    }
    Write-Info 'Application files ready.'
}

# ---------------------------------------------------------------------------
# Step 5: finish -- shortcut for next time, then launch now
# ---------------------------------------------------------------------------
function New-DesktopShortcut {
    Write-Step 'Creating a shortcut for next time...'
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcutPath = Join-Path ([System.Environment]::GetFolderPath('Desktop')) 'Slowbooks Pro 2026.lnk'
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = Join-Path $AppDir 'Launch SlowBooks Pro.bat'
        $shortcut.WorkingDirectory = $AppDir
        $shortcut.IconLocation = 'shell32.dll,13'
        $shortcut.Save()
        Write-Info "Created: $shortcutPath"
    } catch {
        Write-Info "Could not create a desktop shortcut (not critical): $($_.Exception.Message)"
    }
}

function Start-App {
    Write-Step 'Launching Slowbooks Pro...'
    Push-Location $AppDir
    try {
        & python -m pip install --quiet -r requirements-desktop.txt
        & python desktop_launcher.py
    } finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Write-Host 'Slowbooks Pro 2026 -- Setup' -ForegroundColor Green
Write-Host 'This installs everything needed and then opens the app. It is safe to' -ForegroundColor Green
Write-Host 'run again if it stops partway through.' -ForegroundColor Green

Get-AppSource
Get-Python
Get-Wsl2
Get-DockerEngine
Sync-AppToWsl
New-DesktopShortcut
Start-App
