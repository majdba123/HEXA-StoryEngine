# Development-only Windows reset/start. Never run this against a production directory.
[CmdletBinding()]
param([switch]$Reset)

$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$branch = (& git -C $project branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne 'montage') {
    throw 'This script must run from the montage branch checkout.'
}
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Python virtual environment missing. Set up .venv first.'
}

$stateRoot = Join-Path $project '.hexa'
$localRoot = Join-Path $stateRoot 'montage-local'
if ((Test-Path -LiteralPath $stateRoot) -and
    (((Get-Item -LiteralPath $stateRoot).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
    throw 'Refusing to use a linked .hexa directory.'
}

if ($Reset -and (Test-Path -LiteralPath $localRoot)) {
    # Reset is intentionally destructive for this ONE local test workspace.
    # Never archive, follow links, or touch any other .hexa directory or VPS data.
    $item = Get-Item -LiteralPath $localRoot
    if (-not $item.PSIsContainer -or
        (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'Unsafe local test directory; no data was deleted.'
    }
    $link = Get-ChildItem -LiteralPath $localRoot -Recurse -Force -ErrorAction Stop |
        Where-Object { ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 } |
        Select-Object -First 1
    if ($null -ne $link) {
        throw 'Refusing to delete local data containing filesystem links.'
    }
    $listener = Get-NetTCPConnection -LocalPort 8788 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw 'Stop the local HEXA server on port 8788 before resetting its database.'
    }
    Remove-Item -LiteralPath $localRoot -Recurse -Force -ErrorAction Stop
    Write-Host 'Deleted old local montage test state (SQLite, uploads, work, and exports). No archive was created.'
}

$env:HEXA_WEB_STORAGE = Join-Path $localRoot 'web'
$env:HEXA_WEB_UPLOAD_ROOT = Join-Path $localRoot 'uploads'
$env:HEXA_WORK_ROOT = Join-Path $localRoot 'work'
$env:HEXA_OUTPUT_ROOT = Join-Path $localRoot 'outputs'
$env:HEXA_EXPORT_ROOT = Join-Path $localRoot 'exports'
$env:HEXA_WEB_HOST = '127.0.0.1'
$env:HEXA_WEB_PORT = '8788'
$env:HEXA_ADMIN_EMAIL = 'majd@gmail.com'
$env:HEXA_ADMIN_BOOTSTRAP_PASSWORD = 'password2026!'
$env:HEXA_INITIAL_USER_EMAIL = 'majd1@gmail.com'
$env:HEXA_INITIAL_USER_PASSWORD = 'password2026!'

Write-Host 'Local-only HEXA montage: http://127.0.0.1:8788/login'
Write-Host 'ADMIN: majd@gmail.com / password2026!'
Write-Host 'USER:  majd1@gmail.com / password2026! (change required on first login)'
& $python -m app.web
if ($LASTEXITCODE -ne 0) {
    throw "HEXA local web process exited with code $LASTEXITCODE"
}
