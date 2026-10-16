# Local Windows trial

Work only from `E:\HEXA-Admin`. Use a dedicated virtual environment and disposable directories under this worktree. Set a local administrator password in your terminal session; do not paste it into chat or commit it. The PowerShell command below generates one at runtime and shows it only on your laptop.

```powershell
Set-Location 'E:\HEXA-Admin'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
$env:HEXA_WEB_STORAGE = 'E:\HEXA-Admin\.hexa\admin-local\web'
$env:HEXA_WEB_UPLOAD_ROOT = 'E:\HEXA-Admin\.hexa\admin-local\uploads'
$env:HEXA_WORK_ROOT = 'E:\HEXA-Admin\.hexa\admin-local\work'
$env:HEXA_OUTPUT_ROOT = 'E:\HEXA-Admin\.hexa\admin-local\outputs'
$env:HEXA_EXPORT_ROOT = 'E:\HEXA-Admin\.hexa\admin-local\exports'
$env:HEXA_ADMIN_EMAIL = 'local-admin@example.invalid'
if (-not (Test-Path -LiteralPath (Join-Path $env:HEXA_WEB_STORAGE 'jobs.sqlite3'))) {
    $env:HEXA_ADMIN_BOOTSTRAP_PASSWORD = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
    Set-Clipboard -Value $env:HEXA_ADMIN_BOOTSTRAP_PASSWORD
    Write-Host 'New local administrator password copied to clipboard.'
} else {
    Remove-Item Env:HEXA_ADMIN_BOOTSTRAP_PASSWORD -ErrorAction SilentlyContinue
    Write-Host 'Existing local database: use the administrator password from the first setup.'
}
Write-Host "Local administrator email: $env:HEXA_ADMIN_EMAIL"
.\.venv\Scripts\python.exe -m app.web
```

Open `http://127.0.0.1:8787/login`. After login, open `Admin Dashboard`, create a normal user, log out, log in as that user, and change the temporary password. A valid local Final Package ZIP and narration audio are required for actual video generation; FFmpeg and FFprobe must be installed and discoverable. Use disposable exports for deletion checks.

The local database and media are under `.hexa/admin-local`, which is ignored by Git. Keep them separate from any production mount or VPS connection.
Paste the copied password into the login form on the first run, then clear the clipboard with `Set-Clipboard -Value ''`. Store the password in your password manager; bootstrap variables do not change an existing account on later starts.
