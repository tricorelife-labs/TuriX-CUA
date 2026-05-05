# TuriX-CUA Windows x64 one-shot setup.
#
# Usage (in the extracted bundle directory):
#   .\setup-win.ps1
#
# Idempotent: safe to re-run. Only unpacks env on first run.

$ErrorActionPreference = 'Stop'

$Dir          = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvDir       = Join-Path $Dir '.turix_env'
$EnvTarball   = Join-Path $Dir 'turix_env-win-amd64.tar.gz'
$Config       = Join-Path $Dir 'examples\config.json'
$Template     = Join-Path $Dir 'examples\config.example.json'

function Bold($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Warn($msg)  { Write-Host $msg -ForegroundColor Yellow }
function Err($msg)   { Write-Host $msg -ForegroundColor Red }

Bold '==> TuriX-CUA Windows setup'
Write-Host "    bundle dir: $Dir"

# 1. Arch check
$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -ne 'AMD64') {
    Err "Unsupported arch: $arch. This bundle is for AMD64 (x64)."
    exit 1
}
Write-Host '✓ AMD64 detected'

# 2. Unpack env (one-time)
$pythonExe = Join-Path $EnvDir 'python.exe'
if (-not (Test-Path $pythonExe)) {
    if (-not (Test-Path $EnvTarball)) {
        Err "Missing env tarball: $EnvTarball"
        exit 1
    }
    Bold '==> Unpacking conda env (first run, ~600 MB) ...'
    if (Test-Path $EnvDir) { Remove-Item -Recurse -Force $EnvDir }
    New-Item -ItemType Directory -Path $EnvDir | Out-Null
    # tar is built into Windows 10+; no extra deps needed.
    tar -xzf $EnvTarball -C $EnvDir
    if ($LASTEXITCODE -ne 0) { Err 'tar extract failed'; exit 1 }

    Bold '==> Fixing env paths (conda-unpack) ...'
    $unpack = Join-Path $EnvDir 'Scripts\conda-unpack.exe'
    if (-not (Test-Path $unpack)) {
        # fallback: some packs put it under bin/
        $unpack = Join-Path $EnvDir 'bin\conda-unpack.exe'
    }
    if (Test-Path $unpack) {
        & $unpack
    } else {
        Warn 'conda-unpack not found; entry-points may have stale paths'
    }
    Write-Host "✓ Env ready at $EnvDir"
} else {
    Write-Host "✓ Env already unpacked: $EnvDir"
}

# 3. Bootstrap config from template
if (-not (Test-Path $Config)) {
    if (-not (Test-Path $Template)) {
        Err "Missing $Template — bundle is incomplete."
        exit 1
    }
    Copy-Item $Template $Config
    Bold '==> Created examples\config.json from template'
}

# 4. Detect placeholder API key
if (Select-String -Path $Config -Pattern 'YOUR_DASHSCOPE_API_KEY' -Quiet) {
    Warn 'examples\config.json still has the placeholder API key.'
    Warn '  Edit and fill in your DashScope (or compatible) key, then re-run.'
    notepad $Config
    exit 0
}

# 5. Launch
Write-Host ''
Bold 'Launching the agent (Ctrl+Shift+2 to force-stop at runtime).'
Set-Location $Dir
& $pythonExe (Join-Path $Dir 'examples\main.py')
