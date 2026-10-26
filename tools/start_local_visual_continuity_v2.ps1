# Isolated local test server for feature/visual-continuity-v2. No reset or cleanup action.
[CmdletBinding()]
param(
    [string]$StateRoot = 'E:\HEXA_Exports\_VISUAL_CONTINUITY_V2_LOCAL',
    [string]$PythonPath = '',
    [string]$AdminEmail = 'vc2-admin@localhost'
)

$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$branch = (& git -C $project branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne 'feature/visual-continuity-v2') {
    throw 'This launcher requires the feature/visual-continuity-v2 worktree.'
}
if (-not $PythonPath) {
    $PythonPath = Join-Path $project '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Set -PythonPath to a prepared Python environment.'
}
if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $StateRoot | Out-Null
}
$root = (Resolve-Path -LiteralPath $StateRoot).Path
if (((Get-Item -LiteralPath $root).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'Refusing a linked local state directory.'
}
if (Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8791 is already in use.'
}
$db = Join-Path $root 'web\jobs.sqlite3'
if (-not (Test-Path -LiteralPath $db) -and -not $env:HEXA_ADMIN_BOOTSTRAP_PASSWORD) {
    throw 'Set HEXA_ADMIN_BOOTSTRAP_PASSWORD for the first local start.'
}
$env:HEXA_WEB_STORAGE = Join-Path $root 'web'
$env:HEXA_WEB_UPLOAD_ROOT = Join-Path $root 'uploads'
$env:HEXA_WORK_ROOT = Join-Path $root 'work'
$env:HEXA_OUTPUT_ROOT = Join-Path $root 'outputs'
$env:HEXA_EXPORT_ROOT = Join-Path $root 'exports'
$env:HF_HOME = Join-Path $root 'cache\huggingface'
$env:XDG_CACHE_HOME = Join-Path $root 'cache\xdg'
$env:HEXA_WEB_HOST = '127.0.0.1'
$env:HEXA_WEB_PORT = '8791'
$env:HEXA_WEB_V2_ENABLED = '1'
$env:HEXA_VISUAL_CONTINUITY_V2 = '1'
$env:HEXA_ADMIN_EMAIL = $AdminEmail
Write-Host 'Visual Continuity V2 local server: http://127.0.0.1:8791/login'
& $PythonPath -m app.web
if ($LASTEXITCODE -ne 0) {
    throw "Local web process exited with code $LASTEXITCODE"
}
