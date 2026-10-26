# Isolated local test server for Visual Continuity V2 on the feature or montage branch.
[CmdletBinding()]
param(
    [string]$StateRoot = 'E:\HEXA_Exports\_VISUAL_CONTINUITY_V2_LOCAL',
    [string]$PythonPath = '',
    [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$branch = (& git -C $project branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -notin @('feature/visual-continuity-v2', 'montage')) {
    throw 'This launcher requires the Visual Continuity V2 feature or montage worktree.'
}
if (-not $PythonPath) {
    $PythonPath = Join-Path $project '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Set -PythonPath to a prepared Python environment.'
}
if (-not $EnvFile) {
    $projectEnv = Join-Path $project '.env'
    $sharedEnv = Join-Path (Split-Path $project -Parent) 'HEXA-StoryEngine-montage-consolidation\.env'
    $EnvFile = if (Test-Path -LiteralPath $projectEnv -PathType Leaf) { $projectEnv } else { $sharedEnv }
}
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "Credentials file not found: $EnvFile"
}
$credentials = @{}
foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
    if ($line -match '^\s*(HEXA_ADMIN_EMAIL|HEXA_ADMIN_BOOTSTRAP_PASSWORD)\s*=\s*(.*)$') {
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $credentials[$Matches[1]] = $value
    }
}
if (-not $credentials['HEXA_ADMIN_EMAIL'] -or -not $credentials['HEXA_ADMIN_BOOTSTRAP_PASSWORD']) {
    throw 'The credentials file must define HEXA_ADMIN_EMAIL and HEXA_ADMIN_BOOTSTRAP_PASSWORD.'
}
$env:HEXA_ADMIN_EMAIL = $credentials['HEXA_ADMIN_EMAIL']
$env:HEXA_ADMIN_BOOTSTRAP_PASSWORD = $credentials['HEXA_ADMIN_BOOTSTRAP_PASSWORD']
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
if (Test-Path -LiteralPath $db -PathType Leaf) {
    & $PythonPath (Join-Path $PSScriptRoot 'sync_local_visual_continuity_admin.py') $db
    if ($LASTEXITCODE -ne 0) {
        throw 'Local administrator credentials could not be synchronized with the credentials file.'
    }
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
Write-Host 'Visual Continuity V2 local server: http://127.0.0.1:8791/login'
& $PythonPath -m app.web
if ($LASTEXITCODE -ne 0) {
    throw "Local web process exited with code $LASTEXITCODE"
}
