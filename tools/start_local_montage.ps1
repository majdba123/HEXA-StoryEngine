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

$localRoot = Join-Path $project '.hexa\montage-local'
if (Test-Path -LiteralPath $localRoot) {
    $item = Get-Item -LiteralPath $localRoot
    if (-not $item.PSIsContainer -or (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'Unsafe local test directory; no state was changed.'
    }
    if ($Reset) {
        # Moving a directory on this volume is not a media backup or deletion.
        $archiveRoot = Join-Path $project '.hexa\local-archives'
        New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
        $id = [guid]::NewGuid().ToString('N').Substring(0, 8)
        $timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')
        $archive = Join-Path $archiveRoot "montage-local-$timestamp-$id"
        Move-Item -LiteralPath $localRoot -Destination $archive -ErrorAction Stop
        Write-Host "Archived previous local test data: $archive"
    }
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
